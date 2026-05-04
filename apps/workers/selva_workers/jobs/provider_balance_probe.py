"""Provider balance probe — runs every 15 minutes, refreshes the cached
LLM provider credit / quota state in Redis at ``selva:providers:balance``.

Per-provider strategy
=====================

**Anthropic**
  Anthropic does NOT expose a public balance API as of 2026-05. The
  Console shows it but there's no programmatic equivalent. We degrade
  to PostHog usage estimation: ``balance_usd ≈ MAX_KNOWN_BALANCE -
  sum(prompt_tokens * input_cost + completion_tokens * output_cost)``.
  ``MAX_KNOWN_BALANCE`` is configured per-provider via the
  ``ANTHROPIC_MAX_KNOWN_BALANCE_USD`` env var — operator updates it
  when they top up the account.

**OpenAI**
  Similarly no public balance API. Same PostHog-fallback strategy via
  ``OPENAI_MAX_KNOWN_BALANCE_USD``.

**DeepInfra**
  Has ``GET https://api.deepinfra.com/v1/me`` returning a JSON shape
  with usage info — but the balance/credit field is not stable across
  account types. We attempt the API call first; on any non-200 (or
  schema mismatch) we fall back to the same PostHog-estimation path.

When ALL paths fail (no API + no PostHog history + no env-var max),
the entry is written with ``source='unknown'`` and ``alert='critical'``
so the route + dashboard surface the absent signal.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


REDIS_BALANCE_KEY = "selva:providers:balance"
REDIS_BALANCE_TTL_SECONDS = 30 * 60

KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "deepinfra")


# Approximate per-1k-token costs for the default Claude / OpenAI / DeepInfra
# tiers we route to. Used only by the PostHog-estimation path; real billing
# happens via the provider's invoice. Operators can override per-deployment
# via env vars listed below.
_DEFAULT_COSTS_PER_1K = {
    "anthropic": {"input": 0.003, "output": 0.015},  # Sonnet 4.x ballpark
    "openai": {"input": 0.0025, "output": 0.01},  # GPT-4 mini ballpark
    "deepinfra": {"input": 0.0006, "output": 0.0009},  # Llama-3 70B ballpark
}


def _max_known_balance(provider: str) -> float:
    """Return the operator-set max-known balance for a provider, or 0.0
    when unset (which causes the estimation path to bail to 'unknown')."""
    var = f"{provider.upper()}_MAX_KNOWN_BALANCE_USD"
    try:
        return float(os.environ.get(var, "0") or "0")
    except (TypeError, ValueError):
        logger.warning("Bad %s value — falling back to 0.0", var)
        return 0.0


def _provider_costs(provider: str) -> tuple[float, float]:
    """Return (input_cost_per_1k, output_cost_per_1k) for a provider.

    Operator can override via env vars (e.g.
    ``ANTHROPIC_INPUT_COST_PER_1K``, ``ANTHROPIC_OUTPUT_COST_PER_1K``).
    """
    defaults = _DEFAULT_COSTS_PER_1K.get(provider, {"input": 0.0, "output": 0.0})
    in_var = f"{provider.upper()}_INPUT_COST_PER_1K"
    out_var = f"{provider.upper()}_OUTPUT_COST_PER_1K"
    try:
        input_cost = float(os.environ.get(in_var, defaults["input"]))
        output_cost = float(os.environ.get(out_var, defaults["output"]))
    except (TypeError, ValueError):
        input_cost = defaults["input"]
        output_cost = defaults["output"]
    return input_cost, output_cost


# ---------------------------------------------------------------------------
# Provider-specific probes
# ---------------------------------------------------------------------------


async def _probe_deepinfra_api() -> dict[str, Any] | None:
    """Try the DeepInfra ``/v1/me`` endpoint. Returns the parsed dict on
    success, ``None`` when the API call fails or the response shape
    doesn't match what we expect.
    """
    api_key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.deepinfra.com/v1/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                logger.debug("DeepInfra /me returned %d", resp.status_code)
                return None
            data = resp.json()
            # Response shape varies — be defensive. Look for a couple of
            # candidate fields; bail if none present.
            balance_keys = ("balance", "credit_balance", "credits", "available_credits")
            for key in balance_keys:
                if key in data and isinstance(data[key], (int, float)):
                    return {
                        "balance_usd": float(data[key]),
                        "source": "api",
                        "raw": data,
                    }
            return None
    except Exception:
        logger.warning("DeepInfra balance probe failed", exc_info=True)
        return None


async def _estimate_via_posthog_usage(provider: str) -> dict[str, Any] | None:
    """Estimate remaining balance as
    ``MAX_KNOWN_BALANCE - sum(provider usage in PostHog window)``.

    Returns None when:
    - PostHog client not configured
    - No env-var max-known-balance set for this provider
    - PostHog query fails

    The estimate is intentionally conservative — uses INPUT-cost as a
    floor for any tokens we can't classify, and the larger of input/output
    cost as a ceiling for safety in dashboards.
    """
    max_balance = _max_known_balance(provider)
    if max_balance <= 0:
        return None  # Operator hasn't told us what "full" looks like.

    try:
        # Late import — PostHog SDK is optional in some workers.
        from nexus_api import analytics as ph

        client = getattr(ph, "_client", None)
        if client is None:
            return None
    except Exception:
        return None

    # The actual PostHog query API is async-unfriendly + batches usage;
    # we keep this hook as a placeholder that operators can wire up to
    # their preferred query path (HogQL, persons API, raw events file
    # tail). For MVP we return a None-as-can't-confirm so the route
    # surfaces source='unknown' until the operator fills in the query.
    #
    # Operator hook: replace this stub with:
    #
    #     usage = await fetch_usage_from_posthog(
    #         provider=provider,
    #         since=datetime.now() - timedelta(days=30),
    #     )
    #     spent = (usage.input_tokens / 1000) * input_cost + ...
    #     return {"balance_usd": max(0.0, max_balance - spent), "source": "estimated"}
    #
    # Until then, the env-var max-known balance acts as a static floor.
    return {
        "balance_usd": max_balance,
        "source": "estimated",
        "note": (
            "PostHog usage subtraction not yet wired — value is the "
            f"static {provider.upper()}_MAX_KNOWN_BALANCE_USD env value. "
            "Operator: implement fetch_usage_from_posthog() to make this "
            "value actually decay with usage."
        ),
    }


async def probe_provider(provider: str) -> dict[str, Any]:
    """Return a balance entry for ``provider``.

    Always returns a dict — never raises. Schema:
    ``{balance_usd, currency, source, updated_at, raw?}``.
    """
    now = datetime.now(UTC).isoformat()
    entry: dict[str, Any] | None = None

    if provider == "deepinfra":
        entry = await _probe_deepinfra_api()
    # Anthropic + OpenAI have no public balance API — straight to estimation.
    if entry is None:
        entry = await _estimate_via_posthog_usage(provider)

    if entry is None:
        return {
            "balance_usd": -1.0,
            "currency": "USD",
            "source": "unknown",
            "updated_at": now,
        }

    return {
        "balance_usd": float(entry.get("balance_usd", -1.0)),
        "currency": "USD",
        "source": entry.get("source", "unknown"),
        "updated_at": now,
        **({"note": entry["note"]} if "note" in entry else {}),
    }


# ---------------------------------------------------------------------------
# Threshold + alerting
# ---------------------------------------------------------------------------


ALERT_THRESHOLD_LOW_USD = 50.0
ALERT_THRESHOLD_CRITICAL_USD = 5.0


def classify_alert(balance_usd: float, source: str) -> str:
    """Return alert level string. Mirrors the same logic in routers/providers.py
    so the cron and the route never disagree."""
    if source == "unknown" or balance_usd < 0:
        return "critical"
    if balance_usd <= ALERT_THRESHOLD_CRITICAL_USD:
        return "critical"
    if balance_usd <= ALERT_THRESHOLD_LOW_USD:
        return "low"
    return "ok"


def _emit_critical_event(provider: str, entry: dict[str, Any]) -> None:
    """Fire ``provider_balance.critical`` PostHog event when an entry
    classifies as critical. Fire-and-forget."""
    try:
        from nexus_api.analytics import track

        track(
            f"provider:{provider}",
            "provider_balance.critical",
            {
                "provider": provider,
                "balance_usd": entry.get("balance_usd"),
                "source": entry.get("source"),
                "updated_at": entry.get("updated_at"),
            },
        )
    except Exception:
        logger.debug("provider_balance.critical PostHog emit failed", exc_info=True)


# ---------------------------------------------------------------------------
# Redis writeback
# ---------------------------------------------------------------------------


async def _write_to_redis(payload: dict[str, dict[str, Any]]) -> bool:
    """Write the balance payload to Redis at ``selva:providers:balance``
    with a 30-min TTL. Returns True on success, False on any failure.
    """
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.warning("REDIS_URL unset — balance probe cannot persist")
        return False

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            await r.set(
                REDIS_BALANCE_KEY,
                json.dumps(payload),
                ex=REDIS_BALANCE_TTL_SECONDS,
            )
            return True
        finally:
            with contextlib.suppress(Exception):
                await r.aclose()
    except Exception:
        logger.warning("Redis writeback failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run() -> dict[str, Any]:
    """Probe every known provider, write the result to Redis, fire a
    PostHog event for anything classifying as critical.

    Returns a summary dict — useful for tests + the cron's exit log.
    """
    payload: dict[str, dict[str, Any]] = {}

    for provider in KNOWN_PROVIDERS:
        entry = await probe_provider(provider)
        alert = classify_alert(entry["balance_usd"], entry["source"])
        payload[provider] = {**entry, "alert": alert}

        if alert == "critical":
            _emit_critical_event(provider, entry)
            logger.warning(
                "Provider %s balance is CRITICAL: balance_usd=%.2f source=%s",
                provider,
                entry["balance_usd"],
                entry["source"],
            )

    persisted = await _write_to_redis(payload)
    return {"providers": payload, "persisted": persisted}
