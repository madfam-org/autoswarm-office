"""Single source of truth for Dhanam subscription tier limits.

Populated from CLAUDE.md / Dhanam tier matrix. When Dhanam exposes a
fetch API, replace this dict with a Redis-cached lookup populated by
``billing.py`` on subscription webhook events (the cache key
``autoswarm:tier:{org_id}`` already follows that pattern).

The values here are the static fallback used by:

- ``billing.py`` -- to seed ``autoswarm:tier:<org_id>`` after a Dhanam
  ``subscription.updated`` webhook arrives.
- ``billing_internal.py`` and ``swarms.py`` -- as the default when no
  cached tier limit exists for the org.

Keep this dict in sync with the canonical Dhanam plan matrix. A test
in ``tests/test_billing_integration.py`` exercises the
``subscription.updated`` path against the ``professional`` value.
"""

from __future__ import annotations

#: Daily compute-token budget, by Dhanam subscription tier slug.
TIER_DAILY_TASK_LIMIT: dict[str, int] = {
    "starter": 1000,
    "professional": 5000,
    "enterprise": 25000,
}

#: Tier slug used when an org has no Dhanam subscription (or the lookup
#: failed). MUST exist as a key in ``TIER_DAILY_TASK_LIMIT``.
DEFAULT_TIER: str = "starter"


def get_daily_limit(tier: str | None) -> int:
    """Return the daily compute-token budget for *tier*.

    Unknown / missing tiers fall back to ``DEFAULT_TIER``'s value
    rather than raising, so a misconfigured org never blocks dispatch
    silently with a 500.
    """
    if not tier:
        return TIER_DAILY_TASK_LIMIT[DEFAULT_TIER]
    return TIER_DAILY_TASK_LIMIT.get(tier, TIER_DAILY_TASK_LIMIT[DEFAULT_TIER])
