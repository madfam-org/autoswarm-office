"""Tests for the providers balance probe route.

Covers:
- 200 with cached payload — happy path
- 200 with degraded 'unknown' entries when cache is empty
- 200 with degraded 'unknown' entries when Redis is unreachable (never 5xx)
- alert classification thresholds (ok / low / critical / unknown)
- Auth: non-admin gets 403
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus_api.routers.providers import (
    KNOWN_PROVIDERS,
    REDIS_BALANCE_KEY,
    classify_alert,
)


class TestClassifyAlert:
    def test_critical_at_zero(self) -> None:
        assert classify_alert(0.0, "api") == "critical"

    def test_critical_below_threshold(self) -> None:
        assert classify_alert(4.99, "api") == "critical"

    def test_critical_at_exact_threshold(self) -> None:
        # $5 is the boundary — included in critical (<=)
        assert classify_alert(5.0, "api") == "critical"

    def test_low_just_above_critical(self) -> None:
        assert classify_alert(5.01, "api") == "low"

    def test_low_at_50(self) -> None:
        assert classify_alert(50.0, "api") == "low"

    def test_ok_above_50(self) -> None:
        assert classify_alert(50.01, "api") == "ok"
        assert classify_alert(1000.0, "estimated") == "ok"

    def test_unknown_source_is_critical(self) -> None:
        """A balance reading with source='unknown' is treated as critical
        regardless of the numeric value (it's noise — alert on absence
        of signal, not on whatever the default placeholder happens to be)."""
        assert classify_alert(100.0, "unknown") == "critical"

    def test_negative_balance_is_critical(self) -> None:
        """The route uses balance=-1.0 as a sentinel for 'no signal'."""
        assert classify_alert(-1.0, "api") == "critical"


@pytest.mark.asyncio
class TestGetProviderBalances:
    async def test_happy_path_returns_cached_balances(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        cached = {
            "anthropic": {
                "balance_usd": 250.0,
                "currency": "USD",
                "source": "estimated",
                "updated_at": "2026-05-04T12:00:00+00:00",
            },
            "openai": {
                "balance_usd": 12.5,
                "currency": "USD",
                "source": "api",
                "updated_at": "2026-05-04T12:00:00+00:00",
            },
            "deepinfra": {
                "balance_usd": 4.99,  # critical
                "currency": "USD",
                "source": "api",
                "updated_at": "2026-05-04T12:00:00+00:00",
            },
        }
        mock_pool = MagicMock()
        mock_pool.get = AsyncMock(return_value=json.dumps(cached))

        with patch("nexus_api.routers.providers.get_redis_pool", return_value=mock_pool):
            resp = await client.get("/api/v1/providers/balance", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == set(KNOWN_PROVIDERS)
        assert data["anthropic"]["balance_usd"] == 250.0
        assert data["anthropic"]["alert"] == "ok"
        assert data["openai"]["alert"] == "low"
        assert data["deepinfra"]["alert"] == "critical"
        # Redis was queried with the canonical key
        mock_pool.get.assert_awaited_once_with(REDIS_BALANCE_KEY)

    async def test_empty_cache_returns_unknown_per_provider(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """No cache entry → every provider reports source='unknown' +
        alert='critical' (never 5xx — surface the missing signal)."""
        mock_pool = MagicMock()
        mock_pool.get = AsyncMock(return_value=None)

        with patch("nexus_api.routers.providers.get_redis_pool", return_value=mock_pool):
            resp = await client.get("/api/v1/providers/balance", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == set(KNOWN_PROVIDERS)
        for provider, entry in data.items():
            assert entry["source"] == "unknown", f"{provider} should be unknown"
            assert entry["alert"] == "critical", f"{provider} should be critical"
            assert entry["balance_usd"] == -1.0

    async def test_redis_unreachable_degrades_gracefully(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Redis pool raises → route returns 200 with unknown entries.
        Surfacing the absent signal beats hiding it behind a 5xx."""
        mock_pool = MagicMock()
        mock_pool.get = AsyncMock(side_effect=ConnectionError("redis down"))

        with patch("nexus_api.routers.providers.get_redis_pool", return_value=mock_pool):
            resp = await client.get("/api/v1/providers/balance", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        for entry in data.values():
            assert entry["source"] == "unknown"
            assert entry["alert"] == "critical"

    async def test_partial_cache_fills_missing_providers_with_unknown(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Only Anthropic in cache → openai + deepinfra still appear with
        source='unknown'. Operator sees the partial signal."""
        cached: dict[str, Any] = {
            "anthropic": {
                "balance_usd": 100.0,
                "currency": "USD",
                "source": "estimated",
                "updated_at": "2026-05-04T12:00:00+00:00",
            }
        }
        mock_pool = MagicMock()
        mock_pool.get = AsyncMock(return_value=json.dumps(cached))

        with patch("nexus_api.routers.providers.get_redis_pool", return_value=mock_pool):
            resp = await client.get("/api/v1/providers/balance", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["anthropic"]["alert"] == "ok"
        assert data["openai"]["source"] == "unknown"
        assert data["deepinfra"]["source"] == "unknown"


@pytest.mark.asyncio
class TestProviderBalanceAuth:
    async def test_non_admin_role_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """Without admin/platform role, the endpoint returns 403."""
        # Override get_current_user to return a viewer-only user.
        from nexus_api.auth import get_current_user
        from nexus_api.main import app

        async def _viewer_only() -> dict[str, Any]:
            return {
                "sub": "u-1",
                "roles": ["viewer"],
                "org_id": "test-org",
                "email": "u@example.com",
            }

        app.dependency_overrides[get_current_user] = _viewer_only
        try:
            mock_pool = MagicMock()
            mock_pool.get = AsyncMock(return_value=None)
            with patch("nexus_api.routers.providers.get_redis_pool", return_value=mock_pool):
                resp = await client.get(
                    "/api/v1/providers/balance",
                    headers={"Authorization": "Bearer x"},
                )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)
