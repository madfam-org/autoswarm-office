"""Tests for the subscription checkout + tiers endpoints (M1 First-Peso).

Selva holds no Stripe keys — it asks Dhanam to create the hosted checkout via
the customer-federation flow (resolve the billing customer, then create the
checkout against the returned ``externalId``). With ``DHANAM_API_URL`` unset
the route must degrade to a clear 501 ``not_configured``, never a 500; with
``FEDERATION_API_TOKEN`` unset it must fail closed with 503.

These patch the ``DhanamClient`` federation methods to exercise route
semantics (tier reconciliation, return-URL confinement, fail-closed paths).
What Dhanam is actually *called with* — URL, method, payload, auth header —
is covered in ``test_dhanam_url_construction.py`` against a real client;
patching the client method here is why a malformed URL went unnoticed for
months.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nexus_api.config import Settings
from nexus_api.services.checkout_tiers import reset_catalog_cache

_FEDERATION_TOKEN = "fed-token-123"
_CATALOG_TIERS = frozenset({"developer", "team", "business"})


def _settings_with_dhanam(
    url: str = "https://api.dhan.am", federation_api_token: str = _FEDERATION_TOKEN
) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        dev_auth_bypass=True,
        dhanam_api_url=url,
        dhanam_webhook_secret="test-secret",
        federation_api_token=federation_api_token,
        public_app_url="https://app.selva.town",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(autouse=True)
def _fresh_tier_cache() -> Generator[None, None, None]:
    """The checkout-tier catalog cache is module-global; isolate every test."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()


def _catalog(tiers: frozenset[str] = _CATALOG_TIERS):
    """Patch the catalog fetch to a fixed live tier set (no network)."""
    return patch(
        "nexus_api.services.checkout_tiers._fetch_catalog_tier_slugs",
        new=AsyncMock(return_value=tiers),
    )


