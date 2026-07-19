"""Tests for the subscription checkout + tiers endpoints (M1 First-Peso).

Selva holds no Stripe keys — it asks Dhanam to create the hosted checkout.
Until Dhanam's checkout API is live these must degrade to a clear 501
`not_configured`, never a 500, so the frontend can show a truthful message
and the contract flips on the moment Dhanam ships.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nexus_api.config import Settings


def _settings_with_dhanam(url: str = "https://api.dhan.am") -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_api_url=url,
        dhanam_webhook_secret="test-secret",
        public_app_url="https://app.selva.town",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.mark.asyncio
class TestListTiers:
    async def test_returns_purchasable_tiers(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/billing/tiers", headers=auth_headers)
        assert resp.status_code == 200
        tiers = resp.json()["tiers"]
        slugs = {t["slug"] for t in tiers}
        # From infra/pricing/selva-tiers.json (dhanam_subscription_daily_limits).
        assert {"starter", "professional", "enterprise"} <= slugs
        for t in tiers:
            assert "daily_token_limit" in t and "name" in t


@pytest.mark.asyncio
class TestCheckout:
    async def test_unknown_tier_rejected(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/billing/checkout",
            json={"tier": "platinum-unicorn"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_not_configured_when_dhanam_url_unset(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Default test settings have no dhanam_api_url → 501 not_configured,
        never a 500."""
        resp = await client.post(
            "/api/v1/billing/checkout",
            json={"tier": "professional"},
            headers=auth_headers,
        )
        assert resp.status_code == 501
        assert resp.json()["detail"]["status"] == "not_configured"

    async def test_dhanam_404_degrades_to_not_configured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Dhanam reachable but checkout endpoint not shipped yet (404) →
        501 not_configured, not a 502."""
        request = httpx.Request("POST", "https://api.dhan.am/billing/checkout")
        response = httpx.Response(404, request=request)
        http_404 = httpx.HTTPStatusError("404", request=request, response=response)
        with (
            patch(
                "nexus_api.routers.billing.get_settings",
                return_value=_settings_with_dhanam(),
            ),
            patch(
                "nexus_api.billing_client.DhanamClient.create_checkout",
                new=AsyncMock(side_effect=http_404),
            ),
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 501
        assert resp.json()["detail"]["status"] == "not_configured"

    async def test_happy_path_returns_hosted_url(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch(
                "nexus_api.billing_client.DhanamClient.create_checkout",
                new=AsyncMock(return_value={"url": "https://checkout.dhan.am/sess_123"}),
            ) as mock_checkout,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://checkout.dhan.am/sess_123"
        # Return URLs were confined to the app host.
        kwargs = mock_checkout.await_args.kwargs
        assert kwargs["success_url"].startswith("https://app.selva.town/")
        assert kwargs["tier"] == "professional"

    async def test_open_redirect_path_is_sanitized(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A caller-supplied absolute/protocol-relative return path must not
        become the redirect target — it falls back to the safe default."""
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch(
                "nexus_api.billing_client.DhanamClient.create_checkout",
                new=AsyncMock(return_value={"url": "https://checkout.dhan.am/sess_1"}),
            ) as mock_checkout,
        ):
            await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "starter", "success_path": "//evil.example/phish"},
                headers=auth_headers,
            )
        success_url = mock_checkout.await_args.kwargs["success_url"]
        assert success_url == "https://app.selva.town/office?upgraded=1"
