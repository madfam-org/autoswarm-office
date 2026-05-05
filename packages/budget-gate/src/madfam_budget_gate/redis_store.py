"""Redis-backed storage for budget counters and cap overrides.

Key layout
==========

Counters (incremented atomically on every ``record()``):

    bg:<scope_hash>:daily:<YYYY-MM-DD>:usd      → INCRBYFLOAT
    bg:<scope_hash>:daily:<YYYY-MM-DD>:tokens   → INCRBY
    bg:<scope_hash>:monthly:<YYYY-MM>:usd       → INCRBYFLOAT
    bg:<scope_hash>:monthly:<YYYY-MM>:tokens    → INCRBY

Each daily key carries a TTL of 48h (covers the next-day rollover with
slack).  Each monthly key TTLs at end-of-month + 24h.

Cap overrides (set via :meth:`BudgetGate.set_cap`):

    bg:cap:<scope_hash>  → JSON-encoded :class:`CapConfig`

The store layer is a thin wrapper on top of ``redis.asyncio`` — it
**never** decides whether to allow or deny; that lives in
:mod:`madfam_budget_gate.gate`.
"""

from __future__ import annotations

import calendar
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Protocol

from .scope import BudgetScope, CapConfig

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Time helpers (kept as module-level functions so tests can monkey-patch a
# fixed clock without touching the store internals).
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _daily_bucket(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _monthly_bucket(now: datetime) -> str:
    return now.strftime("%Y-%m")


def _seconds_until_eod(now: datetime) -> int:
    """Return seconds until the start of the *next* UTC day, plus 24h slack."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_start = datetime.fromtimestamp(today_start.timestamp() + 86400, tz=timezone.utc)
    # 24h buffer so a clock-drifting reader still sees yesterday's bucket.
    return int((next_day_start - now).total_seconds()) + 86400


def _seconds_until_eom(now: datetime) -> int:
    """Return seconds until 24h after the start of the *next* UTC month."""
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    # Sanity: ``last_day`` is informational; we use the explicit start-of-next-month.
    _ = last_day
    return int((next_month_start - now).total_seconds()) + 86400


# ─────────────────────────────────────────────────────────────────────────────
# Redis client protocol — keeps the store unit-testable with fakeredis or any
# duck-typed client (we only call a tiny slice of the surface).
# ─────────────────────────────────────────────────────────────────────────────


class AsyncRedisLike(Protocol):
    async def incrbyfloat(self, name: str, amount: float) -> float: ...

    async def incrby(self, name: str, amount: int) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...

    async def get(self, name: str) -> bytes | str | None: ...

    async def set(self, name: str, value: str) -> bool: ...

    async def delete(self, *names: str) -> int: ...

    async def mget(self, keys: list[str]) -> list[bytes | str | None]: ...

    async def ping(self) -> bool: ...


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────


class RedisStore:
    """Thin Redis wrapper for budget counters + cap overrides.

    The constructor accepts any object that satisfies
    :class:`AsyncRedisLike` — in production this is
    ``redis.asyncio.Redis``; in tests, ``fakeredis.aioredis.FakeRedis``
    (declared with a wider type annotation than our protocol, so we
    accept ``Any`` and let runtime duck-typing do the rest).
    """

    PREFIX = "bg"
    CAP_PREFIX = "bg:cap"

    def __init__(self, redis: Any) -> None:
        self._redis: AsyncRedisLike = redis

    # -- key construction ----------------------------------------------------

    @classmethod
    def daily_key(cls, scope: BudgetScope, *, kind: str, day: str) -> str:
        if kind not in ("usd", "tokens"):
            raise ValueError(f"unknown counter kind: {kind!r}")
        return f"{cls.PREFIX}:{scope.hash_key()}:daily:{day}:{kind}"

    @classmethod
    def monthly_key(cls, scope: BudgetScope, *, kind: str, month: str) -> str:
        if kind not in ("usd", "tokens"):
            raise ValueError(f"unknown counter kind: {kind!r}")
        return f"{cls.PREFIX}:{scope.hash_key()}:monthly:{month}:{kind}"

    @classmethod
    def cap_key(cls, scope: BudgetScope) -> str:
        return f"{cls.CAP_PREFIX}:{scope.hash_key()}"

    # -- counter operations --------------------------------------------------

    async def increment(
        self,
        scope: BudgetScope,
        *,
        usd: float,
        tokens: int,
        now: datetime | None = None,
    ) -> None:
        """Atomically bump daily + monthly USD and token counters for ``scope``."""
        if usd < 0 or tokens < 0:
            raise ValueError("usd and tokens must be non-negative")
        now = now or _now_utc()
        day = _daily_bucket(now)
        month = _monthly_bucket(now)

        d_usd = self.daily_key(scope, kind="usd", day=day)
        d_tok = self.daily_key(scope, kind="tokens", day=day)
        m_usd = self.monthly_key(scope, kind="usd", month=month)
        m_tok = self.monthly_key(scope, kind="tokens", month=month)

        # Each operation is atomic; we don't pipeline because fakeredis's
        # pipeline implementation differs subtly from real Redis on edge cases
        # and the cost (4 round-trips) is tolerable for the gate's call rate.
        if usd > 0:
            await self._redis.incrbyfloat(d_usd, usd)
            await self._redis.incrbyfloat(m_usd, usd)
        if tokens > 0:
            await self._redis.incrby(d_tok, tokens)
            await self._redis.incrby(m_tok, tokens)

        # Set/refresh TTLs.  Idempotent — Redis EXPIRE on an existing key with
        # the same value is harmless.
        eod = _seconds_until_eod(now)
        eom = _seconds_until_eom(now)
        await self._redis.expire(d_usd, eod)
        await self._redis.expire(d_tok, eod)
        await self._redis.expire(m_usd, eom)
        await self._redis.expire(m_tok, eom)

    async def read_usage(
        self,
        scope: BudgetScope,
        *,
        now: datetime | None = None,
    ) -> dict[str, float]:
        """Return current daily + monthly USD and token usage for ``scope``."""
        now = now or _now_utc()
        day = _daily_bucket(now)
        month = _monthly_bucket(now)

        keys = [
            self.daily_key(scope, kind="usd", day=day),
            self.daily_key(scope, kind="tokens", day=day),
            self.monthly_key(scope, kind="usd", month=month),
            self.monthly_key(scope, kind="tokens", month=month),
        ]
        raw = await self._redis.mget(keys)
        d_usd, d_tok, m_usd, m_tok = (
            _decode_float(raw[0]),
            _decode_int(raw[1]),
            _decode_float(raw[2]),
            _decode_int(raw[3]),
        )
        return {
            "daily_usd": d_usd,
            "daily_tokens": float(d_tok),
            "monthly_usd": m_usd,
            "monthly_tokens": float(m_tok),
        }

    # -- cap override operations --------------------------------------------

    async def write_cap(self, scope: BudgetScope, config: CapConfig) -> None:
        """Persist a per-scope cap override (no TTL — caps are long-lived)."""
        await self._redis.set(self.cap_key(scope), json.dumps(asdict(config)))

    async def read_cap(self, scope: BudgetScope) -> CapConfig | None:
        raw = await self._redis.get(self.cap_key(scope))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("budget-gate: corrupt cap config at %s", self.cap_key(scope))
            return None
        return CapConfig(**data)

    async def delete_cap(self, scope: BudgetScope) -> int:
        return await self._redis.delete(self.cap_key(scope))

    # -- health --------------------------------------------------------------

    async def ping(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception:
            return False


def _decode_float(raw: bytes | str | None) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _decode_int(raw: bytes | str | None) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0
