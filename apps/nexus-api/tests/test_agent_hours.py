"""Tests for agent-hours accrual (M3) — Selva's metered Tulana-priced SKU."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import AgentHoursLedger, SwarmTask
from nexus_api.services.agent_hours import _compute_agent_hours, accrue_agent_hours


class TestComputeAgentHours:
    def test_one_agent_one_hour(self) -> None:
        assert _compute_agent_hours(3600, 1) == Decimal("1.000000")

    def test_multiplies_by_agent_count(self) -> None:
        assert _compute_agent_hours(3600, 3) == Decimal("3.000000")

    def test_short_task_still_accrues(self) -> None:
        # 5s single agent → 0.001389 h, not truncated to zero.
        assert _compute_agent_hours(5, 1) == Decimal("0.001389")

    def test_zero_agents_treated_as_one(self) -> None:
        assert _compute_agent_hours(3600, 0) == Decimal("1.000000")


def _make_task(**kw: object) -> SwarmTask:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "description": "t",
        "graph_type": "research",
        "org_id": "acme",
        "assigned_agent_ids": ["a1", "a2"],
        "started_at": now - timedelta(hours=2),
        "completed_at": now,
    }
    defaults.update(kw)
    return SwarmTask(**defaults)


@pytest.mark.asyncio
class TestAccrueAgentHours:
    async def test_accrues_hours_for_completed_task(
        self, db_session: AsyncSession
    ) -> None:
        task = _make_task()
        db_session.add(task)
        await db_session.flush()

        entry = await accrue_agent_hours(db_session, task)
        assert entry is not None
        # 2h * 2 agents = 4 agent-hours.
        assert entry.agent_hours == Decimal("4.000000")
        assert entry.agent_count == 2
        assert entry.org_id == "acme"

    async def test_no_started_at_accrues_nothing(self, db_session: AsyncSession) -> None:
        task = _make_task(started_at=None)
        db_session.add(task)
        await db_session.flush()
        assert await accrue_agent_hours(db_session, task) is None

    async def test_non_positive_duration_accrues_nothing(
        self, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        task = _make_task(started_at=now, completed_at=now)
        db_session.add(task)
        await db_session.flush()
        assert await accrue_agent_hours(db_session, task) is None

    async def test_naive_and_aware_timestamps_mix_safely(
        self, db_session: AsyncSession
    ) -> None:
        """Regression: SQLite/worker payloads can give a naive started_at while
        the endpoint sets an aware completed_at. Subtracting the two must not
        crash (which would silently drop billing for the task)."""
        naive_start = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        aware_end = datetime.now(UTC)
        task = _make_task(started_at=naive_start, completed_at=aware_end)
        db_session.add(task)
        await db_session.flush()

        entry = await accrue_agent_hours(db_session, task)
        assert entry is not None
        assert entry.agent_hours > Decimal("0")

    async def test_idempotent_no_double_bill(self, db_session: AsyncSession) -> None:
        task = _make_task()
        db_session.add(task)
        await db_session.flush()

        first = await accrue_agent_hours(db_session, task)
        second = await accrue_agent_hours(db_session, task)
        assert first is not None
        assert second is None  # replay writes nothing

        count = await db_session.execute(
            select(func.count(AgentHoursLedger.id)).where(
                AgentHoursLedger.task_id == task.id
            )
        )
        assert count.scalar_one() == 1


@pytest.mark.asyncio
class TestAgentHoursEndpoint:
    async def test_returns_zero_when_no_usage(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/billing/agent-hours", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_hours"] == 0
        assert data["task_count"] == 0


@pytest.mark.asyncio
class TestCompletionAccruesViaEndpoint:
    async def test_patch_to_completed_accrues_agent_hours(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Completing a task through the real PATCH endpoint writes an
        agent-hours ledger row — the full accrual path, not just the helper."""
        started = datetime.now(UTC) - timedelta(hours=1)
        task = SwarmTask(
            description="metered work",
            graph_type="research",
            assigned_agent_ids=["a1"],
            status="running",
            org_id="dev-org",
            started_at=started,
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)
        task_id = task.id

        resp = await client.patch(
            f"/api/v1/swarms/tasks/{task_id}",
            json={"status": "completed"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        db_session.expire_all()
        row = await db_session.execute(
            select(AgentHoursLedger).where(AgentHoursLedger.task_id == task_id)
        )
        entry = row.scalar_one()
        # ~1h * 1 agent ≈ 1 agent-hour (allow small clock delta).
        assert Decimal("0.98") <= entry.agent_hours <= Decimal("1.02")
        assert entry.org_id == "dev-org"
