"""LLM provider balance probe — admin endpoint surfacing cached provider
credit / quota state so ops doesn't have to log into the Anthropic console
manually to discover we're at $0.

Background: on 2026-04-16 the Anthropic primary hit $0 credits and the
LLM router silently shipped placeholder text to real customers for
several hours before anyone noticed (the router PR fix/router-400-fallback
closes the silent-failure mode; this PR closes the
no-visibility mode that delayed detection).

Probe lifecycle:
- Cron job at ``apps/workers/selva_workers/jobs/provider_balance_probe.py``
  runs every 15 minutes, hits whatever balance/usage API each provider
  exposes (and falls back to PostHog usage estimation when none exists),
  and stores the result in Redis at ``selva:providers:balance`` with a
  30-min TTL.
- ``GET /api/v1/providers/balance`` (admin role required) returns the
  cached state. When the cache is missing the route degrades to the
  same provider-fingerprint dict but with ``source="unknown"`` and
  ``alert="critical"``, NEVER 5xx — the goal is to surface the missing
  signal, not hide it.

Threshold ladder (per-provider, USD):
- ``ok``        balance > $50
- ``low``       $5 < balance <= $50
- ``critical``  balance <= $5  (also fires PostHog ``provider_balance.critical``)
- ``unknown``   no signal at all (treated as critical for alerting)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from selva_redis_pool import get_redis_pool

from ..auth import CurrentUser, require_roles
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Constants — single source of truth for the cron + the route
# ---------------------------------------------------------------------------


REDIS_BALANCE_KEY = "selva:providers:balance"
REDIS_BALANCE_TTL_SECONDS = 30 * 60

# Per-provider list. Keep in sync with the cron probe so the route never
# returns a provider name the probe doesn't know how to populate.
KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "deepinfra")

ALERT_THRESHOLD_LOW_USD = 50.0
ALERT_THRESHOLD_CRITICAL_USD = 5.0


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProviderBalance(BaseModel):
    """Cached balance state for a single provider."""

    balance_usd: float = Field(
        ...,
        description=(
            "Estimated USD balance / remaining quota. -1 when unknown "
            "(degraded path: no API + no PostHog history)."
        ),
    )
    currency: str = Field(default="USD", description="Always USD at MVP.")
    source: str = Field(
        ...,
        description=(
            "How the value was derived: 'api' (direct provider balance API), "
            "'estimated' (max_known_balance - PostHog usage sum), or 'unknown' "
            "(no signal — treat as critical for alerting)."
        ),
    )
    updated_at: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when the probe last refreshed this entry.",
    )
    alert: str = Field(
        ...,
        description="One of 'ok' / 'low' / 'critical' / 'unknown'.",
    )


def classify_alert(balance_usd: float, source: str) -> str:
    """Return alert level for a balance reading.

    - source=='unknown' OR balance_usd<0: 'critical' — the alert is the
      ABSENCE of signal. Reading a real $0 and getting nothing should
      not be silently downgraded.
    - balance_usd <= $5: 'critical'
    - balance_usd <= $50: 'low'
    - otherwise: 'ok'
    """
    if source == "unknown" or balance_usd < 0:
        return "critical"
    if balance_usd <= ALERT_THRESHOLD_CRITICAL_USD:
        return "critical"
    if balance_usd <= ALERT_THRESHOLD_LOW_USD:
        return "low"
    return "ok"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/balance", response_model=dict[str, ProviderBalance])
async def get_provider_balances(
    _user: CurrentUser = Depends(require_roles(["admin", "platform"])),
) -> dict[str, ProviderBalance]:
    """Return the most recent cached balance for every known LLM provider.

    The cache is populated by the 15-min cron at
    ``apps/workers/selva_workers/jobs/provider_balance_probe.py``.

    Behaviour when the cache is empty / Redis is unreachable:
    - Returns one entry per provider in ``KNOWN_PROVIDERS`` with
      ``source='unknown'`` and ``alert='critical'``.
    - 200 OK, never 5xx — the goal is to surface the missing signal,
      not hide it behind a server error.
    """
    settings = get_settings()
    cached: dict[str, Any] = {}

    try:
        pool = get_redis_pool(url=settings.redis_url)
        raw = await pool.get(REDIS_BALANCE_KEY)
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            cached = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        logger.warning("Provider balance read from Redis failed", exc_info=True)
        cached = {}

    result: dict[str, ProviderBalance] = {}
    for name in KNOWN_PROVIDERS:
        entry = cached.get(name) if isinstance(cached, dict) else None
        if isinstance(entry, dict):
            balance_usd = float(entry.get("balance_usd", -1.0))
            source = str(entry.get("source", "unknown"))
            updated_at = str(entry.get("updated_at", ""))
        else:
            balance_usd = -1.0
            source = "unknown"
            updated_at = ""

        currency = "USD"
        if isinstance(entry, dict):
            currency = str(entry.get("currency", "USD"))
        result[name] = ProviderBalance(
            balance_usd=balance_usd,
            currency=currency,
            source=source,
            updated_at=updated_at,
            alert=classify_alert(balance_usd, source),
        )

    return result
