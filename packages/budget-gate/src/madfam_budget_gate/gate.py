"""Core budget gate.

Bedrock safety mechanism for autonomous LLM campaigns.  Tracks token
spend and USD spend per scope (org / agent / global), enforces daily
and monthly caps, and returns ALLOW / DENY / SOFT-WARN before each
LLM call.

Lifecycle (typical caller)::

    gate = BudgetGate.from_env()
    decision = await gate.check(scope, estimated_tokens=2000, estimated_cost_usd=0.04)
    if not decision.allowed:
        raise BudgetExhausted(decision.reason, decision.retry_after_seconds)
    response = await provider.complete(...)
    await gate.record(scope, actual_tokens=..., actual_cost_usd=..., provider=..., model=...)

Failure mode policy
-------------------
If Redis is unreachable the gate **fails CLOSED** (denies every call)
by default — silently leaking spend during a Redis outage is a worse
business risk than an LLM-call outage.  Operators who run autonomous
campaigns where uptime trumps cost-risk can flip
``BUDGET_GATE_FAIL_OPEN=true`` to invert this behaviour.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .cost_model import estimate_cost
from .redis_store import RedisStore, _now_utc
from .scope import BudgetScope, CapConfig, ResolvedCaps, resolve_caps

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors / decisions
# ─────────────────────────────────────────────────────────────────────────────


class BudgetExhausted(RuntimeError):
    """Raised by callers when the gate denies a request and they want to surface."""

    def __init__(self, reason: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Outcome of a :meth:`BudgetGate.check` call.

    Attributes
    ----------
    allowed : bool
        ``True`` ⇒ the caller may proceed with the LLM call.
    reason : str
        Human-readable explanation.  Always populated; for ALLOW it
        describes the headroom remaining, for DENY it describes which
        cap was hit, for SOFT-WARN it identifies the threshold crossed.
    soft_warn : bool
        ``True`` when the call is allowed but spend has crossed the
        soft-warn threshold (default 80% of any cap).  Triggers a
        structured log warning.
    retry_after_seconds : int | None
        For DENY decisions: seconds until the relevant cap window
        rolls over.  ``None`` for ALLOW.
    scope : BudgetScope
        The scope that was checked (echoed for caller convenience).
    snapshot : dict[str, float]
        The current spend snapshot (daily + monthly, USD + tokens) at
        check time.  Useful for callers that want to log spend
        alongside the decision.
    """

    allowed: bool
    reason: str
    soft_warn: bool = False
    retry_after_seconds: int | None = None
    scope: BudgetScope = field(default_factory=BudgetScope)
    snapshot: dict[str, float] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Env config — defaults match conservative org-wide caps so a fresh deploy
# never wakes up unbounded.
# ─────────────────────────────────────────────────────────────────────────────

_ENV_REDIS_URL = "BUDGET_GATE_REDIS_URL"
_ENV_FALLBACK_REDIS_URL = "REDIS_URL"
_ENV_DEFAULT_DAILY_USD = "BUDGET_GATE_DEFAULT_DAILY_USD"
_ENV_DEFAULT_MONTHLY_USD = "BUDGET_GATE_DEFAULT_MONTHLY_USD"
_ENV_DEFAULT_DAILY_TOKENS = "BUDGET_GATE_DEFAULT_DAILY_TOKENS"
_ENV_DEFAULT_MONTHLY_TOKENS = "BUDGET_GATE_DEFAULT_MONTHLY_TOKENS"
_ENV_SOFT_WARN = "BUDGET_GATE_SOFT_WARN_THRESHOLD"
_ENV_FAIL_OPEN = "BUDGET_GATE_FAIL_OPEN"


