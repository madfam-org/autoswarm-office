"""Checkout tier vocabulary — validated against Dhanam's live catalog.

Why this module exists: checkout used to validate tiers against the static
pricing JSON (``starter`` / ``professional`` / ``enterprise``) while Dhanam's
catalog sells the ``selva`` product under different slugs (``developer`` /
``team`` / ``business``). The two vocabularies were fully disjoint, so every
slug that passed local validation was rejected upstream and every slug Dhanam
actually sells failed local validation — checkout could not succeed for any
input. Two hand-maintained vocabularies WILL drift again, so validation now
reads the catalog itself:

- Valid tiers come from ``GET /billing/catalog/selva`` (public, no auth),
  cached for a short TTL that mirrors Dhanam's own catalog cache.
- When the catalog is unreachable the static pricing JSON is the offline
  fallback, canonicalized through the same legacy-alias map so the fallback
  speaks the catalog's vocabulary. The fallback is LOUD (warning log with a
  stable marker) — a silent fallback is this repo's documented fail-open
  defect class.
- Legacy slugs stay accepted via ``LEGACY_TIER_ALIASES`` because the live
  pricing page (``/billing/tiers``, sourced from the static JSON) still emits
  them; each use logs a deprecation warning so their removal is measurable.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

#: Dhanam catalog product slug for this platform. Checkout plan ids are the
#: fully-qualified ``{product}_{tier}`` form of this slug + the tier slug.
SELVA_PRODUCT_SLUG = "selva"

#: Legacy tier slugs (static pricing JSON vocabulary, still served by the
#: pricing page and possibly bookmarked) mapped to the catalog slugs Dhanam
#: sells. An exact catalog match always wins over this map, so if the catalog
#: ever (re)introduces one of these keys the catalog meaning prevails.
LEGACY_TIER_ALIASES: dict[str, str] = {
    "starter": "developer",
    "professional": "team",
    "enterprise": "business",
}

#: Inverse of ``LEGACY_TIER_ALIASES``: Dhanam catalog tier slug → the pricing
#: JSON slug the rest of this codebase speaks (``billing_tiers`` daily limits,
#: the pricing page, the Stripe price-id map). The webhook reader uses this so
#: a purchase of catalog tier ``team`` lands as ``professional`` in
#: ``tenant_configs.subscription_tier`` — the vocabulary ``get_daily_limit``
#: resolves. Slugs missing from this map pass through unchanged, so if the
#: pricing JSON ever adopts the catalog vocabulary nothing double-translates.
CATALOG_TIER_TO_PRICING_SLUG: dict[str, str] = {
    catalog: legacy for legacy, catalog in LEGACY_TIER_ALIASES.items()
}

# Mirrors Dhanam's catalog cache TTL. Successful fetches are cached; failures
# are not, so a recovering catalog is picked up on the next checkout attempt.
_CATALOG_TTL_SECONDS = 300.0

_catalog_cache: tuple[float, frozenset[str]] | None = None


def reset_catalog_cache() -> None:
    """Drop the cached catalog tier set (tests + operator hot-reload)."""
    global _catalog_cache
    _catalog_cache = None


def plan_id_for_tier(tier: str) -> str:
    """Fully-qualified Dhanam catalog plan id for a canonical tier slug.

    Dhanam's price resolution parses ``{product}_{tier}``; an unprefixed slug
    is attributed to the default product, not to Selva.
    """
    return f"{SELVA_PRODUCT_SLUG}_{tier}"


def tier_for_plan_id(plan_id: str) -> str | None:
    """Inverse of :func:`plan_id_for_tier`: ``selva_team`` → ``team``.

    This is the reader-side half of the plan-id contract. Dhanam's outbound
    product webhooks echo the plan id verbatim in ``data.plan_id``, and its
    dispatcher routes on the ``{product}_`` prefix — so anything delivered to
    Selva's subscription webhook should be ``selva_{tier}``.

    Returns ``None`` when *plan_id* does not carry a Selva tier: either it
    belongs to another product (``janua_pro``, a bare Dhanam consumer slug
    like ``essentials``) or it is the bare product slug ``selva`` with no
    tier segment. Callers distinguish those two cases via
    :data:`SELVA_PRODUCT_SLUG` when the difference matters.
    """
    slug = plan_id.strip().lower()
    prefix = f"{SELVA_PRODUCT_SLUG}_"
    if not slug.startswith(prefix):
        return None
    return slug[len(prefix) :] or None


def pricing_slug_for_catalog_tier(tier: str) -> str:
    """Map a Dhanam catalog tier slug onto the pricing-JSON vocabulary.

    ``team`` → ``professional``; slugs already in (or unknown to) the pricing
    vocabulary pass through unchanged so callers can validate the result
    against ``billing_tiers.is_valid_subscription_tier`` and decide how loud
    to be about novel slugs.
    """
    slug = tier.strip().lower()
    return CATALOG_TIER_TO_PRICING_SLUG.get(slug, slug)


async def _fetch_catalog_tier_slugs() -> frozenset[str]:
    """One catalog round-trip; raises on transport errors or an untrustworthy
    shape (no product / no tiers) so the caller falls back explicitly."""
    from ..billing_client import DhanamClient
    from ..config import get_settings

    settings = get_settings()
    if not settings.dhanam_api_url:
        raise RuntimeError("dhanam_api_url is not configured")

    client = DhanamClient(settings.dhanam_api_url)
    product = await client.get_catalog(SELVA_PRODUCT_SLUG)

    slugs = frozenset(
        slug
        for entry in product.get("tiers") or []
        if isinstance(entry, dict)
        and (slug := str(entry.get("tierSlug") or entry.get("slug") or "").strip().lower())
    )
    if not slugs:
        raise ValueError(f"catalog product {SELVA_PRODUCT_SLUG!r} lists no tiers")
    return slugs


def _static_fallback_tiers() -> frozenset[str]:
    """Static pricing-JSON slugs, canonicalized through the alias map so the
    offline fallback validates the same vocabulary the catalog does."""
    from ..billing_tiers import get_subscription_tiers

    slugs = {str(t["slug"]).strip().lower() for t in get_subscription_tiers()}
    return frozenset(LEGACY_TIER_ALIASES.get(slug, slug) for slug in slugs)


async def get_valid_checkout_tiers() -> tuple[frozenset[str], str]:
    """Return ``(valid tier slugs, source)``.

    ``source`` is ``"catalog"`` (live, possibly TTL-cached) or
    ``"static-fallback"`` (catalog unreachable/untrustworthy — logged loudly).
    """
    global _catalog_cache
    now = time.monotonic()
    if _catalog_cache is not None and now < _catalog_cache[0]:
        return _catalog_cache[1], "catalog"

    try:
        slugs = await _fetch_catalog_tier_slugs()
    except Exception:
        # Loud on purpose: the silent-fallback pattern is how the pricing
        # JSON packaging gap went unnoticed in production.
        logger.warning(
            "checkout_tier_catalog_unavailable: could not read Dhanam catalog "
            "product %r; validating checkout tiers against the static pricing "
            "JSON fallback until the catalog recovers",
            SELVA_PRODUCT_SLUG,
            exc_info=True,
        )
        return _static_fallback_tiers(), "static-fallback"

    _catalog_cache = (now + _CATALOG_TTL_SECONDS, slugs)
    return slugs, "catalog"


async def resolve_checkout_tier(requested: str) -> str | None:
    """Map *requested* onto the canonical catalog tier slug.

    Precedence: an exact catalog match wins; otherwise a legacy alias is
    honored with a deprecation warning. Returns ``None`` when the slug is not
    purchasable under either vocabulary.
    """
    slug = requested.strip().lower()
    valid, _source = await get_valid_checkout_tiers()

    if slug in valid:
        return slug

    canonical = LEGACY_TIER_ALIASES.get(slug)
    if canonical is not None and canonical in valid:
        logger.warning(
            "checkout_tier_legacy_alias: tier %r mapped to catalog tier %r; "
            "the legacy slug is deprecated — update the caller",
            slug,
            canonical,
        )
        return canonical

    return None
