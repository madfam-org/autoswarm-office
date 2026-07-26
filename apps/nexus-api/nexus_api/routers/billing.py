"""Billing, usage, and compute token endpoints (Dhanam proxy)."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import ComputeTokenLedger
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"], dependencies=[Depends(get_current_user)])
webhook_router = APIRouter(tags=["billing-webhooks"])

# Replayed billing events are dangerous on a money surface: a re-delivered
# subscription.deleted can downgrade a paying customer, a re-delivered
# invoice.paid can clear a real overage counter. The Stripe handler already
# rejects replays via signed-timestamp tolerance; Dhanam's HMAC alone does
# not, so we add a first-write-wins idempotency guard keyed on the event id.
_WEBHOOK_DEDUP_TTL_SECONDS = 24 * 60 * 60


async def _claim_webhook_event(event_id: str) -> bool:
    """Atomically claim a webhook event id. Returns True on first sight,
    False if already processed (a replay). Fails OPEN — if Redis is
    unreachable we process the event rather than silently drop billing
    state, matching the fire-and-forget posture elsewhere in this path."""
    try:
        from selva_redis_pool import get_redis_pool

        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        # SET key value NX EX ttl → truthy only when the key did not exist.
        claimed = await pool.execute_with_retry(
            "set",
            f"selva:webhook:dhanam:{event_id}",
            "1",
            nx=True,
            ex=_WEBHOOK_DEDUP_TTL_SECONDS,
        )
        return bool(claimed)
    except Exception:
        logger.warning(
            "Webhook dedup unavailable (Redis) for event=%s; processing anyway",
            event_id,
            exc_info=True,
        )
        return True


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
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> dict[str, object]:
    """Return compute token usage aggregated from the ledger.

    Groups usage by action type for the current UTC day.
    """
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            ComputeTokenLedger.action,
            func.sum(ComputeTokenLedger.amount).label("total"),
            func.count(ComputeTokenLedger.id).label("count"),
        )
        .where(ComputeTokenLedger.created_at >= today_start)
        .where(ComputeTokenLedger.org_id == tenant.org_id)
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
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> dict[str, object]:
    """Return the current compute token bucket status.

    The daily limit is sourced from the subscription tier; usage is
    summed from the ledger for today.
    """
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.coalesce(func.sum(ComputeTokenLedger.amount), 0)).where(
            ComputeTokenLedger.created_at >= today_start,
            ComputeTokenLedger.org_id == tenant.org_id,
        )
    )
    used: int = result.scalar_one()

    from ..services.tier_limits import resolve_org_daily_limit

    daily_limit = await resolve_org_daily_limit(db, tenant.org_id)

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
    # Goes through DhanamClient rather than building the URL inline: the
    # inline version omitted the /v1 segment Dhanam serves everything under,
    # so every portal request 404'd. One normalisation point, one place to
    # get it wrong.
    from ..billing_client import DhanamClient

    settings = get_settings()
    client = DhanamClient(settings.dhanam_api_url, settings.dhanam_webhook_secret)
    try:
        return await client.create_portal_session(settings.dhanam_webhook_secret)
    except httpx.HTTPError as exc:
        logger.warning("Dhanam portal API unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Billing service unavailable",
        ) from exc


@router.get("/agent-hours")
async def agent_hours_usage(
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> dict[str, object]:
    """Metered agent-hours consumed by the caller's org this calendar month.

    This is the consumption surface for Selva's Tulana hourly packs
    (Maker/Studio/Enterprise). Dhanam reads accrued hours at invoice time;
    this endpoint surfaces the running total for the UI and reporting.
    """
    from ..models import AgentHoursLedger

    month_start = datetime.now(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(
            func.coalesce(func.sum(AgentHoursLedger.agent_hours), 0),
            func.count(AgentHoursLedger.id),
        ).where(
            AgentHoursLedger.created_at >= month_start,
            AgentHoursLedger.org_id == tenant.org_id,
        )
    )
    total_hours, task_count = result.one()
    return {
        "period_start": month_start.isoformat(),
        "agent_hours": float(total_hours),
        "task_count": int(task_count),
    }


@router.get("/tiers")
async def list_subscription_tiers() -> dict[str, object]:
    """Return the purchasable subscription tiers for the pricing page.

    Source of truth is ``infra/pricing/selva-tiers.json`` via
    ``billing_tiers.get_subscription_tiers`` — the CI drift gate keeps this
    from diverging from the canonical numbers.
    """
    from ..billing_tiers import get_subscription_tiers

    return {"tiers": get_subscription_tiers()}


class CheckoutRequest(BaseModel):
    tier: str = Field(..., min_length=1, max_length=64)
    # Optional client-provided return paths; the server rewrites them onto
    # PUBLIC_APP_URL so a caller cannot redirect checkout to an arbitrary host.
    success_path: str = Field(default="/office?upgraded=1", max_length=512)
    cancel_path: str = Field(default="/pricing?checkout=cancelled", max_length=512)


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> dict[str, object]:
    """Start a subscription checkout for the caller's org.

    Selva holds no Stripe keys — Dhanam is the sole payment surface (RFC 0011
    / monetization north star). We validate the tier, resolve the caller's
    Dhanam space, and ask Dhanam to create the hosted checkout; the resulting
    ``subscription.created`` webhook flows back through the Dhanam webhook
    handler. Returns ``{"url": ...}`` for the browser to redirect to.

    When ``DHANAM_API_URL`` is unset this returns HTTP 501 with a clear
    ``status: "not_configured"`` body rather than a 500. Any error from Dhanam
    itself is a 502 — including a 404, which says the request we built was
    wrong, not that the feature is missing.
    """
    from ..billing_tiers import is_valid_subscription_tier
    from ..services.billing_sync import resolve_tenant_by_org_id

    if not is_valid_subscription_tier(body.tier):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown subscription tier: {body.tier}",
        )

    settings = get_settings()
    if not settings.dhanam_api_url:
        # Dhanam billing API not configured for this environment yet.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "status": "not_configured",
                "message": "Checkout is not yet available — Dhanam billing API is not configured.",
            },
        )

    # Confine return URLs to our own app host — never honor an arbitrary
    # caller-supplied absolute URL as a redirect target.
    app_base = (settings.public_app_url or "https://app.selva.town").rstrip("/")
    success_url = f"{app_base}{_safe_path(body.success_path, '/office?upgraded=1')}"
    cancel_url = f"{app_base}{_safe_path(body.cancel_path, '/pricing?checkout=cancelled')}"

    tenant_config = await resolve_tenant_by_org_id(db, tenant.org_id)
    space_id = tenant_config.dhanam_space_id if tenant_config else None

    from ..billing_client import DhanamClient

    client = DhanamClient(settings.dhanam_api_url, settings.dhanam_webhook_secret)
    try:
        result = await client.create_checkout(
            settings.dhanam_webhook_secret,
            tier=body.tier,
            success_url=success_url,
            cancel_url=cancel_url,
            space_id=space_id,
        )
    except httpx.HTTPStatusError as exc:
        # Every non-2xx is an upstream failure, 404 included. Reporting 404 as
        # 501 "not_configured" told us for months that Dhanam had not shipped
        # checkout, when in fact we were calling a URL of our own that was
        # missing the /v1 segment — a misdiagnosis of our own request that
        # pointed the blame at another team. Log the URL actually dialled so
        # the next malformed path is one grep away; the response stays generic
        # because this route is public and the upstream endpoint is not the
        # browser's business.
        logger.error(
            "Dhanam checkout failed: HTTP %s from %s",
            exc.response.status_code,
            exc.request.url,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Checkout service error",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Dhanam checkout unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Checkout service unavailable",
        ) from exc

    url = result.get("url")
    if not url:
        logger.error("Dhanam checkout returned no url: %s", result)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Checkout service returned no redirect URL",
        )
    return {"url": url, "tier": body.tier}


def _safe_path(path: str, fallback: str) -> str:
    """Accept only same-origin absolute paths (start with a single '/').
    Anything protocol-relative ('//host'), absolute-URL, or non-'/'-leading
    falls back — the return URL must stay on our app host."""
    if path.startswith("/") and not path.startswith("//"):
        return path
    return fallback


@webhook_router.post("/webhooks/dhanam", include_in_schema=False)
async def dhanam_webhook(request: Request) -> dict[str, str]:
    """Receive verified billing events from Dhanam (canonical Stripe/POS router)."""
    settings = get_settings()
    body = await request.body()
    signature = request.headers.get("x-dhanam-signature", "")

    if not settings.dhanam_webhook_secret:
        logger.error(
            "Dhanam billing webhook received but DHANAM_WEBHOOK_SECRET is unset"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dhanam billing webhook not configured",
        )

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

    # Idempotency: skip an event we've already processed (replay / redelivery).
    # Dhanam events carry an id at the top level or under data; fall back to a
    # content hash so an id-less event is still deduplicated by exact payload.
    event_id = str(
        payload.get("id")
        or (payload.get("data") or {}).get("event_id")
        or hashlib.sha256(body).hexdigest()
    )
    if not await _claim_webhook_event(event_id):
        logger.info(
            "Duplicate Dhanam webhook ignored: type=%s event=%s", event_type, event_id
        )
        return {"status": "duplicate", "event_type": str(event_type)}

    logger.info("Received Dhanam billing webhook: %s (event=%s)", event_type, event_id)

    from ..services.billing_sync import handle_dhanam_billing_event

    await handle_dhanam_billing_event(payload)

    return {"status": "ok", "event_type": str(event_type)}
