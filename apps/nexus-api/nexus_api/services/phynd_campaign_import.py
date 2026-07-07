"""Selva → PhyndCRM campaign-import bridge (RFC 0031 campaign loop).

The `crm-handoff` endpoint enqueues a Redis task for the CRM graph, but nothing
POSTed the campaign into PhyndCRM — the loop's first structural break. This
bridge closes it: it maps a governed crm-handoff payload (Selva `generate-copy`
draft variants + the Tulana pack) onto PhyndCRM's
`POST /api/v1/campaigns/import` contract and HMAC-signs it the way PhyndCRM's
`validateWebhookSignature` expects.

Inert until configured: if `phynd_crm_url` or `phynd_campaign_import_secret` is
unset, `push_campaign_import` is a no-op that returns a skipped result, so the
handoff still enqueues its task and nothing breaks. This lets the full loop be
exercised (dry-run) before the shared secret exists.

Signature scheme (must match phynd-crm/packages/federation webhook-validator):
    x-webhook-signature: sha256=<hex hmac-sha256 of the raw JSON body>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


def _phynd_config() -> tuple[str | None, str]:
    settings = get_settings()
    base = (settings.phynd_crm_url or "").strip() or None
    secret = (settings.phynd_campaign_import_secret or "").strip()
    return base, secret


_GA_READINESS_MAP = {
    # Tulana pack readiness → PhyndCRM import enum (not_ready | near_ready | ready)
    "not_ready": "not_ready",
    "near_ready": "near_ready",
    "ready": "ready",
    # tolerate the pricing-side vocabulary if a pack carries it
    "ga_ready": "ready",
    "candidate": "near_ready",
    "blocked": "not_ready",
}


def build_campaign_import_payload(
    *,
    handoff_id: str,
    sku_key: str,
    platform: str,
    audience: str | None,
    campaign_name: str,
    value_prop: str,
    ga_readiness: str,
    draft_variants: list[dict[str, Any]],
    proof_points: list[dict[str, Any]] | None = None,
    human_approver_email: str | None = None,
    gate_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map a crm-handoff into PhyndCRM's tulanaCampaignImportSchema shape.

    ``idempotency_key`` is derived from the handoff id + sku so replays of the
    same handoff dedupe on the PhyndCRM side (campaignImports.idempotencyKey).
    """
    return {
        "idempotency_key": f"selva-handoff:{handoff_id}:{sku_key}",
        "source": "selva",
        "orchestrator": "selva.crm_handoff",
        "sku_key": sku_key,
        "platform": platform,
        **({"audience": audience} if audience else {}),
        "ga_readiness": _GA_READINESS_MAP.get(ga_readiness, "not_ready"),
        **({"human_approver_email": human_approver_email} if human_approver_email else {}),
        "gate_evidence": gate_evidence or [],
        "value_prop": value_prop,
        "proof_points": proof_points or [],
        # Structured governed variants from generate-copy (subject/preheader/
        # body/cta/claim_keys_used). PhyndCRM persists these to
        # campaign_draft_variants for the claims audit trail.
        "draft_variants": draft_variants,
    }


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def push_campaign_import(payload: dict[str, Any]) -> dict[str, Any]:
    """HMAC-POST a campaign-import payload to PhyndCRM.

    Returns ``{"status": "skipped", ...}`` when the bridge is unconfigured (so
    callers stay dry-run-safe), or ``{"status": "sent", "http_status": ...}`` on
    a delivered POST. Never raises into the handoff path — a bridge failure must
    not fail the handoff (the Redis task is still enqueued for the CRM graph).
    """
    base, secret = _phynd_config()
    if not base or not secret:
        logger.info("Phynd campaign-import bridge not configured; skipping POST")
        return {"status": "skipped", "reason": "not_configured"}

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    url = f"{base.rstrip('/')}/api/v1/campaigns/import"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-webhook-signature": _sign(body, secret),
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Phynd campaign-import POST failed: %s", exc)
        return {"status": "error", "reason": "unreachable"}

    if resp.status_code >= 400:
        logger.warning(
            "Phynd campaign-import rejected (%s): %s", resp.status_code, resp.text[:300]
        )
        return {"status": "error", "http_status": resp.status_code}

    return {"status": "sent", "http_status": resp.status_code}
