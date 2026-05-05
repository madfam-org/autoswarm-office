"""End-to-end tests for the BudgetGate facade."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytest

from madfam_budget_gate import BudgetGate, BudgetScope, GateDecision, RedisStore
from madfam_budget_gate.scope import CapConfig, ResolvedCaps


# ─────────────────────────────────────────────────────────────────────────────
# Cap enforcement (hard-deny)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_allows_under_cap(gate: BudgetGate, now: datetime) -> None:
    decision = await gate.check(
        BudgetScope(org_id="acme"),
        estimated_tokens=100,
        estimated_cost_usd=0.01,
        now=now,
    )
    assert decision.allowed is True
    assert decision.soft_warn is False


@pytest.mark.asyncio
async def test_check_denies_when_daily_usd_exceeded(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    scope = BudgetScope(org_id="acme")
    # Pre-spend 9.50 of the 10.0 daily cap.
    await store.increment(scope, usd=9.50, tokens=0, now=now)
    decision = await gate.check(
        scope, estimated_tokens=0, estimated_cost_usd=1.00, now=now
    )
    assert decision.allowed is False
    assert "daily USD cap exhausted" in decision.reason
    assert decision.retry_after_seconds is not None
    assert decision.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_check_denies_when_daily_tokens_exceeded(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    scope = BudgetScope(org_id="acme")
    await store.increment(scope, usd=0.0, tokens=999_999, now=now)
    decision = await gate.check(
        scope, estimated_tokens=2, estimated_cost_usd=0.0, now=now
    )
    assert decision.allowed is False
    assert "daily token cap exhausted" in decision.reason


@pytest.mark.asyncio
async def test_check_denies_when_monthly_usd_exceeded(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    """Monthly cap kicks in before daily would, when daily=10 month=200."""
    scope = BudgetScope(org_id="acme")
    # Spend 199.50 across the month — daily counter for `now` stays at 0
    # because the increment is on a different day, but monthly counter holds.
    yesterday = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    await store.increment(scope, usd=199.50, tokens=0, now=yesterday)
    decision = await gate.check(
        scope, estimated_tokens=0, estimated_cost_usd=1.00, now=now
    )
    assert decision.allowed is False
    assert "monthly USD cap exhausted" in decision.reason


# ─────────────────────────────────────────────────────────────────────────────
# Soft-warn
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_warn_fires_at_threshold(
    gate: BudgetGate,
    now: datetime,
    store: RedisStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scope = BudgetScope(org_id="acme")
    # Pre-spend 7.99 — projected 8.49 = 84.9% of $10 cap, above 80% threshold.
    await store.increment(scope, usd=7.99, tokens=0, now=now)
    with caplog.at_level(logging.WARNING, logger="madfam_budget_gate.gate"):
        decision = await gate.check(
            scope, estimated_tokens=0, estimated_cost_usd=0.50, now=now
        )

    assert decision.allowed is True
    assert decision.soft_warn is True
    assert "soft-warn threshold" in decision.reason
    assert any("budget-gate.soft_warn" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_no_soft_warn_below_threshold(
    gate: BudgetGate, now: datetime
) -> None:
    decision = await gate.check(
        BudgetScope(org_id="acme"),
        estimated_tokens=0,
        estimated_cost_usd=0.10,  # 1% of $10 cap
        now=now,
    )
    assert decision.soft_warn is False


# ─────────────────────────────────────────────────────────────────────────────
# Recording / chain propagation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_propagates_to_org_and_global(
    gate: BudgetGate, now: datetime
) -> None:
    scope = BudgetScope(org_id="acme", agent_id="reddit")
    await gate.record(
        scope,
        actual_tokens=2_000,
        actual_cost_usd=0.50,
        provider="anthropic",
        model="claude-sonnet-4-6",
        now=now,
    )

    # Agent scope sees the spend.
    agent_status = await gate.status(scope, now=now)
    assert agent_status["daily"]["used_usd"] == pytest.approx(0.50)
    assert agent_status["daily"]["used_tokens"] == 2_000

    # Org scope sees the same spend.
    org_status = await gate.status(BudgetScope(org_id="acme"), now=now)
    assert org_status["daily"]["used_usd"] == pytest.approx(0.50)

    # Global scope also sees it.
    global_status = await gate.status(BudgetScope(), now=now)
    assert global_status["daily"]["used_usd"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_record_estimates_cost_when_not_supplied(
    gate: BudgetGate, now: datetime
) -> None:
    scope = BudgetScope(org_id="acme")
    await gate.record(
        scope,
        actual_tokens=1_000_000,
        provider="anthropic",
        model="claude-haiku-4-5",
        now=now,
    )
    status = await gate.status(scope, now=now)
    # haiku-4-5 = $0.80 / $4.00 per 1M.  Default 30/70 split → 300k input + 700k output.
    # cost = (300_000 * 0.80 + 700_000 * 4.0) / 1M = 0.24 + 2.80 = $3.04
    assert status["daily"]["used_usd"] == pytest.approx(3.04, rel=0.01)


@pytest.mark.asyncio
async def test_record_uses_explicit_input_output_split(
    gate: BudgetGate, now: datetime
) -> None:
    scope = BudgetScope(org_id="acme")
    await gate.record(
        scope,
        actual_tokens=2_000,
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=1_500,
        output_tokens=500,
        now=now,
    )
    # sonnet-4-6 = $3 / $15 per 1M.  cost = (1500*3 + 500*15) / 1M = 0.0045 + 0.0075 = $0.012
    status = await gate.status(scope, now=now)
    assert status["daily"]["used_usd"] == pytest.approx(0.012, rel=0.01)


@pytest.mark.asyncio
async def test_record_rejects_negative_tokens(gate: BudgetGate) -> None:
    with pytest.raises(ValueError):
        await gate.record(BudgetScope(), actual_tokens=-1)


# ─────────────────────────────────────────────────────────────────────────────
# Cap overrides
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_cap_persists_and_resolves(gate: BudgetGate, now: datetime) -> None:
    scope = BudgetScope(org_id="acme")
    await gate.set_cap(scope, daily_usd=2.0)
    status = await gate.status(scope, now=now)
    assert status["daily"]["cap_usd"] == 2.0


@pytest.mark.asyncio
async def test_per_scope_cap_overrides_env_default(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    scope = BudgetScope(org_id="acme")
    await gate.set_cap(scope, daily_usd=2.0)  # tighter than env default of $10
    await store.increment(scope, usd=1.99, tokens=0, now=now)
    decision = await gate.check(
        scope, estimated_tokens=0, estimated_cost_usd=0.50, now=now
    )
    assert decision.allowed is False
    assert "daily USD cap exhausted" in decision.reason


@pytest.mark.asyncio
async def test_agent_cap_more_restrictive_than_org(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    org = BudgetScope(org_id="acme")
    agent = BudgetScope(org_id="acme", agent_id="x")
    await gate.set_cap(org, daily_usd=10.0)  # generous org
    await gate.set_cap(agent, daily_usd=1.0)  # tight agent

    decision_under = await gate.check(
        agent, estimated_tokens=0, estimated_cost_usd=0.50, now=now
    )
    assert decision_under.allowed is True

    await store.increment(agent, usd=0.99, tokens=0, now=now)
    decision_over = await gate.check(
        agent, estimated_tokens=0, estimated_cost_usd=0.50, now=now
    )
    assert decision_over.allowed is False


@pytest.mark.asyncio
async def test_clear_cap_removes_override(gate: BudgetGate, now: datetime) -> None:
    scope = BudgetScope(org_id="acme")
    await gate.set_cap(scope, daily_usd=2.0)
    await gate.clear_cap(scope)
    status = await gate.status(scope, now=now)
    # Falls back to env default of $10.
    assert status["daily"]["cap_usd"] == 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Status snapshot
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_returns_remaining_headroom(
    gate: BudgetGate, now: datetime, store: RedisStore
) -> None:
    scope = BudgetScope(org_id="acme")
    await store.increment(scope, usd=3.0, tokens=200_000, now=now)
    status = await gate.status(scope, now=now)
    assert status["daily"]["remaining_usd"] == pytest.approx(7.0)
    assert status["daily"]["remaining_tokens"] == 800_000
    assert status["scope"]["org_id"] == "acme"


# ─────────────────────────────────────────────────────────────────────────────
# Failure modes
# ─────────────────────────────────────────────────────────────────────────────


class _BrokenRedis:
    async def incrbyfloat(self, *args: Any, **kwargs: Any) -> float:
        raise ConnectionError("redis down")

    async def incrby(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")

    async def expire(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    async def get(self, *args: Any, **kwargs: Any) -> bytes | None:
        raise ConnectionError("redis down")

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")

    async def mget(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise ConnectionError("redis down")

    async def ping(self) -> bool:
        raise ConnectionError("redis down")


@pytest.fixture
def env_defaults_strict() -> ResolvedCaps:
    return ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )


@pytest.mark.asyncio
async def test_redis_outage_fail_closed_by_default(
    env_defaults_strict: ResolvedCaps,
) -> None:
    broken_store = RedisStore(_BrokenRedis())
    gate = BudgetGate(broken_store, env_defaults=env_defaults_strict, fail_open=False)
    decision = await gate.check(BudgetScope(org_id="acme"))
    assert decision.allowed is False
    assert "fail" in decision.reason.lower()


@pytest.mark.asyncio
async def test_redis_outage_fail_open_when_configured(
    env_defaults_strict: ResolvedCaps,
) -> None:
    broken_store = RedisStore(_BrokenRedis())
    gate = BudgetGate(broken_store, env_defaults=env_defaults_strict, fail_open=True)
    decision = await gate.check(BudgetScope(org_id="acme"))
    assert decision.allowed is True
    assert decision.soft_warn is True


@pytest.mark.asyncio
async def test_health_reports_redis_unhealthy(
    env_defaults_strict: ResolvedCaps,
) -> None:
    broken_store = RedisStore(_BrokenRedis())
    gate = BudgetGate(broken_store, env_defaults=env_defaults_strict, fail_open=False)
    health = await gate.health()
    assert health["redis_ok"] is False
    assert health["fail_open"] is False


@pytest.mark.asyncio
async def test_health_reports_redis_ok_with_fakeredis(gate: BudgetGate) -> None:
    health = await gate.health()
    assert health["redis_ok"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Decision contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_is_immutable(gate: BudgetGate, now: datetime) -> None:
    decision = await gate.check(
        BudgetScope(org_id="acme"),
        estimated_tokens=10,
        estimated_cost_usd=0.01,
        now=now,
    )
    assert isinstance(decision, GateDecision)
    with pytest.raises((AttributeError, TypeError)):
        decision.allowed = False  # type: ignore[misc]


@pytest.mark.asyncio
async def test_check_rejects_negative_estimates(gate: BudgetGate) -> None:
    with pytest.raises(ValueError):
        await gate.check(BudgetScope(), estimated_tokens=-1)
    with pytest.raises(ValueError):
        await gate.check(BudgetScope(), estimated_cost_usd=-0.01)


@pytest.mark.asyncio
async def test_check_with_no_cap_set_for_token_field_skips_token_check(
    store: RedisStore,
) -> None:
    """A cap of 0 disables that dimension (e.g. only enforce USD)."""
    env = ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=0,  # disabled
        monthly_tokens=0,  # disabled
        soft_warn_threshold=0.8,
    )
    gate = BudgetGate(store, env_defaults=env, fail_open=False)
    decision = await gate.check(
        BudgetScope(org_id="acme"),
        estimated_tokens=10_000_000_000,  # absurd, but tokens cap is off
        estimated_cost_usd=0.01,
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_set_cap_merges_with_existing(
    gate: BudgetGate, store: RedisStore, now: datetime
) -> None:
    scope = BudgetScope(org_id="acme")
    # Seed an existing cap config directly.
    await store.write_cap(scope, CapConfig(daily_usd=5.0))
    # Add a monthly cap; daily must be preserved.
    await gate.set_cap(scope, monthly_usd=100.0)

    cfg = await store.read_cap(scope)
    assert cfg is not None
    assert cfg.daily_usd == 5.0
    assert cfg.monthly_usd == 100.0
