"""Shared fixtures for the budget-gate test suite."""

from __future__ import annotations

from datetime import datetime, timezone

import fakeredis.aioredis
import pytest
import pytest_asyncio

from madfam_budget_gate import BudgetGate, RedisStore
from madfam_budget_gate.scope import ResolvedCaps


@pytest.fixture
def env_defaults() -> ResolvedCaps:
    """Default caps used by all tests unless overridden."""
    return ResolvedCaps(
        daily_usd=10.0,
        monthly_usd=200.0,
        daily_tokens=1_000_000,
        monthly_tokens=20_000_000,
        soft_warn_threshold=0.8,
    )


@pytest_asyncio.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def store(fake_redis: fakeredis.aioredis.FakeRedis) -> RedisStore:
    return RedisStore(fake_redis)


@pytest_asyncio.fixture
async def gate(store: RedisStore, env_defaults: ResolvedCaps) -> BudgetGate:
    return BudgetGate(store, env_defaults=env_defaults, fail_open=False)


@pytest.fixture
def now() -> datetime:
    """Mid-day UTC timestamp on a deterministic day."""
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
