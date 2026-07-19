"""Agent-hours accrual — Selva's WTP-validated metered SKU (Tulana packs).

When a task reaches a terminal state we record one immutable ledger row
capturing the billable agent-hours it consumed:

    agent_hours = agent_count * (completed_at - started_at) / 3600

Kept fail-safe and idempotent: a task with no ``started_at`` (never picked
up) accrues nothing, and the unique constraint on ``task_id`` means a
re-delivered completion cannot double-bill. The rate lookup
(``billing_tiers.get_tulana_hourly_rate_mxn``) stays the pricing side;
this module only counts hours.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentHoursLedger, SwarmTask

logger = logging.getLogger(__name__)

_SECONDS_PER_HOUR = Decimal(3600)


def _as_utc(dt: datetime) -> datetime:
    """Coerce a possibly-naive timestamp to UTC-aware.

    Postgres returns tz-aware datetimes, but SQLite (tests) and some worker
    PATCH payloads carry naive ones. Subtracting a naive from an aware
    datetime raises — normalize both to aware so accrual never crashes on a
    tz mismatch (which would silently drop billing for that task)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _compute_agent_hours(duration_seconds: int, agent_count: int) -> Decimal:
    hours = (Decimal(duration_seconds) * Decimal(max(1, agent_count))) / _SECONDS_PER_HOUR
    # 6 dp so a 5-second task still accrues instead of truncating to zero.
    return hours.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def accrue_agent_hours(db: AsyncSession, task: SwarmTask) -> AgentHoursLedger | None:
    """Write an agent-hours ledger row for a just-completed *task*.

    Returns the new row, or ``None`` when there is nothing billable
    (no start time, non-positive duration) or a row already exists for
    this task (idempotent replay). Does not commit — the caller owns the
    transaction. Never raises: an accrual failure must not fail the
    task-status update.
    """
    try:
        if task.started_at is None or task.completed_at is None:
            return None

        started = _as_utc(task.started_at)
        completed = _as_utc(task.completed_at)
        duration_seconds = int((completed - started).total_seconds())
        if duration_seconds <= 0:
            return None

        # Idempotency: one accrual per task (also enforced by the DB unique
        # constraint — this check avoids a needless IntegrityError on replay).
        existing = await db.execute(
            select(AgentHoursLedger.id).where(AgentHoursLedger.task_id == task.id)
        )
        if existing.scalar_one_or_none() is not None:
            return None

        agent_count = len(task.assigned_agent_ids or []) or 1
        entry = AgentHoursLedger(
            org_id=task.org_id,
            task_id=task.id,
            graph_type=task.graph_type,
            agent_count=agent_count,
            duration_seconds=duration_seconds,
            agent_hours=_compute_agent_hours(duration_seconds, agent_count),
        )
        db.add(entry)
        await db.flush()
        return entry
    except Exception:
        logger.warning(
            "Agent-hours accrual failed for task %s (not billed)",
            getattr(task, "id", "?"),
            exc_info=True,
        )
        return None
