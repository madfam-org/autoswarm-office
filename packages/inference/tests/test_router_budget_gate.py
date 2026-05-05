"""Tests for the ModelRouter ↔ madfam-budget-gate integration.

The integration is opt-in via the ``BUDGET_GATE_ENABLED`` env var.
These tests verify three behaviours:

1. Default OFF — gate not consulted when env flag unset.
2. Pass-through — gate ALLOWs and the call proceeds + records usage.
3. Hard-deny — gate raises ``BudgetExhausted``, no provider call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from madfam_budget_gate import BudgetExhausted, BudgetGate, BudgetScope, RedisStore
from madfam_budget_gate.scope import ResolvedCaps
from madfam_inference.router import ModelRouter
from madfam_inference.types import InferenceRequest, InferenceResponse, RoutingPolicy, Sensitivity


def _make_request() -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "hi"}],
        policy=RoutingPolicy(sensitivity=Sensitivity.PUBLIC, max_tokens=500),
    )


def _make_provider(name: str = "anthropic") -> MagicMock:
    provider = MagicMock()
    provider.supports_vision = False
    provider.complete = AsyncMock(
        return_value=InferenceResponse(
            content="hello back",
            model="claude-haiku-4-5",
            provider=name,
            usage={"input_tokens": 50, "output_tokens": 100},
        )
    )
    return provider


@pytest.fixture
def env_defaults() -> ResolvedCaps:
    return ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )


@pytest.fixture
async def gate(env_defaults: ResolvedCaps):
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    store = RedisStore(client)
    yield BudgetGate(store, env_defaults=env_defaults, fail_open=False)
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_skips_gate_when_env_flag_unset(monkeypatch) -> None:
    """Default OFF: gate is not consulted, provider is called normally."""
    monkeypatch.delenv("BUDGET_GATE_ENABLED", raising=False)
    provider = _make_provider()
    router = ModelRouter(providers={"anthropic": provider})
    response = await router.complete(_make_request())
    assert response.content == "hello back"
    assert provider.complete.await_count == 1


@pytest.mark.asyncio
async def test_complete_with_gate_records_usage_after_success(
    gate: BudgetGate, monkeypatch
) -> None:
    """When gate is enabled, an allowed call records usage post-response."""
    monkeypatch.setenv("BUDGET_GATE_ENABLED", "true")
    provider = _make_provider()
    router = ModelRouter(providers={"anthropic": provider}, budget_gate=gate)

    response = await router.complete(_make_request())
    assert response.content == "hello back"

    # Global scope should now show 150 tokens spent (50 input + 100 output).
    status = await gate.status(BudgetScope())
    assert status["daily"]["used_tokens"] == 150
    assert status["daily"]["used_usd"] > 0


@pytest.mark.asyncio
async def test_complete_with_gate_raises_when_budget_exhausted(
    gate: BudgetGate, monkeypatch
) -> None:
    """A pre-call DENY raises BudgetExhausted; provider is never called."""
    monkeypatch.setenv("BUDGET_GATE_ENABLED", "true")
    # Pin a tight daily token cap and pre-spend up to it so the next
    # call's projection exceeds the cap regardless of cost estimate.
    await gate.set_cap(BudgetScope(), daily_tokens=100)
    await gate.record(BudgetScope(), actual_tokens=99, actual_cost_usd=0.0)

    provider = _make_provider()
    router = ModelRouter(providers={"anthropic": provider}, budget_gate=gate)

    # max_tokens=500 ≫ remaining 1 → projection exceeds cap → DENY.
    with pytest.raises(BudgetExhausted):
        await router.complete(_make_request())
    assert provider.complete.await_count == 0


@pytest.mark.asyncio
async def test_complete_with_gate_propagates_to_org_scope(
    gate: BudgetGate, monkeypatch
) -> None:
    """When BUDGET_GATE_DEFAULT_ORG_ID is set, spend records against that org."""
    monkeypatch.setenv("BUDGET_GATE_ENABLED", "true")
    monkeypatch.setenv("BUDGET_GATE_DEFAULT_ORG_ID", "acme")

    provider = _make_provider()
    router = ModelRouter(providers={"anthropic": provider}, budget_gate=gate)
    await router.complete(_make_request())

    org_status = await gate.status(BudgetScope(org_id="acme"))
    global_status = await gate.status(BudgetScope())
    assert org_status["daily"]["used_tokens"] == 150
    # Global also sees the spend (record() walks the chain).
    assert global_status["daily"]["used_tokens"] == 150
