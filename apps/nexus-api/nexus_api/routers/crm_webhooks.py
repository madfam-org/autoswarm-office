"""PhyndCRM webhook handler — receives CRM events and auto-dispatches tasks.

Maps CRM lifecycle events to SwarmTask dispatch via the playbook system.
Only dispatches if a matching enabled playbook exists for the event.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from selva_permissions import resolve_audience
from selva_redis_pool import get_redis_pool

from ..attribution import (
    domain_of,
    emit_lead_qualified,
    extract_lead_id,
)
from ..config import get_settings
from ..database import tenant_session
from ..models import SwarmTask, SwarmTaskOutbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gateway/phynd-crm", tags=["gateway"])

# CRM event → internal event key mapping
EVENT_MAP = {
    "lead.hot": "crm:hot_lead",
    "lead.created": "crm:lead_created",
    "activity.overdue": "crm:support_ticket",
    "opportunity.created": "crm:opportunity_created",
}


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 webhook signature from PhyndCRM."""
    if not secret:
        return True  # skip verification if no secret configured
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _webhook_secret(settings: Any) -> str:
    """Return the configured PhyndCRM webhook secret, if any.

    ``phynd_crm_webhook_secret`` is intentionally resolved with an env
    fallback because older Settings classes did not declare the field, but
    production operators may already provide PHYND_CRM_WEBHOOK_SECRET.
    """
    return (
        getattr(settings, "phynd_crm_webhook_secret", "")
        or os.getenv("PHYND_CRM_WEBHOOK_SECRET", "")
    )


def _idempotency_key(request: Request, payload: dict[str, Any], event_type: str) -> str:
    """Build a stable idempotency key for the durable task envelope."""
    header_key = request.headers.get("Idempotency-Key")
    if header_key:
        return header_key

    provider_key = (
        request.headers.get("X-PhyndCRM-Event-Id")
        or str(payload.get("idempotency_key") or "")
        or str(payload.get("event_id") or "")
        or str(payload.get("id") or "")
    )
    if provider_key:
        return provider_key

    return f"crm:{event_type}:{uuid.uuid4()}"


