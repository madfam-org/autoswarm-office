"""Tests for the Redis-backed counter + cap store."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from madfam_budget_gate import RedisStore
from madfam_budget_gate.redis_store import (
    _daily_bucket,
    _monthly_bucket,
    _seconds_until_eod,
    _seconds_until_eom,
)
from madfam_budget_gate.scope import BudgetScope, CapConfig


@pytest.mark.asyncio
async def test_increment_and_read_roundtrip(store: RedisStore, now: datetime) -> None:
    scope = BudgetScope(org_id="acme")
    await store.increment(scope, usd=0.50, tokens=1_000, now=now)
    await store.increment(scope, usd=0.25, tokens=500, now=now)

    usage = await store.read_usage(scope, now=now)
    assert usage["daily_usd"] == pytest.approx(0.75)
    assert usage["daily_tokens"] == pytest.approx(1_500)
    assert usage["monthly_usd"] == pytest.approx(0.75)
    assert usage["monthly_tokens"] == pytest.approx(1_500)


@pytest.mark.asyncio
async def test_increment_rejects_negative_values(store: RedisStore, now: datetime) -> None:
    with pytest.raises(ValueError):
        await store.increment(BudgetScope(), usd=-0.01, tokens=0, now=now)
    with pytest.raises(ValueError):
        await store.increment(BudgetScope(), usd=0.0, tokens=-1, now=now)


@pytest.mark.asyncio
async def test_scope_isolation(store: RedisStore, now: datetime) -> None:
    """Two scopes must keep separate counters."""
    a = BudgetScope(org_id="acme")
    b = BudgetScope(org_id="other")
    await store.increment(a, usd=1.0, tokens=100, now=now)

    a_usage = await store.read_usage(a, now=now)
    b_usage = await store.read_usage(b, now=now)
    assert a_usage["daily_usd"] == pytest.approx(1.0)
    assert b_usage["daily_usd"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_cap_write_read_delete_roundtrip(store: RedisStore) -> None:
    scope = BudgetScope(org_id="acme")
    cfg = CapConfig(daily_usd=5.0, monthly_usd=100.0, daily_tokens=200_000)
    await store.write_cap(scope, cfg)

    read = await store.read_cap(scope)
    assert read == cfg

    deleted = await store.delete_cap(scope)
    assert deleted == 1
    assert await store.read_cap(scope) is None


@pytest.mark.asyncio
async def test_read_cap_returns_none_for_missing(store: RedisStore) -> None:
    assert await store.read_cap(BudgetScope(org_id="ghost")) is None


@pytest.mark.asyncio
async def test_corrupt_cap_payload_returns_none(
    store: RedisStore,
    fake_redis,
) -> None:
    # Corrupt payload should not raise — caller treats it as no-override.
    await fake_redis.set("bg:cap:" + BudgetScope(org_id="zzz").hash_key(), b"not-json")
    assert await store.read_cap(BudgetScope(org_id="zzz")) is None


def test_daily_bucket_format(now: datetime) -> None:
    assert _daily_bucket(now) == "2026-05-04"


def test_monthly_bucket_format(now: datetime) -> None:
    assert _monthly_bucket(now) == "2026-05"


def test_seconds_until_eod_is_positive_and_includes_buffer(now: datetime) -> None:
    secs = _seconds_until_eod(now)
    # 12 hours remaining + 24h buffer = ~36h.
    assert 36 * 3600 - 60 < secs < 37 * 3600


def test_seconds_until_eom_handles_year_rollover() -> None:
    # Mid-December UTC.
    dec = datetime(2026, 12, 15, 12, 0, 0, tzinfo=timezone.utc)
    secs = _seconds_until_eom(dec)
    # 16 days + 12h to Jan 1 + 24h buffer ≈ ~17.5 days.
    assert 16 * 86400 < secs < 18 * 86400


@pytest.mark.asyncio
async def test_end_of_day_rollover_isolates_counters(store: RedisStore) -> None:
    """Counters from yesterday must not leak into today."""
    yesterday = datetime(2026, 5, 3, 23, 0, 0, tzinfo=timezone.utc)
    today = datetime(2026, 5, 4, 1, 0, 0, tzinfo=timezone.utc)
    scope = BudgetScope(org_id="acme")

    await store.increment(scope, usd=5.0, tokens=10_000, now=yesterday)
    today_usage = await store.read_usage(scope, now=today)
    # Different daily bucket → daily counters reset.
    assert today_usage["daily_usd"] == pytest.approx(0.0)
    assert today_usage["daily_tokens"] == pytest.approx(0.0)
    # Same monthly bucket → monthly counters preserved.
    assert today_usage["monthly_usd"] == pytest.approx(5.0)
    assert today_usage["monthly_tokens"] == pytest.approx(10_000)


@pytest.mark.asyncio
async def test_ping_returns_true_on_healthy_redis(store: RedisStore) -> None:
    assert await store.ping() is True