def _federation_mocks():
    """Patch both federation client methods for route-semantics tests."""
    resolve = patch(
        "nexus_api.billing_client.DhanamClient.resolve_federation_customer",
        new=AsyncMock(return_value={"externalId": "user_123", "created": False}),
    )
    checkout = patch(
        "nexus_api.billing_client.DhanamClient.create_federation_checkout",
        new=AsyncMock(
            return_value={"checkoutUrl": "https://checkout.dhan.am/sess_123", "sessionId": "cs_1"}
        ),
    )
    return resolve, checkout


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
        with _catalog():
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
        never a 500. (Tier validation runs on the static fallback here — the
        catalog is unreachable by definition.)"""
        resp = await client.post(
            "/api/v1/billing/checkout",
            json={"tier": "professional"},
            headers=auth_headers,
        )
        assert resp.status_code == 501
        assert resp.json()["detail"]["status"] == "not_configured"

    async def test_unset_federation_token_fails_closed_with_503(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """FEDERATION_API_TOKEN unset → 503 + a structured operator log. The
        webhook secret must NOT be substituted (that was the defect), and no
        secret material may reach the caller or the log."""
        caplog.set_level(logging.ERROR, logger="nexus_api.routers.billing")
        resolve_p, checkout_p = _federation_mocks()
        with (
            patch(
                "nexus_api.routers.billing.get_settings",
                return_value=_settings_with_dhanam(federation_api_token=""),
            ),
            _catalog(),
            resolve_p as mock_resolve,
            checkout_p as mock_checkout,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 503
        assert resp.json()["detail"]["status"] == "not_configured"
        # Fail-closed means no upstream call was attempted at all.
        mock_resolve.assert_not_awaited()
        mock_checkout.assert_not_awaited()
        assert any(
            "checkout_federation_token_missing" in r.getMessage() for r in caplog.records
        ), "the unset token must produce a structured operator log"
        # Nothing secret-shaped leaks to the caller.
        assert "test-secret" not in resp.text

    async def test_happy_path_returns_hosted_url(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resolve_p, checkout_p = _federation_mocks()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _catalog(),
            resolve_p as mock_resolve,
            checkout_p as mock_checkout,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "team"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://checkout.dhan.am/sess_123"
        assert resp.json()["tier"] == "team"

        # The caller's own identity drives the resolve step, authenticated
        # with the federation token — never the webhook secret.
        assert mock_resolve.await_args.args == (_FEDERATION_TOKEN,)
        resolve_kwargs = mock_resolve.await_args.kwargs
        assert resolve_kwargs["email"] == "dev@selva.local"
        assert resolve_kwargs["janua_sub"] == "dev-user-00000000"

        kwargs = mock_checkout.await_args.kwargs
        assert mock_checkout.await_args.args == (_FEDERATION_TOKEN,)
        assert kwargs["external_id"] == "user_123"
        # Fully-qualified catalog plan id — an unprefixed slug resolves
        # against the wrong product upstream.
        assert kwargs["plan_id"] == "selva_team"
        # Return URLs were confined to the app host.
        assert kwargs["success_url"].startswith("https://app.selva.town/")
        # The purchase is attributed to the caller's org via metadata.
        assert kwargs["metadata"]["orgId"] == "dev-org"

    async def test_legacy_tier_slug_maps_to_catalog_tier(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The pricing page still emits the legacy vocabulary; ``professional``
        must reach Dhanam as ``selva_team``, with a deprecation log."""
        caplog.set_level(logging.WARNING, logger="nexus_api.services.checkout_tiers")
        resolve_p, checkout_p = _federation_mocks()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _catalog(),
            resolve_p,
            checkout_p as mock_checkout,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "professional"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["tier"] == "team"
        assert mock_checkout.await_args.kwargs["plan_id"] == "selva_team"
        assert any("checkout_tier_legacy_alias" in r.getMessage() for r in caplog.records)

    async def test_disjoint_slug_regression_both_vocabularies_checkout(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """THE regression this change closes: the static JSON vocabulary
        ({starter, professional, enterprise}) and the catalog vocabulary
        ({developer, team, business}) are disjoint — previously no slug from
        either set could complete a checkout. Every slug from both sets must
        now resolve to a purchasable catalog plan."""
        expected = {
            "starter": "selva_developer",
            "professional": "selva_team",
            "enterprise": "selva_business",
            "developer": "selva_developer",
            "team": "selva_team",
            "business": "selva_business",
        }
        for requested, plan_id in expected.items():
            resolve_p, checkout_p = _federation_mocks()
            with (
                patch(
                    "nexus_api.routers.billing.get_settings",
                    return_value=_settings_with_dhanam(),
                ),
                _catalog(),
                resolve_p,
                checkout_p as mock_checkout,
            ):
                resp = await client.post(
                    "/api/v1/billing/checkout",
                    json={"tier": requested},
                    headers=auth_headers,
                )
            assert resp.status_code == 200, f"tier {requested!r} failed: {resp.text}"
            assert mock_checkout.await_args.kwargs["plan_id"] == plan_id

    async def test_catalog_down_falls_back_to_static_vocabulary(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Catalog unreachable → the static JSON (canonicalized through the
        alias map) still lets checkout proceed, and the fallback is loud."""
        caplog.set_level(logging.WARNING, logger="nexus_api.services.checkout_tiers")
        resolve_p, checkout_p = _federation_mocks()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            patch(
                "nexus_api.services.checkout_tiers._fetch_catalog_tier_slugs",
                new=AsyncMock(side_effect=httpx.ConnectError("catalog down")),
            ),
            resolve_p,
            checkout_p as mock_checkout,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "business"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert mock_checkout.await_args.kwargs["plan_id"] == "selva_business"
        assert any(
            "checkout_tier_catalog_unavailable" in r.getMessage() for r in caplog.records
        ), "falling back to the static vocabulary must be loud"

    async def test_missing_email_is_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Dhanam resolves the billing customer by email — a token without one
        cannot start a checkout and must fail before any upstream call."""
        from nexus_api.auth import get_current_user
        from nexus_api.main import app

        async def _no_email_user() -> dict[str, object]:
            return {"sub": "legacy-user", "roles": ["admin"], "org_id": "dev-org", "email": None}

        app.dependency_overrides[get_current_user] = _no_email_user
        try:
            resolve_p, checkout_p = _federation_mocks()
            with (
                patch(
                    "nexus_api.routers.billing.get_settings",
                    return_value=_settings_with_dhanam(),
                ),
                _catalog(),
                resolve_p as mock_resolve,
                checkout_p,
            ):
                resp = await client.post(
                    "/api/v1/billing/checkout",
                    json={"tier": "team"},
                    headers=auth_headers,
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert resp.status_code == 400
        mock_resolve.assert_not_awaited()

    async def test_open_redirect_path_is_sanitized(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A caller-supplied absolute/protocol-relative return path must not
        become the redirect target — it falls back to the safe default."""
        resolve_p, checkout_p = _federation_mocks()
        with (
            patch("nexus_api.routers.billing.get_settings", return_value=_settings_with_dhanam()),
            _catalog(),
            resolve_p,
            checkout_p as mock_checkout,
        ):
            await client.post(
                "/api/v1/billing/checkout",
                json={"tier": "developer", "success_path": "//evil.example/phish"},
                headers=auth_headers,
            )
        success_url = mock_checkout.await_args.kwargs["success_url"]
        assert success_url == "https://app.selva.town/office?upgraded=1"