@router.post("")
async def phynd_crm_webhook(request: Request):
    """Receive webhook events from PhyndCRM and auto-dispatch agent tasks.

    Flow:
    1. Verify HMAC signature
    2. Map CRM event to internal event key
    3. Look up matching playbook via /api/v1/playbooks/match
    4. If playbook found and enabled → dispatch SwarmTask with playbook_id
    5. If no playbook → acknowledge but don't dispatch
    """
    settings = get_settings()
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-PhyndCRM-Signature", "")
    webhook_secret = _webhook_secret(settings)
    if settings.environment == "production" and webhook_secret and not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if webhook_secret and not _verify_signature(body, signature, webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    event_type = payload.get("event", "")
    data = payload.get("data", {})

    logger.info("PhyndCRM webhook received: event=%s", event_type)

    # Map to internal event key
    internal_event = EVENT_MAP.get(event_type)
    if not internal_event:
        return {"status": "ok", "event": event_type, "ignored": True}

    # Look up matching playbook
    from .playbooks import _playbooks

    matching_playbook = None
    for pb in _playbooks.values():
        if pb["trigger_event"] == internal_event and pb["enabled"] and not pb["require_approval"]:
            matching_playbook = pb
            break

    if not matching_playbook:
        logger.info(
            "No matching playbook for CRM event %s (%s), skipping dispatch",
            event_type,
            internal_event,
        )
        return {"status": "ok", "event": event_type, "no_playbook": True}

    # Auto-dispatch a SwarmTask
    try:
        graph_type_map = {
            "crm:hot_lead": "crm",
            "crm:lead_created": "crm",
            "crm:support_ticket": "support",
            "crm:opportunity_created": "crm",
        }
        graph_type = graph_type_map.get(internal_event, "research")

        # Build task description from CRM event data. PII-safe: reference
        # lead_id, not contact_name, so logs / ops dashboards stay clean.
        contact_email = data.get("contact_email", data.get("email", ""))

        # T3.2 — extract a stable `lead_id` and thread it through the funnel.
        lead_id = extract_lead_id(data)

        description = f"CRM auto-dispatch: {event_type} for lead:{lead_id}"

        task_payload = {
            "trigger_event": internal_event,
            "crm_event": event_type,
            "crm_data": data,
            "playbook_id": matching_playbook["id"],
            # Attribution glue — preserved across the hop to the worker.
            "lead_id": lead_id,
            "utm_source": data.get("utm_source", "selva"),
            "utm_campaign": data.get("utm_campaign", "hot_lead_auto"),
        }

        org_id = str(
            payload.get("org_id")
            or data.get("org_id")
            or matching_playbook.get("org_id")
            or "madfam-default"
        )
        audience = resolve_audience(org_id).value
        idempotency_key = _idempotency_key(request, payload, event_type)
        request_id = getattr(request.state, "request_id", None)

        canonical_envelope: dict[str, Any] = {
            "schema": "selva.task-envelope/v1",
            "task_id": None,
            "org_id": org_id,
            "audience": audience,
            "graph_type": graph_type,
            "idempotency_key": idempotency_key,
            "source": "crm-webhook",
            "desired_state_hash": None,
            "request_id": request_id,
        }
        task_payload = {
            **task_payload,
            "_selva_envelope": canonical_envelope,
        }

        async with tenant_session(org_id) as db:
            task = SwarmTask(
                description=description,
                graph_type=graph_type,
                assigned_agent_ids=[],
                payload=task_payload,
                status="queued",
                org_id=org_id,
            )
            db.add(task)
            await db.flush()
            await db.refresh(task)

            task_id = str(task.id)
            canonical_envelope["task_id"] = task_id
            task.payload = {
                **(task.payload or {}),
                "_selva_envelope": canonical_envelope,
            }
            await db.flush()

            task_msg_data: dict[str, Any] = {
                "schema": "selva.task-envelope/v1",
                "task_id": task_id,
                "org_id": org_id,
                "audience": audience,
                "graph_type": graph_type,
                "idempotency_key": idempotency_key,
                "source": "crm-webhook",
                "desired_state_hash": None,
                "description": description,
                "assigned_agent_ids": [],
                "required_skills": ["crm-outreach"],
                "payload": task.payload,
                "request_id": request_id,
                "playbook_id": matching_playbook["id"],
                "playbook": matching_playbook,
                # Promote lead_id to a top-level field for downstream consumers
                # (worker initial_state loader, ops dashboards) that don't
                # want to reach into payload.
                "lead_id": lead_id,
            }

            outbox = SwarmTaskOutbox(
                task_id=task.id,
                org_id=org_id,
                stream_name="selva:task-stream",
                payload=task_msg_data,
            )
            db.add(outbox)
            await db.flush()

            pool = get_redis_pool(url=settings.redis_url)
            try:
                msg_id = await pool.execute_with_retry(
                    "xadd",
                    "selva:task-stream",
                    {"data": json.dumps(task_msg_data)},
                )
                task.stream_message_id = str(msg_id)
                outbox.status = "sent"
                outbox.stream_message_id = str(msg_id)
                outbox.sent_at = datetime.now(UTC)
                await db.flush()
            except Exception as exc:
                task.status = "pending"
                outbox.status = "retryable"
                outbox.retry_count += 1
                outbox.last_error = str(exc)[:2000]
                await db.flush()
                logger.warning(
                    "Redis unavailable; CRM task %s persisted as pending",
                    task_id,
                    exc_info=True,
                )

            try:
                from .events import emit_event_db

                await emit_event_db(
                    db,
                    event_type="task.dispatched",
                    event_category="task",
                    task_id=task.id,
                    graph_type=task.graph_type,
                    org_id=org_id,
                    request_id=request_id,
                    payload={"description": description[:200], "graph_type": graph_type},
                )
            except Exception:
                logger.debug("Failed to emit task.dispatched event", exc_info=True)

        logger.info(
            "CRM auto-dispatch: task=%s event=%s playbook=%s",
            task_id,
            event_type,
            matching_playbook["name"],
        )

        # T3.2 attribution funnel — emit `lead.qualified` with the
        # anonymous lead_id as distinct_id. Never use contact_email as
        # distinct_id: that would fork the funnel once the user
        # authenticates with Janua.
        try:
            emit_lead_qualified(
                lead_id,
                trigger_event=internal_event,
                playbook_name=matching_playbook["name"],
                task_id=task_id,
                utm_source=task_payload.get("utm_source", "selva"),
                extra={
                    "crm_event": event_type,
                    "graph_type": graph_type,
                    "recipient_domain": domain_of(contact_email),
                },
            )
        except Exception:
            logger.debug("emit_lead_qualified failed (non-fatal)", exc_info=True)

        # Legacy ops event kept for the existing dashboards — distinct
        # from the attribution funnel above.
        try:
            from ..analytics import track

            track(
                "system",
                "selva_crm_auto_dispatch",
                {
                    "event": event_type,
                    "playbook": matching_playbook["name"],
                    "task_id": task_id,
                    "lead_id": lead_id,
                },
            )
        except Exception:
            pass

        return {
            "status": "dispatched",
            "task_id": task_id,
            "playbook": matching_playbook["name"],
            "graph_type": graph_type,
            "lead_id": lead_id,
        }

    except Exception as exc:
        logger.exception("CRM auto-dispatch failed: %s", exc)
        return {"status": "error", "message": str(exc)}
