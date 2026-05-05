"""Unit tests for BudgetScope identity and parent chain."""

from __future__ import annotations

from madfam_budget_gate.scope import BudgetScope, CapConfig, ResolvedCaps, resolve_caps


def test_global_scope_hash_is_stable() -> None:
    assert BudgetScope().hash_key() == "global"
    assert BudgetScope().is_global is True


def test_org_scope_hash_is_deterministic() -> None:
    a1 = BudgetScope(org_id="acme").hash_key()
    a2 = BudgetScope(org_id="acme").hash_key()
    b = BudgetScope(org_id="other").hash_key()
    assert a1 == a2
    assert a1 != b
    assert len(a1) == 16


def test_agent_chain_includes_org_and_global() -> None:
    s = BudgetScope(org_id="acme", agent_id="reddit_promo_v1")
    chain = s.chain()
    assert chain[0] == s
    assert BudgetScope(org_id="acme") in chain
    assert BudgetScope() in chain
    assert len(chain) == 3


def test_org_chain_includes_global_only() -> None:
    s = BudgetScope(org_id="acme")
    chain = s.chain()
    assert chain == [s, BudgetScope()]


def test_global_chain_is_self_only() -> None:
    """Global scope's chain must not include itself twice (regression guard)."""
    s = BudgetScope()
    assert s.parents() == []
    assert s.chain() == [s]


def test_resolve_caps_falls_through_to_env_defaults() -> None:
    env = ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )
    scope = BudgetScope(org_id="acme")
    resolved = resolve_caps(scope, overrides={}, env_defaults=env)
    assert resolved == env


def test_resolve_caps_org_override_beats_global() -> None:
    env = ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )
    overrides = {
        BudgetScope(): CapConfig(daily_usd=20.0),
        BudgetScope(org_id="acme"): CapConfig(daily_usd=5.0),
    }
    resolved = resolve_caps(
        BudgetScope(org_id="acme", agent_id="x"),
        overrides=overrides,
        env_defaults=env,
    )
    assert resolved.daily_usd == 5.0  # org wins
    # monthly_usd not set anywhere → env default
    assert resolved.monthly_usd == env.monthly_usd


def test_resolve_caps_agent_override_beats_org() -> None:
    env = ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )
    overrides = {
        BudgetScope(org_id="acme"): CapConfig(daily_usd=5.0),
        BudgetScope(org_id="acme", agent_id="x"): CapConfig(daily_usd=1.0),
    }
    resolved = resolve_caps(
        BudgetScope(org_id="acme", agent_id="x"),
        overrides=overrides,
        env_defaults=env,
    )
    assert resolved.daily_usd == 1.0
