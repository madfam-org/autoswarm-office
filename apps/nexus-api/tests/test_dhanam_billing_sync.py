"""Tests for Dhanam-first billing sync (canonical Stripe/POS router)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from nexus_api.models import TenantConfig
from nexus_api.services.billing_sync import handle_dhanam_billing_event


@pytest.mark.asyncio
async def test_dhanam_subscription_updated_updates_tenant(db_session) -> None:
    db_session.add(
        TenantConfig(
            org_id="org-dhanam-1",
            brand_name="Test",
            subscription_tier="starter",
            subscription_status="active",
        )
    )
    await db_session.commit()

    payload = {
        "type": "subscription.updated",
        "data": {
            "org_id": "org-dhanam-1",
            "tier": "professional",
            "status": "active",
            "dhanam_space_id": "space-abc",
            "external_customer_id": "cus_dhanam_1",
        },
    }

    with patch(
        "nexus_api.services.billing_sync.cache_tier_limit",
        new=AsyncMock(),
    ) as mock_cache:
        await handle_dhanam_billing_event(payload)

    result = await db_session.execute(
        select(TenantConfig).where(TenantConfig.org_id == "org-dhanam-1")
    )
    tenant = result.scalar_one()
    assert tenant.subscription_tier == "professional"
    assert tenant.stripe_customer_id == "cus_dhanam_1"
    assert tenant.dhanam_space_id == "space-abc"
    mock_cache.assert_awaited_once_with("org-dhanam-1", "professional")


@pytest.mark.asyncio
async def test_dhanam_webhook_requires_secret(client) -> None:
    from nexus_api.config import Settings

    payload = {"type": "subscription.updated", "data": {"org_id": "x", "tier": "starter"}}
    body = json.dumps(payload).encode()
    patched = Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_webhook_secret="",
        _env_file=None,  # type: ignore[call-arg]
    )
    with patch("nexus_api.routers.billing.get_settings", return_value=patched):
        resp = await client.post(
            "/api/v1/billing/webhooks/dhanam",
            content=body,
            headers={"Content-Type": "application/json", "x-dhanam-signature": "bad"},
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_dhanam_webhook_rejects_bad_signature(client) -> None:
    from nexus_api.config import Settings

    secret = "test-dhanam-secret"
    payload = {"type": "subscription.updated", "data": {"org_id": "x", "tier": "starter"}}
    body = json.dumps(payload).encode()
    patched = Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_webhook_secret=secret,
        _env_file=None,  # type: ignore[call-arg]
    )
    with patch("nexus_api.routers.billing.get_settings", return_value=patched):
        resp = await client.post(
            "/api/v1/billing/webhooks/dhanam",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-dhanam-signature": "deadbeef",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_webhook_blocked_when_billing_via_dhanam(client) -> None:
    with patch(
        "nexus_api.routers.stripe_webhooks.get_settings",
        return_value=type(
            "S",
            (),
            {
                "billing_via_dhanam": True,
                "stripe_webhook_secret": "whsec_test",
            },
        )(),
    ):
        resp = await client.post(
            "/api/v1/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=x"},
        )
    assert resp.status_code == 503
