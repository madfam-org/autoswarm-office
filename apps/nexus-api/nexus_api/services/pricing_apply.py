"""Apply Tulana pricing proposals to Dhanam catalog after Selva HITL approval."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from nexus_api.config import get_settings

logger = logging.getLogger(__name__)


def _catalog_apply_secret() -> str:
    settings = get_settings()
    return (
        (settings.dhanam_catalog_apply_secret or "").strip()
        or os.environ.get("DHANAM_CATALOG_APPLY_SECRET", "").strip()
        or os.environ.get("TULANA_SELVA_CATALOG_APPLY_SECRET", "").strip()
    )


def _dhanam_base_url() -> str:
    settings = get_settings()
    raw = (settings.dhanam_api_url or "").strip() or os.environ.get("DHANAM_API_URL", "").strip()
    return raw.rstrip("/")


async def apply_price_to_dhanam_catalog(
    preview: dict[str, Any],
    *,
    recommendation_id: int | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """POST /v1/internal/catalog/apply-price on Dhanam billing API."""
    base = _dhanam_base_url()
    secret = _catalog_apply_secret()
    if not base:
        raise RuntimeError("DHANAM_API_URL not configured")
    if not secret:
        raise RuntimeError("DHANAM_CATALOG_APPLY_SECRET not configured")

    product_slug = str(preview.get("productSlug") or preview.get("product_slug") or "").strip()
    tier_slug = str(preview.get("tierSlug") or preview.get("tier_slug") or "").strip()
    amount = preview.get("amountCentavos") or preview.get("amount_cents")
    if not product_slug or not tier_slug:
        raise ValueError("dhanam_payload_preview missing productSlug/tierSlug")
    if amount is None:
        raise ValueError("dhanam_payload_preview missing amountCentavos")

    amount_cents = int(amount)
    if amount_cents < 1:
        raise ValueError("amountCentavos must be >= 1")

    payload = {
        "product_slug": product_slug,
        "tier_slug": tier_slug,
        "amount_cents": amount_cents,
        "currency": str(preview.get("currency") or "MXN"),
        "interval": _interval_from_preview(preview),
        "source": "tulana_selva",
        "recommendation_id": recommendation_id,
        "approval_id": approval_id,
        "metadata": {
            "tulana_preview": preview,
        },
    }

    url = f"{base}/v1/internal/catalog/apply-price"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"X-Dhanam-Catalog-Apply-Secret": secret},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Dhanam catalog apply failed ({resp.status_code}): {resp.text[:500]}"
        )
    return resp.json()


def _interval_from_preview(preview: dict[str, Any]) -> str:
    raw = str(preview.get("interval") or "monthly").lower()
    if raw in ("month", "monthly"):
        return "monthly"
    if raw in ("year", "yearly", "annual"):
        return "yearly"
    return "monthly"


async def apply_pricing_proposal_on_approve(
    approval_row: Any,
    db: Any,
    *,
    responded_by: str = "",
) -> dict[str, Any]:
    """After human approval in Selva, push price to Dhanam catalog."""
    payload = approval_row.payload if isinstance(approval_row.payload, dict) else {}
    preview = payload.get("dhanam_payload_preview") or {}
    rec_id = payload.get("recommendation_id")
    try:
        rec_id_int = int(rec_id) if rec_id is not None else None
    except (TypeError, ValueError):
        rec_id_int = None

    try:
        result = await apply_price_to_dhanam_catalog(
            preview,
            recommendation_id=rec_id_int,
            approval_id=str(approval_row.id),
        )
        logger.info(
            "Dhanam catalog apply ok approval=%s product=%s tier=%s",
            approval_row.id,
            preview.get("productSlug"),
            preview.get("tierSlug"),
        )
        return {"ok": True, "dhanam": result}
    except Exception as exc:
        logger.exception("Dhanam catalog apply failed approval=%s", approval_row.id)
        return {"ok": False, "error": str(exc)}


async def notify_tulana_outcome(
    approval_row: Any,
    *,
    result: str,
    responded_by: str = "",
    notes: str = "",
    dhanam_apply: dict[str, Any] | None = None,
) -> None:
    """POST outcome to Tulana internal webhook (approve or deny)."""
    settings = get_settings()
    base = (settings.tulana_api_url or "").strip() or os.environ.get("TULANA_API_URL", "").strip()
    secret = (settings.tulana_selva_webhook_secret or "").strip() or os.environ.get(
        "TULANA_SELVA_WEBHOOK_SECRET", ""
    ).strip()
    if not base or not secret:
        logger.warning("TULANA_API_URL or TULANA_SELVA_WEBHOOK_SECRET unset — skip notify")
        return

    body: dict[str, Any] = {
        "approval_id": str(approval_row.id),
        "result": result,
        "responded_by": responded_by,
        "notes": notes,
    }
    if dhanam_apply is not None:
        body["dhanam"] = dhanam_apply

    url = f"{base.rstrip('/')}/api/v1/internal/selva/approval-outcome/"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"X-Tulana-Selva-Secret": secret},
            )
        if resp.status_code >= 400:
            logger.error(
                "Tulana webhook failed status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
    except Exception:
        logger.exception("Tulana webhook request failed approval=%s", approval_row.id)
