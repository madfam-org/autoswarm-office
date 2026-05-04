"""Skill-performance tools — feed the Thompson bandit + expose metrics.

Phase 4 of the SELVA_TOOL_COVERAGE_PLAN. The orchestrator already runs a
Thompson Sampling bandit over agents + skills for selection decisions
(see ``packages/orchestrator/selva_orchestrator/bandit.py``). Today the
bandit is fed by the worker task loop; there is no way for a skill that
just completed to voluntarily report its outcome so the bandit can
learn faster.

These tools close that gap by:

1. ``skill_record_outcome`` — posts an outcome (success / partial /
   failure) + duration into a persisted outcomes log AND updates the
   live ``ThompsonBandit`` for the skill arm. Reward mapping mirrors the
   worker: success=1.0, partial=0.5, failure=0.0. Persistence goes to
   ``SKILL_OUTCOMES_PATH`` (default ``/tmp/selva-skill-outcomes.jsonl``)
   so metrics survive restarts even without a DB round-trip.

2. ``skill_get_metrics`` — reads back the outcomes log for a skill over
   a time window and computes success_rate, avg_duration_ms, p95 latency,
   and outcome counts. Pure read; never touches the bandit.

Both tools return structured errors instead of raising. Missing bandit
persist file is treated as 'no signal yet' rather than a failure —
ThompsonBandit's default uniform prior is the correct initial state.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


DEFAULT_OUTCOMES_PATH = "/tmp/selva-skill-outcomes.jsonl"
DEFAULT_BANDIT_PATH = "/tmp/autoswarm-bandit.json"


def _outcomes_path() -> Path:
    return Path(os.environ.get("SKILL_OUTCOMES_PATH", DEFAULT_OUTCOMES_PATH))


def _bandit_path() -> str:
    return os.environ.get("BANDIT_PERSIST_PATH", DEFAULT_BANDIT_PATH)


def _reward(outcome: str) -> float:
    return {"success": 1.0, "partial": 0.5, "failure": 0.0}.get(outcome, 0.0)


def _load_outcomes(skill_id: str, since_ts: float) -> list[dict[str, Any]]:
    path = _outcomes_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("skill_id") != skill_id:
                    continue
                if float(record.get("recorded_at", 0)) < since_ts:
                    continue
                out.append(record)
    except OSError as e:
        logger.warning("could not read outcomes log at %s: %s", path, e)
    return out


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    # Nearest-rank method — good enough for ops dashboards.
    idx = int(round(q * (len(s) - 1)))
    return float(s[idx])


_PERIOD_SECONDS: dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}


class SkillRecordOutcomeTool(BaseTool):
    """Record a skill's task outcome and feed it to the Thompson bandit."""

    name = "skill_record_outcome"
    description = (
        "Record the outcome of a skill's task execution. Appends to the "
        "persisted outcomes log AND updates the ``ThompsonBandit`` arm "
        "for this skill_id so selection improves over time. Outcome "
        "mapping: success=reward 1.0, partial=0.5, failure=0.0. Tools "
        "that wrap the skill (e.g. the puppeteer graph feedback node) "
        "should call this as soon as the outcome is known."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "task_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failure"],
                },
                "duration_ms": {"type": "integer", "minimum": 0},
                "metadata": {"type": "object"},
            },
            "required": ["skill_id", "task_id", "outcome"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            skill_id = str(kwargs["skill_id"])
            task_id = str(kwargs["task_id"])
            outcome = str(kwargs["outcome"]).lower()
            duration_ms = int(kwargs.get("duration_ms") or 0)
            metadata = dict(kwargs.get("metadata") or {})
            if outcome not in ("success", "partial", "failure"):
                return ToolResult(
                    success=False,
                    error=f"invalid outcome: {outcome!r}",
                )
            reward = _reward(outcome)
            record = {
                "skill_id": skill_id,
                "task_id": task_id,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "reward": reward,
                "recorded_at": time.time(),
                "metadata": metadata,
            }
            # Append to outcomes log (fire-and-return on any write error
            # so bandit update still happens; the bandit has its own
            # durable store).
            log_written = True
            try:
                path = _outcomes_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("could not append outcome log: %s", e)
                log_written = False
            # Bandit update — lazy import to keep this module usable even
            # when selva_orchestrator isn't installed (e.g. in a tool-only
            # deployment).
            bandit_updated = False
            try:
                from selva_orchestrator.bandit import ThompsonBandit

                bandit = ThompsonBandit(persist_path=_bandit_path())
                bandit.update(skill_id, reward)
                bandit_updated = True
            except ImportError:
                logger.debug("selva_orchestrator not installed; skipping bandit update")
            except Exception as e:
                logger.warning("bandit update failed for %s: %s", skill_id, e)
            return ToolResult(
                success=True,
                output=(
                    f"recorded {outcome} (reward={reward}) for skill={skill_id} task={task_id}"
                ),
                data={
                    "skill_id": skill_id,
                    "task_id": task_id,
                    "outcome": outcome,
                    "reward": reward,
                    "bandit_updated": bandit_updated,
                    "log_written": log_written,
                },
            )
        except Exception as e:
            logger.error("skill_record_outcome failed: %s", e)
            return ToolResult(success=False, error=str(e))


class SkillGetMetricsTool(BaseTool):
    """Compute aggregate metrics for a skill over a recent time window."""

    name = "skill_get_metrics"
    description = (
        "Compute aggregate metrics for a skill over a recent time window. "
        "Periods: '1h', '24h', '7d', '30d'. Returns count, success_rate, "
        "partial_rate, failure_rate, avg_duration_ms, p95_duration_ms, "
        "and the current bandit arm state (alpha/beta) if the bandit "
        "persist file is available. Pure read — does not touch the bandit."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "period": {
                    "type": "string",
                    "enum": list(_PERIOD_SECONDS.keys()),
                    "default": "24h",
                },
            },
            "required": ["skill_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            skill_id = str(kwargs["skill_id"])
            period = str(kwargs.get("period", "24h"))
            window = _PERIOD_SECONDS.get(period)
            if window is None:
                return ToolResult(
                    success=False,
                    error=f"invalid period {period!r}; use one of {list(_PERIOD_SECONDS)}",
                )
            since = time.time() - window
            outcomes = _load_outcomes(skill_id, since)
            n = len(outcomes)
            counts = {"success": 0, "partial": 0, "failure": 0}
            durations: list[float] = []
            for r in outcomes:
                o = str(r.get("outcome", "")).lower()
                if o in counts:
                    counts[o] += 1
                d = float(r.get("duration_ms") or 0)
                if d > 0:
                    durations.append(d)

            def _rate(k: str) -> float:
                return counts[k] / n if n else 0.0

            avg_duration = sum(durations) / len(durations) if durations else 0.0
            p95_duration = _percentile(durations, 0.95)
            # Bandit arm stats — best-effort, read-only.
            bandit_stats: dict[str, float] | None = None
            try:
                from selva_orchestrator.bandit import ThompsonBandit

                bandit = ThompsonBandit(persist_path=_bandit_path())
                stats = bandit.get_stats().get(skill_id)
                if stats is not None:
                    bandit_stats = {
                        "alpha": float(stats.get("alpha", 1.0)),
                        "beta": float(stats.get("beta", 1.0)),
                    }
            except ImportError:
                pass
            except Exception as e:
                logger.warning("bandit stats read failed: %s", e)
            return ToolResult(
                success=True,
                output=(
                    f"skill={skill_id} period={period} n={n} success_rate={_rate('success'):.2f}"
                ),
                data={
                    "skill_id": skill_id,
                    "period": period,
                    "count": n,
                    "success_rate": _rate("success"),
                    "partial_rate": _rate("partial"),
                    "failure_rate": _rate("failure"),
                    "avg_duration_ms": avg_duration,
                    "p95_duration_ms": p95_duration,
                    "counts": counts,
                    "bandit_arm": bandit_stats,
                },
            )
        except Exception as e:
            logger.error("skill_get_metrics failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_skill_performance_tools() -> list[BaseTool]:
    """Return the skill-performance tool set."""
    return [
        SkillRecordOutcomeTool(),
        SkillGetMetricsTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    SkillRecordOutcomeTool,
    SkillGetMetricsTool,
):
    _cls.audience = Audience.PLATFORM
