"""Push validated campaign outcomes to Tulana buyer-signal API (Phase 2.6)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException, status

from ..config import get_settings
from ..schemas.tulana_campaign import TulanaFeedbackRequest, TulanaFeedbackResponse

logger = logging.getLogger(__name__)


def _tulana_config() -> tuple[str, str]:
    settings = get_settings()
    base = (settings.tulana_api_url or "").strip() or os.environ.get("TULANA_API_URL", "").strip()
    secret = (settings.tulana_selva_webhook_secret or "").strip() or os.environ.get(
        "TULANA_SELVA_WEBHOOK_SECRET", ""
    ).strip()
    return base, secret


async def push_tulana_buyer_signal(
    *,
    org_id: str,
    body: TulanaFeedbackRequest,
    actor_sub: str | None = None,
) -> TulanaFeedbackResponse:
    """POST campaign evidence to Tulana internal buyer-signal endpoint."""
    base, secret = _tulana_config()
    if not base or not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tulana feedback not configured (TULANA_API_URL / TULANA_SELVA_WEBHOOK_SECRET)",
        )

    payload: dict[str, Any] = {
        "org_id": org_id,
        "sku_key": body.sku_key,
        "summary": body.summary,
        "outcomes": [item.model_dump(mode="json") for item in body.outcomes],
        "campaign_name": body.campaign_name,
        "handoff_id": body.handoff_id,
        "task_id": body.task_id,
        "evidence_urls": body.evidence_urls,
        "source": "selva.tulana_feedback_update",
        "actor_sub": actor_sub,
    }

    url = f"{base.rstrip('/')}/api/v1/internal/selva/buyer-signal/"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Tulana-Selva-Secret": secret},
            )
    except httpx.HTTPError as exc:
        logger.warning("Tulana buyer-signal request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Tulana buyer-signal API unreachable",
        ) from exc

    if resp.status_code == 404:
        logger.error(
            "Tulana buyer-signal route missing status=%s url=%s",
            resp.status_code,
            url,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Tulana buyer-signal route not deployed "
                "(POST /api/v1/internal/selva/buyer-signal/)"
            ),
        )

    if resp.status_code >= 400:
        logger.error(
            "Tulana buyer-signal rejected status=%s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Tulana buyer-signal rejected the payload",
        )

    data = resp.json() if resp.content else {}
    event_id = data.get("event_id") or data.get("id")
    return TulanaFeedbackResponse(
        status="accepted",
        tulana_event_id=str(event_id) if event_id else None,
        message="Campaign outcomes recorded in Tulana buyer-signal ledger",
    )