def _env_default_caps() -> ResolvedCaps:
    """Read default caps from env.  Conservative defaults if unset."""
    return ResolvedCaps(
        daily_usd=float(os.environ.get(_ENV_DEFAULT_DAILY_USD, "50.0")),
        monthly_usd=float(os.environ.get(_ENV_DEFAULT_MONTHLY_USD, "1000.0")),
        daily_tokens=int(os.environ.get(_ENV_DEFAULT_DAILY_TOKENS, "5000000")),
        monthly_tokens=int(os.environ.get(_ENV_DEFAULT_MONTHLY_TOKENS, "100000000")),
        soft_warn_threshold=float(os.environ.get(_ENV_SOFT_WARN, "0.8")),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BudgetGate
# ─────────────────────────────────────────────────────────────────────────────


class BudgetGate:
    """Public facade for the budget-gate package."""

    def __init__(
        self,
        store: RedisStore,
        *,
        env_defaults: ResolvedCaps | None = None,
        fail_open: bool = False,
    ) -> None:
        self._store = store
        self._env_defaults = env_defaults or _env_default_caps()
        self._fail_open = fail_open
        # In-memory cache of cap overrides — Redis is the source of truth, but
        # we cache reads in-process for the duration of a single check chain
        # to avoid hammering Redis with N reads (one per scope in the chain).
        # The cache is *per-method-call*; not stored on self.
        self._cap_cache: dict[BudgetScope, CapConfig | None] | None = None

    # -- construction --------------------------------------------------------

    @classmethod
    def from_env(cls) -> BudgetGate:
        """Build a :class:`BudgetGate` from environment variables.

        Reads ``BUDGET_GATE_REDIS_URL`` (falls back to ``REDIS_URL``)
        and the ``BUDGET_GATE_DEFAULT_*`` cap envs.  Honours
        ``BUDGET_GATE_FAIL_OPEN`` (truthy → fail-open).
        """
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:  # pragma: no cover — redis is a hard dep
            raise RuntimeError("redis package is required for BudgetGate.from_env") from exc

        url = os.environ.get(_ENV_REDIS_URL) or os.environ.get(
            _ENV_FALLBACK_REDIS_URL, "redis://localhost:6379"
        )
        client = aioredis.from_url(url, encoding="utf-8", decode_responses=False)
        store = RedisStore(client)
        fail_open = _truthy(os.environ.get(_ENV_FAIL_OPEN, ""))
        return cls(store, env_defaults=_env_default_caps(), fail_open=fail_open)

    # -- public API ---------------------------------------------------------

    async def check(
        self,
        scope: BudgetScope,
        *,
        estimated_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        now: datetime | None = None,
    ) -> GateDecision:
        """Pre-call gate.  Returns ALLOW / DENY / SOFT-WARN."""
        if estimated_tokens < 0 or estimated_cost_usd < 0:
            raise ValueError("estimated_tokens and estimated_cost_usd must be non-negative")
        now = now or _now_utc()

        try:
            self._cap_cache = {}
            return await self._evaluate(
                scope=scope,
                estimated_tokens=estimated_tokens,
                estimated_cost_usd=estimated_cost_usd,
                now=now,
            )
        except _RedisDown as exc:
            return self._fail_decision(scope, exc)
        finally:
            self._cap_cache = None

    async def record(
        self,
        scope: BudgetScope,
        *,
        actual_tokens: int = 0,
        actual_cost_usd: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        now: datetime | None = None,
    ) -> None:
        """Post-call recording.

        Bumps the daily + monthly counters for ``scope`` and every
        parent scope in the chain (so org-level caps see all agent
        spend automatically).

        ``actual_cost_usd`` is preferred when the caller can compute
        it from a billing API.  When omitted, the gate estimates from
        ``provider`` + ``model`` + token counts.
        """
        if actual_tokens < 0:
            raise ValueError("actual_tokens must be non-negative")

        # If caller supplied input/output split, use that for the cost
        # estimate; else fall back to total tokens split as 30/70 input/output
        # (typical for chat completions).
        if actual_cost_usd is None:
            i_tok = input_tokens if input_tokens is not None else int(actual_tokens * 0.3)
            o_tok = (
                output_tokens
                if output_tokens is not None
                else max(0, actual_tokens - i_tok)
            )
            actual_cost_usd = estimate_cost(provider, model, i_tok, o_tok)

        if actual_cost_usd < 0:
            raise ValueError("actual_cost_usd must be non-negative")

        now = now or _now_utc()
        # Increment the chain (specific → parent → global) so every level
        # sees the spend.
        try:
            for s in scope.chain():
                await self._store.increment(
                    s, usd=actual_cost_usd, tokens=actual_tokens, now=now
                )
        except Exception as exc:
            # Recording failures are non-fatal — we already let the call
            # through.  Log loudly so ops sees the drift.
            logger.error(
                "budget-gate: failed to record usage for scope=%r tokens=%d usd=%.6f: %s",
                scope,
                actual_tokens,
                actual_cost_usd,
                exc,
                exc_info=True,
            )

    async def status(
        self,
        scope: BudgetScope,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return current spend + remaining headroom for ``scope``.

        Output shape::

            {
              "scope": {"org_id": ..., "agent_id": ..., "tag": ...},
              "daily":  {"used_usd", "cap_usd", "remaining_usd",
                         "used_tokens", "cap_tokens", "remaining_tokens"},
              "monthly": {... same keys ...},
              "soft_warn_threshold": 0.8,
            }
        """
        now = now or _now_utc()
        self._cap_cache = {}
        try:
            caps = await self._resolve_caps(scope)
        finally:
            self._cap_cache = None

        try:
            usage = await self._store.read_usage(scope, now=now)
        except Exception as exc:
            logger.error("budget-gate: status read failed: %s", exc)
            usage = {"daily_usd": 0.0, "daily_tokens": 0.0, "monthly_usd": 0.0, "monthly_tokens": 0.0}

        return {
            "scope": {"org_id": scope.org_id, "agent_id": scope.agent_id, "tag": scope.tag},
            "daily": {
                "used_usd": round(usage["daily_usd"], 6),
                "cap_usd": caps.daily_usd,
                "remaining_usd": round(max(0.0, caps.daily_usd - usage["daily_usd"]), 6),
                "used_tokens": int(usage["daily_tokens"]),
                "cap_tokens": caps.daily_tokens,
                "remaining_tokens": max(0, caps.daily_tokens - int(usage["daily_tokens"])),
            },
            "monthly": {
                "used_usd": round(usage["monthly_usd"], 6),
                "cap_usd": caps.monthly_usd,
                "remaining_usd": round(max(0.0, caps.monthly_usd - usage["monthly_usd"]), 6),
                "used_tokens": int(usage["monthly_tokens"]),
                "cap_tokens": caps.monthly_tokens,
                "remaining_tokens": max(0, caps.monthly_tokens - int(usage["monthly_tokens"])),
            },
            "soft_warn_threshold": caps.soft_warn_threshold,
        }

    async def set_cap(
        self,
        scope: BudgetScope,
        *,
        daily_usd: float | None = None,
        monthly_usd: float | None = None,
        daily_tokens: int | None = None,
        monthly_tokens: int | None = None,
        soft_warn_threshold: float | None = None,
    ) -> CapConfig:
        """Persist a per-scope cap override.

        Any field left as ``None`` falls through to a less-specific
        scope at resolution time.  Returns the stored ``CapConfig``.
        """
        existing = await self._store.read_cap(scope) or CapConfig()
        merged = CapConfig(
            daily_usd=daily_usd if daily_usd is not None else existing.daily_usd,
            monthly_usd=monthly_usd if monthly_usd is not None else existing.monthly_usd,
            daily_tokens=daily_tokens if daily_tokens is not None else existing.daily_tokens,
            monthly_tokens=monthly_tokens
            if monthly_tokens is not None
            else existing.monthly_tokens,
            soft_warn_threshold=soft_warn_threshold
            if soft_warn_threshold is not None
            else existing.soft_warn_threshold,
        )
        await self._store.write_cap(scope, merged)
        return merged

    async def clear_cap(self, scope: BudgetScope) -> None:
        """Remove a per-scope cap override."""
        await self._store.delete_cap(scope)

    async def health(self) -> dict[str, Any]:
        """Return Redis reachability + fail-mode posture."""
        ok = await self._store.ping()
        return {
            "redis_ok": ok,
            "fail_open": self._fail_open,
            "default_caps": {
                "daily_usd": self._env_defaults.daily_usd,
                "monthly_usd": self._env_defaults.monthly_usd,
                "daily_tokens": self._env_defaults.daily_tokens,
                "monthly_tokens": self._env_defaults.monthly_tokens,
                "soft_warn_threshold": self._env_defaults.soft_warn_threshold,
            },
        }

    # -- internals -----------------------------------------------------------

    async def _evaluate(
        self,
        *,
        scope: BudgetScope,
        estimated_tokens: int,
        estimated_cost_usd: float,
        now: datetime,
    ) -> GateDecision:
        # Read usage for the scope itself; caps for the scope walk the chain.
        try:
            usage = await self._store.read_usage(scope, now=now)
        except Exception as exc:
            raise _RedisDown(f"read_usage failed: {exc}") from exc

        caps = await self._resolve_caps(scope)

        # Project the post-call counters to detect cap exhaustion *before* the
        # caller burns the budget.
        projected_daily_usd = usage["daily_usd"] + estimated_cost_usd
        projected_daily_tokens = usage["daily_tokens"] + estimated_tokens
        projected_monthly_usd = usage["monthly_usd"] + estimated_cost_usd
        projected_monthly_tokens = usage["monthly_tokens"] + estimated_tokens

        # Hard cap checks (deny)
        from .redis_store import _seconds_until_eod, _seconds_until_eom

        if caps.daily_usd > 0 and projected_daily_usd > caps.daily_usd:
            return GateDecision(
                allowed=False,
                reason=(
                    f"daily USD cap exhausted: projected ${projected_daily_usd:.4f} > "
                    f"cap ${caps.daily_usd:.2f}"
                ),
                retry_after_seconds=_seconds_until_eod(now),
                scope=scope,
                snapshot=usage,
            )
        if caps.daily_tokens > 0 and projected_daily_tokens > caps.daily_tokens:
            return GateDecision(
                allowed=False,
                reason=(
                    f"daily token cap exhausted: projected "
                    f"{int(projected_daily_tokens):,} > cap {caps.daily_tokens:,}"
                ),
                retry_after_seconds=_seconds_until_eod(now),
                scope=scope,
                snapshot=usage,
            )
        if caps.monthly_usd > 0 and projected_monthly_usd > caps.monthly_usd:
            return GateDecision(
                allowed=False,
                reason=(
                    f"monthly USD cap exhausted: projected ${projected_monthly_usd:.4f} > "
                    f"cap ${caps.monthly_usd:.2f}"
                ),
                retry_after_seconds=_seconds_until_eom(now),
                scope=scope,
                snapshot=usage,
            )
        if caps.monthly_tokens > 0 and projected_monthly_tokens > caps.monthly_tokens:
            return GateDecision(
                allowed=False,
                reason=(
                    f"monthly token cap exhausted: projected "
                    f"{int(projected_monthly_tokens):,} > cap {caps.monthly_tokens:,}"
                ),
                retry_after_seconds=_seconds_until_eom(now),
                scope=scope,
                snapshot=usage,
            )

        # Soft-warn detection — flag at the highest projected utilisation across
        # all four cap types so a single warn fires per check.
        threshold = caps.soft_warn_threshold
        soft_warn = False
        warn_reason: str | None = None

        candidates: list[tuple[str, float, float]] = [
            ("daily USD", projected_daily_usd, caps.daily_usd),
            ("daily tokens", float(projected_daily_tokens), float(caps.daily_tokens)),
            ("monthly USD", projected_monthly_usd, caps.monthly_usd),
            ("monthly tokens", float(projected_monthly_tokens), float(caps.monthly_tokens)),
        ]
        for label, projected, cap_val in candidates:
            if cap_val <= 0:
                continue
            if projected >= cap_val * threshold:
                soft_warn = True
                warn_reason = (
                    f"{label} usage {projected:.4f}/{cap_val:.4f} "
                    f"({(projected / cap_val) * 100:.1f}%) crossed soft-warn "
                    f"threshold {int(threshold * 100)}%"
                )
                logger.warning(
                    "budget-gate.soft_warn scope=%s label=%s projected=%.4f cap=%.4f pct=%.1f",
                    _scope_repr(scope),
                    label,
                    projected,
                    cap_val,
                    (projected / cap_val) * 100,
                )
                break

        return GateDecision(
            allowed=True,
            reason=warn_reason or "within budget",
            soft_warn=soft_warn,
            scope=scope,
            snapshot=usage,
        )

    async def _resolve_caps(self, scope: BudgetScope) -> ResolvedCaps:
        """Resolve effective caps walking the parent chain.

        Reads each scope's override from Redis once, caching the
        result for the duration of the current ``check()``/``status()``
        call.
        """
        overrides: dict[BudgetScope, CapConfig] = {}
        for s in scope.chain():
            cfg = await self._read_cap_cached(s)
            if cfg is not None:
                overrides[s] = cfg
        return resolve_caps(scope, overrides=overrides, env_defaults=self._env_defaults)

    async def _read_cap_cached(self, scope: BudgetScope) -> CapConfig | None:
        if self._cap_cache is None:
            return await self._safe_read_cap(scope)
        if scope not in self._cap_cache:
            self._cap_cache[scope] = await self._safe_read_cap(scope)
        return self._cap_cache[scope]

    async def _safe_read_cap(self, scope: BudgetScope) -> CapConfig | None:
        try:
            return await self._store.read_cap(scope)
        except Exception as exc:
            raise _RedisDown(f"read_cap failed: {exc}") from exc

    def _fail_decision(self, scope: BudgetScope, exc: Exception) -> GateDecision:
        if self._fail_open:
            logger.error(
                "budget-gate: Redis unreachable, FAILING OPEN (scope=%s): %s",
                _scope_repr(scope),
                exc,
            )
            return GateDecision(
                allowed=True,
                reason=f"Redis unreachable, fail-open: {exc}",
                soft_warn=True,
                scope=scope,
            )
        logger.error(
            "budget-gate: Redis unreachable, FAILING CLOSED (scope=%s): %s",
            _scope_repr(scope),
            exc,
        )
        return GateDecision(
            allowed=False,
            reason=f"Redis unreachable, gate failing closed: {exc}",
            scope=scope,
        )


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────


class _RedisDown(RuntimeError):
    """Internal sentinel — raised inside ``_evaluate`` so ``check`` can decide
    fail-closed vs fail-open without a try/except spaghetti at call sites."""


def _scope_repr(scope: BudgetScope) -> str:
    if scope.is_global:
        return "global"
    parts = []
    if scope.org_id:
        parts.append(f"org={scope.org_id}")
    if scope.agent_id:
        parts.append(f"agent={scope.agent_id}")
    if scope.tag:
        parts.append(f"tag={scope.tag}")
    return ",".join(parts)


def _truthy(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes", "y", "on")
