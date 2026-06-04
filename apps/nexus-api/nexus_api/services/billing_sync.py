"""Canonical subscription sync for Selva tenants (Dhanam-first billing router)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..billing_tiers import DEFAULT_TIER, get_daily_limit
from ..config import get_settings
from ..database import tenant_session
from ..models import TenantConfig

logger = logging.getLogger(__name__)


async def cache_tier_limit(org_id: str, tier: str) -> None:
    """Mirror tier daily limit into Redis for dispatch budget checks."""
    daily_limit = get_daily_limit(tier)
    try:
        from selva_redis_pool import get_redis_pool

        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        await pool.execute_with_retry(
            "set", f"selva:tier:{org_id}", str(daily_limit), ex=86400
        )
    except Exception:
        logger.warning(
            "Failed to cache tier limit for org=%s tier=%s in Redis",
            org_id,
            tier,
            exc_info=True,
        )


async def clear_overage_counter(org_id: str) -> None:
    """Clear daily overage counter after successful invoice payment."""
    try:
        from selva_redis_pool import get_redis_pool

        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        await pool.execute_with_retry("delete", f"selva:tier_overage:{org_id}")
    except Exception:
        logger.warning(
            "Failed to clear tier_overage Redis key for org=%s",
            org_id,
            exc_info=True,
        )


def _parse_period_end(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _normalize_tier(raw: Any) -> str:
    tier = str(raw or DEFAULT_TIER).strip().lower()
    return tier or DEFAULT_TIER


async def resolve_tenant_by_org_id(db: AsyncSession, org_id: str) -> TenantConfig | None:
    if not org_id:
        return None
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    return result.scalar_one_or_none()


async def apply_subscription_state(
    db: AsyncSession,
    *,
    org_id: str,
    tier: str,
    status: str,
    current_period_end: datetime | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    dhanam_space_id: str | None = None,
) -> TenantConfig | None:
    """Update tenant_configs from a Dhanam-normalized subscription event."""
    tenant = await resolve_tenant_by_org_id(db, org_id)
    if tenant is None:
        return None

    tenant.subscription_tier = _normalize_tier(tier)
    tenant.subscription_status = status
    if current_period_end is not None:
        tenant.subscription_current_period_end = current_period_end
    if stripe_customer_id:
        tenant.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        tenant.stripe_subscription_id = stripe_subscription_id
    if dhanam_space_id:
        tenant.dhanam_space_id = dhanam_space_id

    await db.commit()
    await cache_tier_limit(org_id, tenant.subscription_tier)
    return tenant


async def mark_subscription_cancelled(
    db: AsyncSession,
    *,
    org_id: str,
    current_period_end: datetime | None = None,
) -> TenantConfig | None:
    tenant = await resolve_tenant_by_org_id(db, org_id)
    if tenant is None:
        return None
    tenant.subscription_status = "cancelled"
    if current_period_end is not None:
        tenant.subscription_current_period_end = current_period_end
    await db.commit()
    return tenant


async def emit_billing_task_event(
    db: AsyncSession,
    *,
    org_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    from ..routers.events import emit_event_db

    await emit_event_db(
        db,
        event_type=event_type,
        event_category="billing",
        org_id=org_id,
        payload=payload,
    )
    await db.commit()


async def handle_dhanam_billing_event(payload: dict[str, Any]) -> None:
    """Process a signed Dhanam billing webhook (canonical POS/Stripe router)."""
    event_type = str(payload.get("type") or "unknown")
    data = payload.get("data") or {}
    org_id = str(data.get("org_id") or "")
    if not org_id:
        logger.info("Dhanam billing event missing org_id; type=%s", event_type)
        return

    tier = _normalize_tier(data.get("tier"))
    status = str(data.get("status") or "active")
    period_end = _parse_period_end(data.get("current_period_end"))
    stripe_customer_id = data.get("external_customer_id") or data.get("stripe_customer_id")
    stripe_subscription_id = data.get("external_subscription_id") or data.get(
        "stripe_subscription_id"
    )
    dhanam_space_id = data.get("dhanam_space_id")

    async with tenant_session(org_id=org_id) as db:
        if event_type in {"subscription.created", "subscription.updated"}:
            tenant = await apply_subscription_state(
                db,
                org_id=org_id,
                tier=tier,
                status=status,
                current_period_end=period_end,
                stripe_customer_id=str(stripe_customer_id) if stripe_customer_id else None,
                stripe_subscription_id=str(stripe_subscription_id)
                if stripe_subscription_id
                else None,
                dhanam_space_id=str(dhanam_space_id) if dhanam_space_id else None,
            )
            if tenant is None:
                logger.info(
                    "Dhanam %s for unknown org=%s; skipping",
                    event_type,
                    org_id,
                )
                return
            logger.info(
                "Dhanam %s processed: org=%s tier=%s status=%s",
                event_type,
                org_id,
                tier,
                status,
            )
            return

        if event_type in {"subscription.cancelled", "subscription.deleted"}:
            tenant = await mark_subscription_cancelled(
                db, org_id=org_id, current_period_end=period_end
            )
            if tenant is None:
                logger.info("Dhanam %s for unknown org=%s; skipping", event_type, org_id)
                return
            logger.info("Dhanam %s processed: org=%s", event_type, org_id)
            return

        if event_type == "invoice.paid":
            tenant = await resolve_tenant_by_org_id(db, org_id)
            if tenant is None:
                logger.info("Dhanam invoice.paid for unknown org=%s; skipping", org_id)
                return
            if tenant.subscription_status == "past_due":
                tenant.subscription_status = "active"
                await db.commit()
            await emit_billing_task_event(
                db,
                org_id=org_id,
                event_type="billing.invoice_paid",
                payload={
                    "invoice_id": data.get("invoice_id"),
                    "amount_paid": data.get("amount_cents"),
                    "currency": data.get("currency"),
                    "payment_provider": data.get("payment_provider", "dhanam"),
                    "dhanam_space_id": dhanam_space_id,
                },
            )
            await clear_overage_counter(org_id)
            logger.info("Dhanam invoice.paid processed: org=%s", org_id)
            return

        if event_type == "invoice.payment_failed":
            tenant = await resolve_tenant_by_org_id(db, org_id)
            if tenant is None:
                logger.info(
                    "Dhanam invoice.payment_failed for unknown org=%s; skipping",
                    org_id,
                )
                return
            tenant.subscription_status = "past_due"
            await db.commit()
            await emit_billing_task_event(
                db,
                org_id=org_id,
                event_type="billing.payment_failed",
                payload={
                    "invoice_id": data.get("invoice_id"),
                    "amount_due": data.get("amount_cents"),
                    "currency": data.get("currency"),
                    "payment_provider": data.get("payment_provider", "dhanam"),
                    "next_payment_attempt": data.get("next_payment_attempt"),
                },
            )
            logger.warning("Dhanam invoice.payment_failed processed: org=%s", org_id)
            return

    logger.info("Dhanam billing event acknowledged without handler: type=%s", event_type)
