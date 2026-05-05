"""Unit tests for the cost model lookup table."""

from __future__ import annotations

import pytest

from madfam_budget_gate.cost_model import estimate_cost, known_providers


def test_known_providers_includes_core_set() -> None:
    providers = set(known_providers())
    assert {"anthropic", "openai", "deepinfra"}.issubset(providers)


def test_anthropic_opus_pricing() -> None:
    # 1M input + 1M output tokens at $15/$75 per 1M = $90.
    cost = estimate_cost("anthropic", "claude-opus-4-7", 1_000_000, 1_000_000)
    assert cost == pytest.approx(90.0)


def test_anthropic_sonnet_pricing() -> None:
    cost = estimate_cost("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_anthropic_haiku_pricing() -> None:
    cost = estimate_cost("anthropic", "claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(4.80)


def test_openai_gpt4o_mini_pricing() -> None:
    cost = estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75)


def test_unknown_model_uses_opus_fallback() -> None:
    """Unknown (provider, model) pair falls back to Claude Opus rate."""
    cost = estimate_cost("anthropic", "claude-fictional-9000", 1_000_000, 0)
    assert cost == pytest.approx(15.0)


def test_unknown_provider_uses_opus_fallback() -> None:
    cost = estimate_cost("never-heard-of-it", "model-x", 1_000_000, 0)
    assert cost == pytest.approx(15.0)


def test_missing_provider_or_model_uses_fallback() -> None:
    cost = estimate_cost(None, None, 1_000_000, 0)
    assert cost == pytest.approx(15.0)


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_cost("anthropic", "claude-opus-4-7", -1, 0)
    with pytest.raises(ValueError):
        estimate_cost("anthropic", "claude-opus-4-7", 0, -1)


def test_case_insensitive_lookup() -> None:
    a = estimate_cost("Anthropic", "Claude-Opus-4-7", 100_000, 0)
    b = estimate_cost("anthropic", "claude-opus-4-7", 100_000, 0)
    assert a == b


def test_prefix_match_handles_versioned_model_strings() -> None:
    """Model strings often include version suffixes; prefix match must catch them."""
    cost = estimate_cost("anthropic", "claude-sonnet-4-6-20260301", 1_000_000, 0)
    # Should match the claude-sonnet-4-6 entry: $3 per 1M input.
    assert cost == pytest.approx(3.0)
