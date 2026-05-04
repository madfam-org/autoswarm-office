"""Single source of truth for Selva tier limits — JSON-backed.

The hardcoded ``TIER_DAILY_TASK_LIMIT`` dict that lived here previously
moved to ``infra/pricing/selva-tiers.json`` per the
ecosystem-cohesion remediation. Same values, same exported names —
the difference is that the JSON is the canonical source and is
schema-validated against ``infra/pricing/schema.json``.

Why the move:
    Pricing was the most contested data path in the ecosystem
    (3 places it could drift — see ROADMAP `Pricing source-of-truth`
    item). The JSON file lives in ``infra/pricing/`` so both Python
    (here) and TypeScript (office-ui future bundle-page reader) can
    consume it. The CI drift gate
    (``apps/nexus-api/tests/test_pricing_codification.py``) fails when
    a tier value drifts between this loader and the JSON.

Behaviour preserved (no production change from this refactor):

- ``TIER_DAILY_TASK_LIMIT`` still exposed as a module-level dict.
- ``DEFAULT_TIER`` still exposed.
- ``get_daily_limit(tier)`` still has the same fallback semantics.
- Stripe webhook handlers (``routers/stripe_webhooks.py``) and
  swarms / billing_internal callers don't change.

Operator follow-up:
    When Dhanam exposes its tier-fetch API, replace ``_load_pricing()``
    with a Redis-cached call against that API (the
    ``autoswarm:tier:{org_id}`` cache key already follows this
    pattern). The JSON file then becomes the bootstrap fallback only.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the canonical pricing JSON. Located under ``infra/pricing/``
# so it ships in the same commit boundary as Kustomize overlays and
# Cloudflare config. Resolved relative to the repo root by walking up
# from this file — works in editable installs and packaged deployments.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRICING_JSON = _REPO_ROOT / "infra" / "pricing" / "selva-tiers.json"


@lru_cache(maxsize=1)
def _load_pricing() -> dict[str, Any]:
    """Read + cache the pricing JSON.

    Cached because the file is read-only at runtime and re-parsing on
    every call (the dispatch hot path) would be wasteful. Tests that
    need to test against modified pricing should call
    ``_load_pricing.cache_clear()`` between assertions.
    """
    try:
        with _PRICING_JSON.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Last-resort fallback: if the JSON file is missing or
        # corrupted, ship the same defaults the previous hardcoded
        # version had so the worker still runs. Logged loud because
        # this is a real misconfig.
        logger.error(
            "Pricing JSON missing or corrupted at %s — using emergency fallback. "
            "This means CI / packaging dropped the canonical file. Investigate.",
            _PRICING_JSON,
            exc_info=True,
        )
        return {
            "dhanam_subscription_daily_limits": {
                "default_tier": "starter",
                "tiers": {
                    "starter": {"daily_token_limit": 1000},
                    "professional": {"daily_token_limit": 5000},
                    "enterprise": {"daily_token_limit": 25000},
                },
            },
            "external_a2a_default": {"daily_token_limit": 200},
        }


def _build_tier_dict() -> dict[str, int]:
    """Project the JSON's structured tier section into the flat
    ``{slug: daily_token_limit}`` shape this module has historically
    exported. Keeps every existing caller working unchanged."""
    pricing = _load_pricing()
    tiers = pricing["dhanam_subscription_daily_limits"]["tiers"]
    return {slug: spec["daily_token_limit"] for slug, spec in tiers.items()}


#: Daily compute-token budget, by Dhanam subscription tier slug.
#: Loaded once at import from infra/pricing/selva-tiers.json.
TIER_DAILY_TASK_LIMIT: dict[str, int] = _build_tier_dict()

#: Tier slug used when an org has no Dhanam subscription (or the lookup
#: failed). MUST exist as a key in ``TIER_DAILY_TASK_LIMIT``. Loaded
#: from the JSON's ``default_tier`` field.
DEFAULT_TIER: str = _load_pricing()["dhanam_subscription_daily_limits"]["default_tier"]


def get_daily_limit(tier: str | None) -> int:
    """Return the daily compute-token budget for *tier*.

    Unknown / missing tiers fall back to ``DEFAULT_TIER``'s value
    rather than raising, so a misconfigured org never blocks dispatch
    silently with a 500.
    """
    if not tier:
        return TIER_DAILY_TASK_LIMIT[DEFAULT_TIER]
    return TIER_DAILY_TASK_LIMIT.get(tier, TIER_DAILY_TASK_LIMIT[DEFAULT_TIER])


def get_tulana_hourly_rate_mxn(pack_slug: str) -> int | None:
    """Return the Tulana metered hourly rate (MXN) for *pack_slug*.

    Pack slugs (per the Tulana decision doc, 2026-04-25):
      - ``"maker_pack"`` → 85 MXN/hr
      - ``"studio_pack"`` → 170 MXN/hr
      - ``"enterprise_pack"`` → 255 MXN/hr

    Returns ``None`` for unknown slugs so callers can decide how to
    surface the error (e.g., "tier not yet defined" vs "fall back to
    Studio").

    This data is NOT used by the Stripe-tied subscription model
    (that's in ``TIER_DAILY_TASK_LIMIT`` above). Tulana hourly packs
    are the metered consumption surface that Dhanam will read at
    invoice-generation time once the metering pipeline lands. Today
    the values exist for documentation + downstream reporting only.
    """
    pricing = _load_pricing()
    packs = pricing.get("tulana_metered_hourly_packs", {}).get("tiers", {})
    spec = packs.get(pack_slug)
    if spec is None:
        return None
    return int(spec["hourly_rate_mxn"])


def get_external_a2a_daily_limit() -> int:
    """Default daily token budget for external A2A callers.

    Used by the synthetic ``"a2a-external"`` org until RFC 0018
    (per-caller external-tenant model, in flight) replaces it with
    real per-caller tenant rows. After RFC 0018 lands, the per-caller
    ``subscription_tier`` column will override this value.
    """
    pricing = _load_pricing()
    return int(pricing["external_a2a_default"]["daily_token_limit"])
