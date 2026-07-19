"""Tests for Phase 1.2 org daily limit resolution and subscription gates."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from nexus_api.billing_tiers import get_daily_limit
from nexus_api.models import TenantConfig
from nexus_api.services.tier_limits import (
    assert_subscription_allows_dispatch,
    resolve_org_daily_limit,
    subscription_blocks_dispatch,
)


@pytest.mark.asyncio
async def test_resolve_uses_db_tier_when_redis_empty(db_session) -> None:
    db_session.add(
        TenantConfig(
            org_id="tier-org-pro",
            brand_name="Pro Co",
            subscription_tier="professional",
            subscription_status="active",
        )
    )
    await db_session.commit()

    with patch(
        "nexus_api.services.tier_limits.get_redis_pool",
        side_effect=ConnectionError("redis down"),
    ):
        limit = await resolve_org_daily_limit(db_session, "tier-org-pro")

    assert limit == get_daily_limit("professional")


@pytest.mark.asyncio
async def test_resolve_prefers_redis_over_db_tier(db_session) -> None:
    db_session.add(
        TenantConfig(
            org_id="tier-org-cache",
            brand_name="Cached",
            subscription_tier="starter",
            subscription_status="active",
        )
    )
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.execute_with_retry = AsyncMock(return_value=b"25000")

    with patch(
        "nexus_api.services.tier_limits.get_redis_pool",
        return_value=mock_pool,
    ):
        limit = await resolve_org_daily_limit(db_session, "tier-org-cache")

    assert limit == 25000


def test_subscription_blocks_past_due() -> None:
    tenant = TenantConfig(org_id="x", brand_name="x", subscription_status="past_due")
    assert subscription_blocks_dispatch(tenant) == "past_due"


def test_assert_subscription_allows_active() -> None:
    tenant = TenantConfig(org_id="x", brand_name="x", subscription_status="active")
    assert_subscription_allows_dispatch(tenant)


@pytest.mark.asyncio
async def test_dispatch_rejected_when_past_due(client, auth_headers, db_session) -> None:
    db_session.add(
        TenantConfig(
            org_id="dev-org",
            brand_name="Dev",
            subscription_status="past_due",
            subscription_tier="professional",
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/swarms/dispatch",
        json={"description": "Should block on billing", "graph_type": "research"},
        headers=auth_headers,
    )
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    # Structured 402 so the office-ui upgrade modal can key on the code.
    assert detail["code"] == "budget_exhausted"
    assert "past_due" in detail["message"]


@pytest.mark.asyncio
async def test_dispatch_uses_professional_tier_without_redis(
    client, auth_headers, db_session
) -> None:
    db_session.add(
        TenantConfig(
            org_id="dev-org",
            brand_name="Dev",
            subscription_status="active",
            subscription_tier="professional",
        )
    )
    await db_session.commit()

    # Starter default would block at 101×10; professional allows 5000.
    for _ in range(101):
        await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 10, "org_id": "dev-org"},
        )

    resp = await client.post(
        "/api/v1/swarms/dispatch",
        json={"description": "Within professional budget", "graph_type": "research"},
        headers=auth_headers,
    )
    assert resp.status_code in {200, 201, 202}

    result = await db_session.execute(
        select(TenantConfig).where(TenantConfig.org_id == "dev-org")
    )
    assert result.scalar_one().subscription_tier == "professional"
