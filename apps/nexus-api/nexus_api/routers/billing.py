"""Billing, usage, and compute token endpoints (Dhanam proxy)."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import ComputeTokenLedger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"], dependencies=[Depends(get_current_user)])


@router.get("/status")
async def billing_status() -> dict[str, object]:
    """Proxy to the Dhanam billing API to retrieve subscription status.

    Falls back to a local stub when the Dhanam API is unreachable so the
    office UI can still render a meaningful state.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.dhanam_api_url.rstrip('/')}/v1/subscription/status",
                headers={"Authorization": f"Bearer {settings.dhanam_webhook_secret}"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Dhanam billing API unreachable: %s", exc)
        # Return a graceful degradation response.
        return {
            "tier": "starter",
            "is_active": True,
            "message": "Billing service temporarily unavailable; showing cached tier",
        }


@router.get("/usage")
async def compute_usage(
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return compute token usage aggregated from the ledger.

    Groups usage by action type for the current UTC day.
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            ComputeTokenLedger.action,
            func.sum(ComputeTokenLedger.amount).label("total"),
            func.count(ComputeTokenLedger.id).label("count"),
        )
        .where(ComputeTokenLedger.created_at >= today_start)
        .group_by(ComputeTokenLedger.action)
    )
    rows = result.all()

    usage_by_action = {row.action: {"total_tokens": row.total, "count": row.count} for row in rows}
    grand_total = sum(entry["total_tokens"] for entry in usage_by_action.values())

    return {
        "date": today_start.date().isoformat(),
        "total_used": grand_total,
        "by_action": usage_by_action,
    }


@router.get("/tokens")
async def compute_token_status(
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return the current compute token bucket status.

    The daily limit is sourced from the subscription tier; usage is
    summed from the ledger for today.
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.coalesce(func.sum(ComputeTokenLedger.amount), 0)).where(
            ComputeTokenLedger.created_at >= today_start
        )
    )
    used: int = result.scalar_one()

    # Default daily limit for the starter tier.  In production this would
    # come from the Dhanam subscription capabilities.
    daily_limit = 1000

    return {
        "daily_limit": daily_limit,
        "used": used,
        "remaining": max(0, daily_limit - used),
        "reset_at": (
            today_start.replace(day=today_start.day + 1).isoformat()
            if today_start.day < 28
            else today_start.isoformat()
        ),
    }


@router.post("/portal")
async def create_billing_portal() -> dict[str, object]:
    """Create a Dhanam billing portal session for self-service management."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.dhanam_api_url.rstrip('/')}/billing/portal",
                headers={"Authorization": f"Bearer {settings.dhanam_webhook_secret}"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Dhanam portal API unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Billing service unavailable",
        ) from exc


@router.post("/webhooks/dhanam", include_in_schema=False, dependencies=[])
async def dhanam_webhook(request: Request) -> dict[str, str]:
    """Receive and verify webhooks from the Dhanam billing system."""
    settings = get_settings()
    body = await request.body()
    signature = request.headers.get("x-dhanam-signature", "")

    if settings.dhanam_webhook_secret:
        expected = hmac_mod.new(
            settings.dhanam_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac_mod.compare_digest(expected, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )

    payload = json.loads(body)
    event_type = payload.get("type", "unknown")
    logger.info("Received Dhanam webhook event: %s", event_type)

    return {"status": "ok"}
