"""Resolve org daily compute token limits (Phase 1.2 — Dhanam tier enforcement)."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..billing_tiers import get_daily_limit
from ..config import get_settings
from ..models import TenantConfig

logger = logging.getLogger(__name__)

_BLOCKED_SUBSCRIPTION_STATUSES = frozenset(
    {"past_due", "cancelled", "unpaid", "incomplete_expired"}
)


def subscription_blocks_dispatch(tenant_config: TenantConfig | None) -> str | None:
    """Return blocking status slug when dispatch must be refused, else None."""
    if tenant_config is None or not tenant_config.subscription_status:
        return None
    status_slug = tenant_config.subscription_status.strip().lower()
    if status_slug in _BLOCKED_SUBSCRIPTION_STATUSES:
        return status_slug
    return None


#: Stable machine-readable code carried in every dispatch-budget 402 so the
#: frontend can render a one-click upgrade modal instead of string-matching a
#: human message. See ``useTaskDispatch`` on the office-ui side.
BUDGET_EXHAUSTED_CODE = "budget_exhausted"


def budget_exhausted_detail(message: str) -> dict[str, str]:
    """Structured 402 detail: a stable ``code`` plus a human ``message``."""
    return {"code": BUDGET_EXHAUSTED_CODE, "message": message}


def assert_subscription_allows_dispatch(tenant_config: TenantConfig | None) -> None:
    """Raise 402 when subscription status forbids new compute spend."""
    blocked = subscription_blocks_dispatch(tenant_config)
    if blocked is not None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=budget_exhausted_detail(
                f"Subscription {blocked}; renew billing before dispatching tasks."
            ),
        )


async def resolve_org_daily_limit(
    db: AsyncSession,
    org_id: str,
    *,
    tenant_config: TenantConfig | None = None,
) -> int:
    """Return the daily compute token budget for *org_id*.

    Priority:
    1. Redis ``selva:tier:{org_id}`` (written by Dhanam billing webhooks)
    2. ``tenant_configs.subscription_tier`` (Dhanam sync / provisioning)
    3. Default starter tier from ``infra/pricing/selva-tiers.json``
    """
    tier: str | None = None
    if tenant_config is None:
        result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
        tenant_config = result.scalar_one_or_none()
    if tenant_config is not None:
        tier = tenant_config.subscription_tier

    try:
        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        cached = await pool.execute_with_retry("get", f"selva:tier:{org_id}")
        if cached:
            if isinstance(cached, bytes):
                cached = cached.decode()
            return int(str(cached))
    except Exception:
        logger.debug(
            "Failed to fetch cached tier limit for org=%s; falling back to DB tier",
            org_id,
            exc_info=True,
        )

    return get_daily_limit(tier)
