"""Unit tests for the checkout tier vocabulary service.

The service exists because two hand-maintained tier vocabularies (static
pricing JSON vs Dhanam's catalog) drifted until they were fully disjoint and
no checkout could succeed. These tests pin the reconciliation rules:
catalog-first validation, TTL caching, loud static fallback, and legacy-alias
precedence.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from nexus_api.services import checkout_tiers
from nexus_api.services.checkout_tiers import (
    LEGACY_TIER_ALIASES,
    get_valid_checkout_tiers,
    plan_id_for_tier,
    pricing_slug_for_catalog_tier,
    reset_catalog_cache,
    resolve_checkout_tier,
    tier_for_plan_id,
)

_CATALOG_TIERS = frozenset({"developer", "team", "business"})


@pytest.fixture(autouse=True)
def _fresh_cache() -> Generator[None, None, None]:
    reset_catalog_cache()
    yield
    reset_catalog_cache()


def _fetch_mock(result: frozenset[str] | Exception) -> AsyncMock:
    if isinstance(result, Exception):
        return AsyncMock(side_effect=result)
    return AsyncMock(return_value=result)


@pytest.mark.asyncio
class TestGetValidCheckoutTiers:
    async def test_catalog_success_returns_catalog_slugs(self) -> None:
        mock = _fetch_mock(_CATALOG_TIERS)
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", mock):
            slugs, source = await get_valid_checkout_tiers()
        assert slugs == _CATALOG_TIERS
        assert source == "catalog"

    async def test_catalog_result_is_ttl_cached(self) -> None:
        """A second call inside the TTL must not refetch."""
        mock = _fetch_mock(_CATALOG_TIERS)
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", mock):
            await get_valid_checkout_tiers()
            await get_valid_checkout_tiers()
        assert mock.await_count == 1

    async def test_cache_expires_after_ttl(self) -> None:
        mock = _fetch_mock(_CATALOG_TIERS)
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", mock):
            await get_valid_checkout_tiers()
            # Force the cached entry past its expiry.
            assert checkout_tiers._catalog_cache is not None
            expires_at, slugs = checkout_tiers._catalog_cache
            checkout_tiers._catalog_cache = (expires_at - 10_000.0, slugs)
            await get_valid_checkout_tiers()
        assert mock.await_count == 2

    async def test_fetch_failure_falls_back_to_static_and_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Catalog down → static JSON vocabulary, canonicalized through the
        alias map, with the loud structured marker. Fail-open silently is the
        defect class this repo documents — the log IS the contract."""
        caplog.set_level(logging.WARNING, logger="nexus_api.services.checkout_tiers")
        mock = _fetch_mock(RuntimeError("catalog down"))
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", mock):
            slugs, source = await get_valid_checkout_tiers()
        assert source == "static-fallback"
        # The static JSON declares the legacy slugs; the fallback speaks the
        # canonical vocabulary so both validation paths agree.
        assert slugs == _CATALOG_TIERS
        assert any("checkout_tier_catalog_unavailable" in r.getMessage() for r in caplog.records)

    async def test_failures_are_not_cached(self) -> None:
        """A recovering catalog must be picked up on the very next call."""
        mock = AsyncMock(side_effect=[RuntimeError("down"), _CATALOG_TIERS])
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", mock):
            _slugs, source_1 = await get_valid_checkout_tiers()
            _slugs, source_2 = await get_valid_checkout_tiers()
        assert (source_1, source_2) == ("static-fallback", "catalog")
        assert mock.await_count == 2


