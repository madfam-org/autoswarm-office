"""Tulana SKU campaign import and planning endpoints (Phase 2)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..auth import get_current_user, require_non_guest
from ..config import get_settings
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import SwarmTask, SwarmTaskOutbox
from ..schemas.tulana_campaign import (
    CrmCampaignHandoffRequest,
    CrmCampaignHandoffResponse,
    TulanaImportRequest,
    TulanaImportResponse,
)
from ..services.tulana_campaign import import_tulana_packs, validate_pack
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


async def _dispatch_planning_tasks(
    *,
    db: AsyncSession,
    tenant: TenantContext,
    request: Request,
    import_result: TulanaImportResponse,
    idempotency_prefix: str,
) -> list[str]:
    """Enqueue one campaign-graph task per accepted SKU (Phase 2.2)."""
    from selva_permissions import resolve_audience

    settings = get_settings()
    request_id = getattr(request.state, "request_id", None)
    task_audience = resolve_audience(tenant.org_id).value
    dispatched: list[str] = []

    for index, pack in enumerate(import_result.accepted):
        task_id = uuid.uuid4()
        idempotency_key = f"{idempotency_prefix}:{pack.sku_key}:{index}"
        canonical_envelope: dict[str, Any] = {
            "schema": "selva.task-envelope/v1",
            "task_id": str(task_id),
            "org_id": tenant.org_id,
            "audience": task_audience,
            "graph_type": "campaign",
            "idempotency_key": idempotency_key,
            "source": "tulana-campaign-import",
            "desired_state_hash": None,
            "request_id": request_id,
        }
        payload: dict[str, Any] = {
            "campaign_category": "sku_campaign_planning",
            "tulana_pack": pack.model_dump(mode="json"),
            "_selva_envelope": canonical_envelope,
        }
        description = (
            f"Plan campaign lane for {pack.sku_key} ({pack.audience}) — "
            f"readiness={pack.ga_readiness}"
        )
        task = SwarmTask(
            id=task_id,
            title=f"Campaign plan: {pack.sku_key}",
            description=description[:2000],
            graph_type="campaign",
            assigned_agent_ids=[],
            payload=payload,
            status="queued",
            kanban_status="todo",
            priority="medium",
            labels=["campaign", "tulana", pack.sku_key],
            org_id=tenant.org_id,
        )
        db.add(task)
        await db.flush()

        task_msg_data: dict[str, Any] = {
            "schema": "selva.task-envelope/v1",
            "task_id": str(task.id),
            "org_id": tenant.org_id,
            "audience": task_audience,
            "graph_type": "campaign",
            "idempotency_key": idempotency_key,
            "source": "tulana-campaign-import",
            "description": task.description,
            "assigned_agent_ids": [],
            "required_skills": ["campaign-planning"],
            "payload": task.payload,
            "request_id": request_id,
        }
        outbox = SwarmTaskOutbox(
            task_id=task.id,
            org_id=tenant.org_id,
            stream_name="autoswarm:task-stream",
            payload=task_msg_data,
        )
        db.add(outbox)
        await db.flush()

        try:
            pool = get_redis_pool(url=settings.redis_url)
            msg_id = await pool.execute_with_retry(
                "xadd",
                "autoswarm:task-stream",
                {"data": json.dumps(task_msg_data)},
            )
            task.stream_message_id = str(msg_id)
            outbox.status = "sent"
            outbox.stream_message_id = str(msg_id)
            outbox.sent_at = datetime.now(UTC)
            await db.flush()
        except Exception:
            logger.warning(
                "Redis publish failed for campaign task %s; outbox row retained",
                task.id,
                exc_info=True,
            )

        dispatched.append(str(task.id))

    return dispatched


@router.post(
    "/import-tulana-pack",
    response_model=TulanaImportResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_non_guest)],
)
async def import_tulana_pack(
    body: TulanaImportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> TulanaImportResponse:
    """Validate and rank Tulana SKU campaign packs; optionally enqueue planning tasks."""
    cached = getattr(idem, "cached", None)
    if getattr(idem, "is_replay", False) and cached is not None:
        return TulanaImportResponse.model_validate(cached)

    result = import_tulana_packs(body)

    if body.dispatch_tasks and result.accepted:
        prefix = request.headers.get("Idempotency-Key") or f"tulana-import:{tenant.org_id}"
        result.dispatched_task_ids = await _dispatch_planning_tasks(
            db=db,
            tenant=tenant,
            request=request,
            import_result=result,
            idempotency_prefix=prefix,
        )

    await idem.save(result.model_dump(mode="json"))
    logger.info(
        "Tulana import org=%s user=%s accepted=%d rejected=%d dispatched=%d",
        tenant.org_id,
        user.get("sub"),
        len(result.accepted),
        len(result.rejected),
        len(result.dispatched_task_ids),
    )
    return result


@router.post(
    "/crm-handoff",
    response_model=CrmCampaignHandoffResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def crm_campaign_handoff(
    body: CrmCampaignHandoffRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> CrmCampaignHandoffResponse:
    """Stage human-approved campaign drafts for Phynd CRM handoff (Phase 2.4)."""
    cached = getattr(idem, "cached", None)
    if getattr(idem, "is_replay", False) and cached is not None:
        return CrmCampaignHandoffResponse.model_validate(cached)

    validation = validate_pack(body.tulana_pack, allow_blocked=False)
    if not validation.accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid Tulana pack", "errors": validation.errors},
        )

    settings = get_settings()
    request_id = getattr(request.state, "request_id", None)
    from selva_permissions import resolve_audience

    task_audience = resolve_audience(tenant.org_id).value
    handoff_id = str(uuid.uuid4())
    idempotency_key = (
        request.headers.get("Idempotency-Key") or f"crm-handoff:{handoff_id}:{body.sku_key}"
    )
    task_id = uuid.uuid4()
    canonical_envelope: dict[str, Any] = {
        "schema": "selva.task-envelope/v1",
        "task_id": str(task_id),
        "org_id": tenant.org_id,
        "audience": task_audience,
        "graph_type": "crm",
        "idempotency_key": idempotency_key,
        "source": "tulana-crm-handoff",
        "desired_state_hash": None,
        "request_id": request_id,
    }
    payload: dict[str, Any] = {
        "campaign_category": "crm_campaign_handoff",
        "handoff_id": handoff_id,
        "sku_key": body.sku_key,
        "audience": body.audience,
        "campaign_name": body.campaign_name or f"{body.sku_key} → {body.audience}",
        "draft_variants": body.draft_variants,
        "phynd_list_id": body.phynd_list_id,
        "tulana_pack": body.tulana_pack.model_dump(mode="json"),
        "require_approval": True,
        "_selva_envelope": canonical_envelope,
    }
    task = SwarmTask(
        id=task_id,
        title=f"CRM handoff: {body.sku_key}",
        description=f"Hand approved drafts to Phynd CRM for {body.audience}"[:2000],
        graph_type="crm",
        assigned_agent_ids=[],
        payload=payload,
        status="queued",
        kanban_status="review",
        priority="high",
        labels=["campaign", "crm-handoff", body.sku_key],
        org_id=tenant.org_id,
    )
    db.add(task)
    await db.flush()

    task_msg_data: dict[str, Any] = {
        "schema": "selva.task-envelope/v1",
        "task_id": str(task.id),
        "org_id": tenant.org_id,
        "audience": task_audience,
        "graph_type": "crm",
        "idempotency_key": idempotency_key,
        "source": "tulana-crm-handoff",
        "description": task.description,
        "assigned_agent_ids": [],
        "required_skills": ["campaign-planning"],
        "payload": task.payload,
        "request_id": request_id,
    }
    outbox = SwarmTaskOutbox(
        task_id=task.id,
        org_id=tenant.org_id,
        stream_name="autoswarm:task-stream",
        payload=task_msg_data,
    )
    db.add(outbox)
    await db.flush()

    try:
        pool = get_redis_pool(url=settings.redis_url)
        msg_id = await pool.execute_with_retry(
            "xadd",
            "autoswarm:task-stream",
            {"data": json.dumps(task_msg_data)},
        )
        task.stream_message_id = str(msg_id)
        outbox.status = "sent"
        outbox.stream_message_id = str(msg_id)
        outbox.sent_at = datetime.now(UTC)
        await db.flush()
    except Exception:
        logger.warning(
            "Redis publish failed for CRM handoff task %s; outbox row retained",
            task.id,
            exc_info=True,
        )

    response = CrmCampaignHandoffResponse(
        handoff_id=handoff_id,
        task_id=str(task.id),
        status="queued",
        message="Campaign handoff queued for Phynd CRM staging (HITL required)",
    )
    await idem.save(response.model_dump(mode="json"))
    return response
