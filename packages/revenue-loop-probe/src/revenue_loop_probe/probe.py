"""Probe orchestration + shared types.

A probe is a sequence of async ``ProbeStep``s. Each step sees the same
``ProbeContext``, can read/write shared state, and returns a ``StageResult``.
The orchestrator runs them in order, aggregates results, and produces a
``ProbeReport`` that is JSON-serialisable for pushing to logs / Sentry /
Prometheus.

Stages fail forward: by default, a failed stage does NOT stop subsequent
stages. That's deliberate — we want the report to say which of {CRM,
draft, email, webhook, billing, attribution} is broken in one pass, not
"first failure only". Set ``short_circuit=True`` on the probe to change
that.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol

import httpx


class StageStatus(StrEnum):
    """Outcome of a single stage."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    # A stage can no-op and still be 'ok' — e.g. email in dry-run mode.
    DRY_RUN = "dry_run"


@dataclass
class StageResult:
    name: str
    status: StageStatus
    duration_ms: float
    detail: str | None = None
    # Structured facts the stage discovered. Goes straight into the JSON
    # report for downstream consumption (Sentry tags, Prom labels, etc.).
    facts: dict[str, Any] = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status in (StageStatus.PASSED, StageStatus.SKIPPED, StageStatus.DRY_RUN)


@dataclass
class ProbeContext:
    """Shared state threaded through every stage.

    ``correlation_id`` is generated per probe run and should be attached to
    every external call — CRM, Stripe, Dhanam, PhyndCRM — so we can trace
    a probe across the ecosystem.

    ``dry_run=True`` means stages should not perform real side-effects: no
    real email, no real charge, no real credit attribution. Stages that
    can't honour dry-run must skip themselves.
    """

    dry_run: bool = True
    correlation_id: str = field(default_factory=lambda: f"probe-{uuid.uuid4().hex[:12]}")
    started_at: float = field(default_factory=time.time)
    env: dict[str, str] = field(default_factory=dict)
    http: httpx.AsyncClient | None = None
    # Stage-to-stage scratch. For example, stage 1 (CRM) stores the
    # synthetic lead_id here for stage 3 (email send) to reference.
    state: dict[str, Any] = field(default_factory=dict)


class ProbeStep(Protocol):
    """Contract every probe stage must satisfy."""

    name: str

    async def run(self, ctx: ProbeContext) -> StageResult: ...


@dataclass
class ProbeReport:
    correlation_id: str
    dry_run: bool
    started_at: float
    finished_at: float
    stages: list[StageResult]

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at) * 1000.0

    @property
    def ok(self) -> bool:
        return all(s.is_ok() for s in self.stages)

    @property
    def fail_count(self) -> int:
        return sum(1 for s in self.stages if s.status is StageStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 2),
            "ok": self.ok,
            "fail_count": self.fail_count,
            "stages": [
                {
                    "name": s.name,
                    "status": s.status.value,
                    "duration_ms": round(s.duration_ms, 2),
                    "detail": s.detail,
                    "facts": s.facts,
                }
                for s in self.stages
            ],
        }


class RevenueLoopProbe:
    """Runs a configured sequence of probe stages and produces a report."""

    def __init__(
        self,
        steps: list[ProbeStep],
        *,
        short_circuit: bool = False,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        if not steps:
            raise ValueError("RevenueLoopProbe requires at least one step")
        self._steps = steps
        self._short_circuit = short_circuit
        self._http_factory = http_factory or (
            lambda: httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        )

    async def run(self, ctx: ProbeContext | None = None) -> ProbeReport:
        ctx = ctx or ProbeContext()
        owns_http = False
        if ctx.http is None:
            ctx.http = self._http_factory()
            owns_http = True

        results: list[StageResult] = []
        try:
            for step in self._steps:
                t0 = time.perf_counter()
                try:
                    res = await step.run(ctx)
                except Exception as exc:  # noqa: BLE001 — probe must survive step bugs
                    res = StageResult(
                        name=step.name,
                        status=StageStatus.FAILED,
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        detail=f"step raised {type(exc).__name__}: {exc}",
                    )
                results.append(res)
                if self._short_circuit and res.status is StageStatus.FAILED:
                    break
        finally:
            if owns_http and ctx.http is not None:
                await ctx.http.aclose()

        return ProbeReport(
            correlation_id=ctx.correlation_id,
            dry_run=ctx.dry_run,
            started_at=ctx.started_at,
            finished_at=time.time(),
            stages=results,
        )


# Helper for stage authors: skip when a required env var is missing.
def skip_if_missing(
    *env_keys: str,
) -> Callable[
    [Callable[[ProbeContext], Awaitable[StageResult]]],
    Callable[[ProbeContext], Awaitable[StageResult]],
]:
    def decorator(fn):
        async def wrapper(ctx: ProbeContext) -> StageResult:
            missing = [k for k in env_keys if not ctx.env.get(k)]
            if missing:
                return StageResult(
                    name=getattr(fn, "__name__", "anon"),
                    status=StageStatus.SKIPPED,
                    duration_ms=0.0,
                    detail=f"missing env: {', '.join(missing)}",
                )
            return await fn(ctx)

        return wrapper

    return decorator