@pytest.mark.asyncio
class TestFetchCatalogTierSlugs:
    async def test_unconfigured_dhanam_url_raises(self) -> None:
        # Default test settings (conftest) carry no dhanam_api_url.
        with pytest.raises(RuntimeError):
            await checkout_tiers._fetch_catalog_tier_slugs()

    async def test_empty_or_malformed_tier_list_raises(self) -> None:
        """An empty catalog must NOT validate as 'no tier is purchasable' —
        it falls back instead of bricking checkout on a bad payload."""
        from nexus_api.config import Settings

        settings = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_api_url="https://api.dhan.am",
            _env_file=None,  # type: ignore[call-arg]
        )
        with (
            patch("nexus_api.config.get_settings", return_value=settings),
            patch(
                "nexus_api.billing_client.DhanamClient.get_catalog",
                new=AsyncMock(return_value={"slug": "selva", "tiers": []}),
            ),
        ):
            with pytest.raises(ValueError):
                await checkout_tiers._fetch_catalog_tier_slugs()

    async def test_reads_tier_slug_with_slug_fallback(self) -> None:
        from nexus_api.config import Settings

        settings = Settings(
            database_url="sqlite+aiosqlite://",
            environment="development",
            dev_auth_bypass=True,
            dhanam_api_url="https://api.dhan.am",
            _env_file=None,  # type: ignore[call-arg]
        )
        body = {
            "slug": "selva",
            "tiers": [
                {"tierSlug": "developer"},
                {"slug": "team"},  # older shape: only the mirror key
                {"tierSlug": "  Business "},  # normalized
            ],
        }
        with (
            patch("nexus_api.config.get_settings", return_value=settings),
            patch(
                "nexus_api.billing_client.DhanamClient.get_catalog",
                new=AsyncMock(return_value=body),
            ),
        ):
            slugs = await checkout_tiers._fetch_catalog_tier_slugs()
        assert slugs == _CATALOG_TIERS


@pytest.mark.asyncio
class TestResolveCheckoutTier:
    async def test_catalog_slug_passes_through(self) -> None:
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", _fetch_mock(_CATALOG_TIERS)):
            assert await resolve_checkout_tier("team") == "team"

    async def test_legacy_slug_is_aliased_with_deprecation_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="nexus_api.services.checkout_tiers")
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", _fetch_mock(_CATALOG_TIERS)):
            for legacy, canonical in LEGACY_TIER_ALIASES.items():
                assert await resolve_checkout_tier(legacy) == canonical
        assert any("checkout_tier_legacy_alias" in r.getMessage() for r in caplog.records)

    async def test_exact_catalog_match_beats_aliasing(self) -> None:
        """If Dhanam ever (re)introduces a slug that is also a legacy alias
        key, the catalog meaning wins — the alias map must not rewrite a slug
        the catalog itself sells."""
        catalog = frozenset({"starter", "developer", "team", "business"})
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", _fetch_mock(catalog)):
            assert await resolve_checkout_tier("starter") == "starter"

    async def test_unknown_slug_returns_none(self) -> None:
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", _fetch_mock(_CATALOG_TIERS)):
            assert await resolve_checkout_tier("platinum-unicorn") is None

    async def test_input_is_normalized(self) -> None:
        with patch.object(checkout_tiers, "_fetch_catalog_tier_slugs", _fetch_mock(_CATALOG_TIERS)):
            assert await resolve_checkout_tier("  Team ") == "team"
            assert await resolve_checkout_tier("PROFESSIONAL") == "team"


class TestPlanId:
    def test_plan_id_is_product_qualified(self) -> None:
        """Dhanam parses ``{product}_{tier}``; an unprefixed tier slug is
        attributed to the wrong product upstream."""
        assert plan_id_for_tier("team") == "selva_team"
        assert plan_id_for_tier("developer") == "selva_developer"


class TestPlanIdInverse:
    """Reader-side half of the plan-id contract (Dhanam webhook envelopes
    echo the plan id verbatim in ``data.plan_id``)."""

    def test_round_trips_plan_id_for_tier(self) -> None:
        for tier in ("team", "developer", "business"):
            assert tier_for_plan_id(plan_id_for_tier(tier)) == tier

    def test_strips_selva_prefix(self) -> None:
        assert tier_for_plan_id("selva_team") == "team"
        assert tier_for_plan_id("  SELVA_Business ") == "business"

    def test_foreign_plans_return_none(self) -> None:
        assert tier_for_plan_id("janua_pro") is None
        assert tier_for_plan_id("essentials") is None
        # Bare product slug carries no tier segment.
        assert tier_for_plan_id("selva") is None
        assert tier_for_plan_id("selva_") is None

    def test_pricing_slug_mapping_inverts_legacy_aliases(self) -> None:
        for pricing_slug, catalog_slug in LEGACY_TIER_ALIASES.items():
            assert pricing_slug_for_catalog_tier(catalog_slug) == pricing_slug

    def test_pricing_slug_passthrough_for_canonical_and_unknown(self) -> None:
        assert pricing_slug_for_catalog_tier("professional") == "professional"
        assert pricing_slug_for_catalog_tier("scale") == "scale"
        assert pricing_slug_for_catalog_tier("  Team ") == "professional"
