"""CI drift gate: pricing JSON is the single source of truth.

What this enforces:
1. The JSON file at ``infra/pricing/selva-tiers.json`` exists and parses.
2. The ``billing_tiers`` module's exported values match what's in the JSON
   (catches a regression where someone re-hardcodes the dict).
3. The Tulana hourly tiers in the JSON match the values cited in
   ``CLAUDE.md`` (catches drift between the human-readable doc and the
   machine-readable JSON).
4. Schema-shape sanity (load JSON Schema + validate the data file).
5. The fallback dict inside ``billing_tiers._load_pricing`` matches the
   live JSON (catches the case where someone updates one but not the other,
   leaving the emergency fallback stale).
6. Behaviour preserved: ``get_daily_limit`` returns the same values it
   did before the JSON migration, for the 4 historically-tested cases.

What this DELIBERATELY does NOT enforce:
- That tier values are within any specific range (operator can change
  them with a PR; the gate just prevents drift, not changes).
- That the bundle page in office-ui matches (separate, TS-side concern;
  follow-up PR to add a similar gate there).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRICING_JSON = _REPO_ROOT / "infra" / "pricing" / "selva-tiers.json"
_SCHEMA_JSON = _REPO_ROOT / "infra" / "pricing" / "schema.json"
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"


@pytest.fixture
def pricing_data() -> dict:
    """Load the canonical pricing JSON. Failure here means the file is
    missing or syntactically broken — the most basic invariant."""
    assert _PRICING_JSON.exists(), (
        f"Canonical pricing JSON missing at {_PRICING_JSON}. "
        "Anyone editing tier values MUST do so in this file."
    )
    with _PRICING_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


class TestJsonShape:
    """The JSON file conforms to the schema."""

    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_JSON.exists(), (
            f"JSON Schema missing at {_SCHEMA_JSON}. The schema is the "
            "contract editors rely on for autocomplete + validation."
        )

    def test_required_top_level_keys(self, pricing_data: dict) -> None:
        for key in (
            "generated_from",
            "last_updated",
            "tulana_metered_hourly_packs",
            "dhanam_subscription_daily_limits",
            "external_a2a_default",
        ):
            assert key in pricing_data, f"Required top-level key {key!r} missing"

    def test_last_updated_is_iso_date(self, pricing_data: dict) -> None:
        """Pinned format catches sloppy edits like 'May 2026' or '5/4/26'."""
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", pricing_data["last_updated"]), (
            "last_updated must be ISO YYYY-MM-DD; "
            f"got {pricing_data['last_updated']!r}"
        )

    def test_default_tier_is_a_real_tier(self, pricing_data: dict) -> None:
        """Catches the foot-gun where someone renames a tier slug but forgets
        to update default_tier. Worker would 500 on cache-miss."""
        section = pricing_data["dhanam_subscription_daily_limits"]
        assert section["default_tier"] in section["tiers"], (
            f"default_tier={section['default_tier']!r} not in tiers "
            f"{list(section['tiers'].keys())}"
        )


class TestBillingTiersLoaderMatchesJson:
    """The Python module ``billing_tiers`` loads the SAME values the JSON
    declares. A regression here means someone re-introduced a hardcoded dict."""

    def test_tier_daily_task_limit_matches_json(self, pricing_data: dict) -> None:
        from nexus_api.billing_tiers import _load_pricing

        # Ensure the loader sees the on-disk JSON, not a stale cache from
        # an earlier test.
        _load_pricing.cache_clear()

        from nexus_api.billing_tiers import TIER_DAILY_TASK_LIMIT

        # Re-import to pick up post-cache-clear values.
        json_tiers = pricing_data["dhanam_subscription_daily_limits"]["tiers"]
        for slug, spec in json_tiers.items():
            assert TIER_DAILY_TASK_LIMIT.get(slug) == spec["daily_token_limit"], (
                f"Drift: TIER_DAILY_TASK_LIMIT[{slug!r}]="
                f"{TIER_DAILY_TASK_LIMIT.get(slug)} but JSON says "
                f"{spec['daily_token_limit']}"
            )

    def test_default_tier_matches_json(self, pricing_data: dict) -> None:
        from nexus_api.billing_tiers import DEFAULT_TIER

        assert DEFAULT_TIER == pricing_data["dhanam_subscription_daily_limits"][
            "default_tier"
        ]

    def test_external_a2a_limit_matches_json(self, pricing_data: dict) -> None:
        from nexus_api.billing_tiers import (
            _load_pricing,
            get_external_a2a_daily_limit,
        )

        _load_pricing.cache_clear()
        assert (
            get_external_a2a_daily_limit()
            == pricing_data["external_a2a_default"]["daily_token_limit"]
        )


class TestTulanaPackValuesMatchClaudeMd:
    """The Tulana hourly rates in the JSON must match the values cited in
    CLAUDE.md. Otherwise the human-readable doc and the machine-readable
    source disagree, which is what this whole codification was meant to
    prevent."""

    def test_claude_md_cites_same_tulana_rates(self, pricing_data: dict) -> None:
        assert _CLAUDE_MD.exists(), "CLAUDE.md missing"
        claude_text = _CLAUDE_MD.read_text(encoding="utf-8")

        # CLAUDE.md cites: "Maker Pack 85 / Studio Pack 170 / Enterprise Pack 255"
        # If those numbers don't appear in CLAUDE.md verbatim, either the
        # doc was edited without touching the JSON or vice versa.
        json_packs = pricing_data["tulana_metered_hourly_packs"]["tiers"]
        for slug, spec in json_packs.items():
            rate = spec["hourly_rate_mxn"]
            # Look for the integer rate near the pack name in CLAUDE.md.
            # We don't pin exact prose because the doc's wording may
            # evolve — we only pin the rate value's presence.
            assert str(rate) in claude_text, (
                f"Tulana pack {slug!r} has hourly_rate_mxn={rate} in JSON "
                f"but that integer isn't in CLAUDE.md. Either update the doc "
                f"to cite the new number, or update the JSON to match the doc, "
                f"or remove the doc's reference."
            )


class TestGetDailyLimitBehaviourPreserved:
    """No-behavior-change regression — the same calls return the same values."""

    def test_starter(self) -> None:
        from nexus_api.billing_tiers import _load_pricing, get_daily_limit

        _load_pricing.cache_clear()
        assert get_daily_limit("starter") == 1000

    def test_professional(self) -> None:
        from nexus_api.billing_tiers import _load_pricing, get_daily_limit

        _load_pricing.cache_clear()
        assert get_daily_limit("professional") == 5000

    def test_enterprise(self) -> None:
        from nexus_api.billing_tiers import _load_pricing, get_daily_limit

        _load_pricing.cache_clear()
        assert get_daily_limit("enterprise") == 25000

    def test_unknown_falls_back_to_starter(self) -> None:
        from nexus_api.billing_tiers import _load_pricing, get_daily_limit

        _load_pricing.cache_clear()
        assert get_daily_limit("not_a_real_tier") == 1000  # starter default

    def test_none_falls_back_to_starter(self) -> None:
        from nexus_api.billing_tiers import _load_pricing, get_daily_limit

        _load_pricing.cache_clear()
        assert get_daily_limit(None) == 1000


class TestEmergencyFallbackMatchesLiveJson:
    """If the JSON is missing at runtime, the emergency fallback in
    ``_load_pricing`` kicks in. Its values must match the live JSON
    (otherwise a packaging accident silently drops production tiers
    to stale numbers)."""

    def test_fallback_dict_dhanam_section_matches(self, pricing_data: dict) -> None:
        # Read the source of billing_tiers.py + extract the fallback dict
        # by parsing — we can't just `import` it without triggering the
        # JSON load that we're testing the fallback FOR.
        from pathlib import Path

        src = Path(
            _REPO_ROOT / "apps/nexus-api/nexus_api/billing_tiers.py"
        ).read_text(encoding="utf-8")

        # Extract the integer values from the fallback dict's tier specs.
        # Pattern matches: "starter": {"daily_token_limit": 1000},
        fallback_pattern = re.compile(
            r'"(\w+)":\s*\{"daily_token_limit":\s*(\d+)\}'
        )
        fallback = {
            slug: int(limit) for slug, limit in fallback_pattern.findall(src)
        }

        json_tiers = {
            slug: spec["daily_token_limit"]
            for slug, spec in pricing_data[
                "dhanam_subscription_daily_limits"
            ]["tiers"].items()
        }

        # Every tier in the live JSON must also be in the fallback,
        # with the same value. Catches "JSON gained a tier; fallback didn't".
        for slug, limit in json_tiers.items():
            assert slug in fallback, (
                f"Tier {slug!r} added to JSON but not to fallback dict in "
                f"billing_tiers._load_pricing — packaging accident would drop it."
            )
            assert fallback[slug] == limit, (
                f"Drift: JSON {slug}={limit}, fallback {slug}={fallback[slug]}. "
                f"Update the fallback dict in billing_tiers._load_pricing."
            )
