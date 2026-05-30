"""Tests for billing integration: internal endpoints, budget checks, Dhanam webhook tier."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest


class TestBillingRecord:
    """POST /api/v1/billing/record writes a ledger entry."""

    @pytest.mark.asyncio
    async def test_records_usage(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={
                "action": "inference",
                "amount": 150,
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "org_id": "test-org",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "recorded"

    @pytest.mark.asyncio
    async def test_rejects_zero_amount(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={"action": "inference", "amount": 0, "org_id": "test-org"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_records_with_agent_and_task_ids(self, client: httpx.AsyncClient) -> None:
        import uuid

        agent_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/v1/billing/record",
            json={
                "action": "inference",
                "amount": 50,
                "agent_id": agent_id,
                "task_id": task_id,
                "org_id": "dev",
            },
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_records_with_provider_and_model(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/record",
            json={
                "action": "inference",
                "amount": 100,
                "provider": "openai",
                "model": "gpt-4o",
                "org_id": "dev",
            },
        )
        assert resp.status_code == 201


class TestCheckBudget:
    """POST /api/v1/billing/check-budget returns budget status."""

    @pytest.mark.asyncio
    async def test_returns_budget_when_under_limit(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={"org_id": "dev"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["over_budget"] is False
        assert data["remaining"] > 0
        assert "daily_limit" in data

    @pytest.mark.asyncio
    async def test_shows_over_budget_after_heavy_usage(self, client: httpx.AsyncClient) -> None:
        # Record enough usage to exceed the default 1000 limit
        for _ in range(11):
            await client.post(
                "/api/v1/billing/record",
                json={"action": "inference", "amount": 100, "org_id": "budget-test"},
            )

        resp = await client.post(
            "/api/v1/billing/check-budget",
            json={"org_id": "budget-test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["over_budget"] is True
        assert data["remaining"] == 0


class TestDispatchBudgetCheck:
    """Dispatch rejects with 402 when over budget."""

    @pytest.mark.asyncio
    async def test_dispatch_rejected_when_over_budget(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Fill up the budget for "dev-org" (the org_id from dev auth bypass)
        for _ in range(101):
            await client.post(
                "/api/v1/billing/record",
                json={"action": "inference", "amount": 10, "org_id": "dev-org"},
            )

        resp = await client.post(
            "/api/v1/swarms/dispatch",
            json={"description": "Over budget task", "graph_type": "research"},
            headers=auth_headers,
        )
        assert resp.status_code == 402


class TestDhanamWebhookTier:
    """Dhanam webhook (canonical billing router) updates cached tier limits."""

    @pytest.mark.asyncio
    async def test_returns_503_when_secret_unset(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        import json

        from nexus_api.config import Settings

        payload = {
            "type": "subscription.updated",
            "data": {"tier": "professional", "org_id": "acme-corp"},
        }
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
                headers={**auth_headers, "Content-Type": "application/json"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_subscription_updated_caches_tier(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        import hashlib
        import hmac
        import json

        from nexus_api.config import Settings

        secret = "test-dhanam-billing-secret"
        payload = {
            "type": "subscription.updated",
            "data": {"tier": "professional", "org_id": "acme-corp"},
        }
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        mock_cache = AsyncMock()
        patched = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_webhook_secret=secret,
            _env_file=None,  # type: ignore[call-arg]
        )

        with (
            patch("nexus_api.routers.billing.get_settings", return_value=patched),
            patch(
                "nexus_api.services.billing_sync.handle_dhanam_billing_event",
                new=AsyncMock(side_effect=mock_cache),
            ),
        ):
            resp = await client.post(
                "/api/v1/billing/webhooks/dhanam",
                content=body,
                headers={
                    **auth_headers,
                    "Content-Type": "application/json",
                    "x-dhanam-signature": signature,
                },
            )

        assert resp.status_code == 200
        mock_cache.assert_awaited_once()
