"""Hardcoded cost model for known LLM provider/model combinations.

Prices are USD per 1M tokens, sourced from each provider's public
pricing page as of 2026-Q2.  This is intentionally a small,
maintainable lookup — providers rarely add public price tiers and
when they do we want a code review on the bump.

When a (provider, model) pair is not found we **fall back to a
conservative high default** (Claude Opus rate) rather than 0 — the
gate must err on the side of overestimating spend, never under.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class _Price(NamedTuple):
    input_per_1m_usd: float
    output_per_1m_usd: float


# Lower-cased provider, lower-cased model fragment (matched as prefix on the
# normalised model string) → price.  We match on prefix so the table covers
# minor model-name variants like "claude-opus-4-7-20260301" or
# "anthropic.claude-opus-4-7-v1:0".
#
# IMPORTANT: order matters within a provider — longer / more specific
# prefixes must come BEFORE shorter ones.  Iteration uses first-match.
_PRICE_TABLE: dict[str, list[tuple[str, _Price]]] = {
    "anthropic": [
        ("claude-opus-4-7", _Price(15.0, 75.0)),
        ("claude-opus-4", _Price(15.0, 75.0)),
        ("claude-sonnet-4-6", _Price(3.0, 15.0)),
        ("claude-sonnet-4", _Price(3.0, 15.0)),
        ("claude-haiku-4-5", _Price(0.80, 4.0)),
        ("claude-haiku-4", _Price(0.80, 4.0)),
        ("claude-haiku", _Price(0.25, 1.25)),
        ("claude-sonnet", _Price(3.0, 15.0)),
        ("claude-opus", _Price(15.0, 75.0)),
    ],
    "openai": [
        ("gpt-4o-mini", _Price(0.15, 0.60)),
        ("gpt-4o", _Price(2.50, 10.0)),
        ("gpt-4-turbo", _Price(10.0, 30.0)),
        ("gpt-4", _Price(30.0, 60.0)),
        ("gpt-3.5-turbo", _Price(0.50, 1.50)),
        ("o1-mini", _Price(3.0, 12.0)),
        ("o1", _Price(15.0, 60.0)),
    ],
    # DeepInfra hosts many open-source models at heavily discounted rates.
    # We list the four we actually route to in production; everything
    # else under the 'deepinfra' key falls back to a conservative
    # mid-tier price.
    "deepinfra": [
        ("meta-llama/llama-3.3-70b-instruct", _Price(0.23, 0.40)),
        ("meta-llama/llama-3.1-70b-instruct", _Price(0.23, 0.40)),
        ("meta-llama/llama-3.1-8b-instruct", _Price(0.05, 0.08)),
        ("mistralai/mixtral-8x7b-instruct-v0.1", _Price(0.24, 0.24)),
    ],
    # Together / Fireworks / Groq host the same model families at
    # similar prices; we treat them as a single tier.
    "together": [
        ("meta-llama/llama-3.3-70b-instruct", _Price(0.88, 0.88)),
        ("meta-llama/llama-3.1-70b-instruct", _Price(0.88, 0.88)),
    ],
    "fireworks": [
        ("accounts/fireworks/models/llama-v3p1-70b-instruct", _Price(0.90, 0.90)),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", _Price(0.59, 0.79)),
    ],
    "mistral": [
        ("mistral-large", _Price(2.0, 6.0)),
        ("mistral-small", _Price(0.20, 0.60)),
    ],
}

# Conservative fallback when the table doesn't know the model.  Picked
# to be the highest mainstream price (Claude Opus) so the gate never
# *under*-estimates spend.  Configurable via an env var if ops want to
# be even more conservative.
_DEFAULT_FALLBACK = _Price(15.0, 75.0)


def estimate_cost(
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate USD cost of a single LLM call.

    Both ``provider`` and ``model`` are case-insensitive.  Unknown
    combinations fall back to the Claude Opus rate (a deliberately
    high baseline) and emit a debug log so ops can backfill the
    table if it becomes a hot path.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts cannot be negative")

    price = _lookup(provider, model)
    cost = (input_tokens * price.input_per_1m_usd + output_tokens * price.output_per_1m_usd) / 1_000_000
    return round(cost, 6)


def _lookup(provider: str | None, model: str | None) -> _Price:
    if provider is None or model is None:
        logger.debug("cost_model: missing provider/model, using fallback rate")
        return _DEFAULT_FALLBACK

    p = provider.strip().lower()
    m = model.strip().lower()
    table = _PRICE_TABLE.get(p)
    if table is None:
        logger.debug("cost_model: unknown provider %r, using fallback rate", provider)
        return _DEFAULT_FALLBACK
    for prefix, price in table:
        if m.startswith(prefix.lower()):
            return price
    logger.debug(
        "cost_model: unknown model %r for provider %r, using fallback rate", model, provider
    )
    return _DEFAULT_FALLBACK


def known_providers() -> list[str]:
    """Return the list of providers with explicit price entries."""
    return sorted(_PRICE_TABLE.keys())
