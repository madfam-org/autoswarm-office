"""Phase 2 critical-path coverage for ``nexus_api.routers.swarms``.

Targets endpoints not exercised by ``test_swarm_task_lifecycle.py`` or
``test_dispatch_audience_gate.py``:

- ``POST /dispatch`` validation paths: workflow_id required for
  custom, invalid UUID, workflow not found.
- ``GET /tasks`` list_active_tasks (queued/pending/running statuses).
- ``GET /tasks/board`` task board grouping with event aggregates +
  agent name resolution.
- ``GET /tasks/{id}`` happy + 404 + invalid UUID.
- ``PATCH /tasks/{id}`` invalid UUID + 404 + completed_at on terminal
  status + payload merge with result.
- ``POST /tasks/reap-stale`` reaper marks old queued tasks as failed.
- ``_compute_perf_weight`` neutral default + computed mix.
- Pydantic ``DispatchRequest`` graph_type pattern enforcement.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from nexus_api.models import Agent, SwarmTask, TaskEvent
from nexus_api.routers.swarms import DispatchRequest, _compute_perf_weight

# ---------------------------------------------------------------------------
# Reset module-level dispatch rate limiter between tests so we never spill
# accumulated dispatches from one test class to the next.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_dispatch_limiter() -> None:
    from nexus_api.routers import swarms as _swarms

    _swarms._dispatch_limiter._messages.clear()




# ---------------------------------------------------------------------------
# DispatchRequest pydantic validation
# ---------------------------------------------------------------------------


class TestDispatchRequestSchema:
    def test_valid_graph_types_accepted(self) -> None:
        for gt in (
            "sequential", "parallel", "coding", "research", "crm",
            "custom", "deployment", "puppeteer", "meeting", "billing",
            "accounting", "sales", "intelligence", "operations",
        ):
            req = DispatchRequest(description="x", graph_type=gt)
            assert req.graph_type == gt

    def test_invalid_graph_type_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DispatchRequest(description="x", graph_type="malicious")

    def test_description_min_length_enforced(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DispatchRequest(description="", graph_type="research")

    def test_description_max_length_enforced(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DispatchRequest(description="x" * 2001, graph_type="research")


# ---------------------------------------------------------------------------
# _compute_perf_weight
# ---------------------------------------------------------------------------


class TestComputePerfWeight:
    def test_new_agent_returns_neutral_default(self) -> None:
        agent = Agent(
            name="new", role="coder", status="idle", org_id="o",
            tasks_completed=0, tasks_failed=0,
            approval_success_count=0, approval_denial_count=0,
        )
        assert _compute_perf_weight(agent) == 0.5

    def test_perfect_history_returns_one(self) -> None:
        agent = Agent(name="great", role="coder", status="idle", org_id="o")
        agent.tasks_completed = 10
        agent.tasks_failed = 0
        agent.approval_success_count = 10
        agent.approval_denial_count = 0
        assert _compute_perf_weight(agent) == 1.0

    def test_failed_history_returns_zero(self) -> None:
        agent = Agent(name="bad", role="coder", status="idle", org_id="o")
        agent.tasks_completed = 0
        agent.tasks_failed = 10
        agent.approval_success_count = 0
        agent.approval_denial_count = 10
        assert _compute_perf_weight(agent) == 0.0

    def test_mixed_history_blends_50_50(self) -> None:
        agent = Agent(name="mid", role="coder", status="idle", org_id="o")
        agent.tasks_completed = 8
        agent.tasks_failed = 2  # 80% completion
        agent.approval_success_count = 5
        agent.approval_denial_count = 5  # 50% approval
        # 0.5 * 0.5 + 0.5 * 0.8 = 0.65
        assert _compute_perf_weight(agent) == pytest.approx(0.65)

    def test_zero_total_tasks_uses_default_completion_rate(self) -> None:
        agent = Agent(name="approval_only", role="coder", status="idle", org_id="o")
        agent.tasks_completed = 0
        agent.tasks_failed = 0
        agent.approval_success_count = 4
        agent.approval_denial_count = 0
        # completion_rate defaults to 0.5 when no tasks; approval_rate = 1.0
        # total = 0.5 * 1.0 + 0.5 * 0.5 = 0.75
        assert _compute_perf_weight(agent) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# POST /dispatch — validation paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDispatchValidation:
    async def test_custom_without_workflow_id_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=AsyncMock(execute_with_retry=AsyncMock()),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "x", "graph_type": "custom"},
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "workflow_id" in resp.json()["detail"]

    async def test_custom_with_invalid_workflow_uuid_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=AsyncMock(execute_with_retry=AsyncMock()),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                json={
                    "description": "x",
                    "graph_type": "custom",
                    "workflow_id": "not-a-uuid",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "UUID" in resp.json()["detail"]

    async def test_custom_with_unknown_workflow_returns_404(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        unknown = str(uuid.uuid4())
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=AsyncMock(execute_with_retry=AsyncMock()),
        ):
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                json={
                    "description": "x",
                    "graph_type": "custom",
                    "workflow_id": unknown,
                },
                headers=auth_headers,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /tasks (list_active_tasks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListActiveTasks:
    async def test_returns_empty_list_when_no_tasks(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/swarms/tasks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_lists_only_active_statuses(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        # Create one task per status type
        for st in ("queued", "pending", "running", "completed", "failed"):
            db_session.add(
                SwarmTask(
                    description=f"task-{st}",
                    graph_type="research",
                    assigned_agent_ids=[],
                    payload={},
                    status=st,
                    org_id="dev-org",
                )
            )
        await db_session.commit()

        resp = await client.get("/api/v1/swarms/tasks", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        statuses = {item["status"] for item in items}
        assert statuses == {"queued", "pending", "running"}


# ---------------------------------------------------------------------------
# GET /tasks/{id} + PATCH /tasks/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetAndPatchTask:
    async def test_get_task_invalid_uuid_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get(
            "/api/v1/swarms/tasks/not-a-uuid", headers=auth_headers
        )
        assert resp.status_code == 400

    async def test_get_task_unknown_returns_404(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get(
            f"/api/v1/swarms/tasks/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_patch_task_invalid_uuid_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.patch(
            "/api/v1/swarms/tasks/garbage",
            json={"status": "running"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_patch_task_unknown_returns_404(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.patch(
            f"/api/v1/swarms/tasks/{uuid.uuid4()}",
            json={"status": "running"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_patch_invalid_status_value_rejected_by_pydantic(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        task = SwarmTask(
            description="x", graph_type="research", assigned_agent_ids=[],
            payload={}, status="queued", org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)
        resp = await client.patch(
            f"/api/v1/swarms/tasks/{task.id}",
            json={"status": "purgatory"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_patch_with_result_merges_into_payload(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        task = SwarmTask(
            description="x", graph_type="research", assigned_agent_ids=[],
            payload={"existing": "value"}, status="running", org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)
        task_id = task.id

        resp = await client.patch(
            f"/api/v1/swarms/tasks/{task_id}",
            json={"status": "completed", "result": {"answer": 42}},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Confirm payload merged + completed_at set
        db_session.expire_all()
        result = await db_session.execute(select(SwarmTask).where(SwarmTask.id == task_id))
        refreshed = result.scalar_one()
        assert refreshed.payload["existing"] == "value"
        assert refreshed.payload["result"] == {"answer": 42}
        assert refreshed.completed_at is not None


# ---------------------------------------------------------------------------
# GET /tasks/board
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTaskBoard:
    async def test_empty_board_has_all_columns(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/swarms/tasks/board", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["columns"].keys()) == {"queued", "running", "completed", "failed"}
        assert all(len(items) == 0 for items in body["columns"].values())
        assert body["totals"] == {
            "queued": 0, "running": 0, "completed": 0, "failed": 0,
        }

    async def test_board_aggregates_events_and_resolves_agent_names(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        # One agent
        agent = Agent(name="Alice", role="coder", status="idle", org_id="dev-org")
        db_session.add(agent)
        await db_session.flush()
        await db_session.refresh(agent)

        # One task assigned to Alice
        task = SwarmTask(
            description="board-test",
            graph_type="research",
            assigned_agent_ids=[str(agent.id)],
            payload={},
            status="running",
            org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)

        # Two events with duration + tokens
        for _ in range(2):
            ev = TaskEvent(
                task_id=task.id,
                event_type="node.exited",
                event_category="task",
                duration_ms=500,
                token_count=100,
                org_id="dev-org",
            )
            db_session.add(ev)
        await db_session.commit()

        resp = await client.get("/api/v1/swarms/tasks/board", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        running_items = body["columns"]["running"]
        assert len(running_items) == 1
        item = running_items[0]
        # Aggregates
        assert item["duration_ms"] == 1000
        assert item["total_tokens"] == 200
        assert item["event_count"] == 2
        # Agent name resolved
        assert "Alice" in item["agent_names"]

    async def test_board_handles_unresolvable_agent_id_gracefully(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        # Task references non-existent agent UUID
        ghost_id = str(uuid.uuid4())
        task = SwarmTask(
            description="ghost-agent-task",
            graph_type="research",
            assigned_agent_ids=[ghost_id],
            payload={},
            status="completed",
            org_id="dev-org",
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get("/api/v1/swarms/tasks/board", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        completed_items = body["columns"]["completed"]
        assert len(completed_items) == 1
        # Falls back to first 8 chars of the agent UUID when name not found.
        assert completed_items[0]["agent_names"][0] == ghost_id[:8]


# ---------------------------------------------------------------------------
# POST /tasks/reap-stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReapStaleTasks:
    async def test_reaps_old_queued_tasks(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        old_task = SwarmTask(
            description="stale", graph_type="research", assigned_agent_ids=[],
            payload={}, status="queued", org_id="dev-org",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        fresh_task = SwarmTask(
            description="fresh", graph_type="research", assigned_agent_ids=[],
            payload={}, status="queued", org_id="dev-org",
        )
        running_task = SwarmTask(
            description="active", graph_type="research", assigned_agent_ids=[],
            payload={}, status="running", org_id="dev-org",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db_session.add_all([old_task, fresh_task, running_task])
        await db_session.commit()

        resp = await client.post(
            "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["reaped"] == 1

        # Old queued task is now failed; fresh + running untouched.
        # Refresh each ORM-cached object explicitly (async-safe).
        for task in (old_task, fresh_task, running_task):
            await db_session.refresh(task)
        assert old_task.status == "failed"
        assert fresh_task.status == "queued"
        assert running_task.status == "running"

    async def test_reap_returns_zero_when_no_stale_tasks(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["reaped"] == 0


# ---------------------------------------------------------------------------
# Direct endpoint invocation — bypass ASGI to give pytest-cov a clean
# stack frame for line tracking. The async-via-httpx-via-ASGI path
# loses trace events under some pytest-cov configurations.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEndpointsDirect:
    """Call the route handlers directly through their async signatures.

    These tests verify business logic at the function level — they do
    not exercise FastAPI dependency injection, validation, or middleware.
    The FastAPI-level paths are covered by the HTTP tests above; this
    block exists purely to lock in the inner endpoint code paths so
    coverage reports the function bodies as executed.
    """

    async def test_list_active_tasks_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import list_active_tasks
        from nexus_api.tenant import TenantContext

        tenant = TenantContext(org_id="dev-org")

        # Insert one of each status
        for st in ("queued", "running", "completed"):
            db_session.add(
                SwarmTask(
                    description=f"d-{st}", graph_type="research",
                    assigned_agent_ids=[], payload={}, status=st, org_id="dev-org",
                )
            )
        await db_session.commit()

        out = await list_active_tasks(db=db_session, tenant=tenant)
        statuses = {t.status for t in out}
        assert statuses == {"queued", "running"}

    async def test_get_task_board_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import get_task_board
        from nexus_api.tenant import TenantContext

        tenant = TenantContext(org_id="dev-org")
        agent = Agent(name="Bob", role="coder", status="idle", org_id="dev-org")
        db_session.add(agent)
        await db_session.flush()
        await db_session.refresh(agent)
        task = SwarmTask(
            description="board-direct",
            graph_type="research",
            assigned_agent_ids=[str(agent.id)],
            payload={},
            status="completed",
            org_id="dev-org",
        )
        db_session.add(task)
        await db_session.commit()

        out = await get_task_board(db=db_session, tenant=tenant)
        assert "completed" in out.columns
        assert any(it.id == str(task.id) for it in out.columns["completed"])

    async def test_get_task_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import get_task

        task = SwarmTask(
            description="direct-get", graph_type="research",
            assigned_agent_ids=[], payload={}, status="completed", org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)
        out = await get_task(task_id=str(task.id), db=db_session)
        assert out.id == str(task.id)

    async def test_get_task_invalid_uuid_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import get_task

        with pytest.raises(HTTPException) as exc:
            await get_task(task_id="not-a-uuid", db=db_session)
        assert exc.value.status_code == 400

    async def test_get_task_404_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import get_task

        with pytest.raises(HTTPException) as exc:
            await get_task(task_id=str(uuid.uuid4()), db=db_session)
        assert exc.value.status_code == 404

    async def test_update_task_status_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import TaskStatusUpdate, update_task_status

        task = SwarmTask(
            description="patch", graph_type="research",
            assigned_agent_ids=[], payload={"existing": "v"}, status="running", org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)

        body = TaskStatusUpdate(
            status="completed", result={"k": "v"},
            started_at="2026-04-01T10:00:00+00:00",
            error_message=None,
        )
        out = await update_task_status(task_id=str(task.id), body=body, db=db_session)
        assert out.status == "completed"
        # Refresh and check side effects.
        await db_session.refresh(task)
        assert task.completed_at is not None
        assert task.payload["result"] == {"k": "v"}
        assert task.started_at is not None

    async def test_update_task_status_invalid_uuid_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import TaskStatusUpdate, update_task_status

        with pytest.raises(HTTPException) as exc:
            await update_task_status(
                task_id="garbage",
                body=TaskStatusUpdate(status="running"),
                db=db_session,
            )
        assert exc.value.status_code == 400

    async def test_update_task_status_404_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import TaskStatusUpdate, update_task_status

        with pytest.raises(HTTPException) as exc:
            await update_task_status(
                task_id=str(uuid.uuid4()),
                body=TaskStatusUpdate(status="running"),
                db=db_session,
            )
        assert exc.value.status_code == 404

    async def test_reap_stale_tasks_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import reap_stale_tasks

        old = SwarmTask(
            description="old-direct", graph_type="research", assigned_agent_ids=[],
            payload={}, status="queued", org_id="dev-org",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db_session.add(old)
        await db_session.commit()

        # Caller must hold an allowed role (service / worker / platform / admin).
        platform_caller = {"sub": "ops-cron", "roles": ["service"], "org_id": "platform"}
        out = await reap_stale_tasks(user=platform_caller, db=db_session)
        assert out["reaped"] == 1
        await db_session.refresh(old)
        assert old.status == "failed"

    async def test_dispatch_task_direct_happy_path(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exercise the dispatch_task body via a direct call.

        Mocks Redis xadd so we don't need a live Redis. Tenant-config
        and Dhanam-billing branches are skipped (no TenantConfig row).
        """
        from unittest.mock import MagicMock

        # Reset rate limiter so we don't 429 from prior tests.
        from nexus_api.routers import swarms as _swarms
        from nexus_api.routers.swarms import (
            DispatchRequest,
            dispatch_task,
        )
        from nexus_api.tenant import TenantContext
        _swarms._dispatch_limiter._messages.clear()

        # Insert one idle agent so auto-assignment path runs.
        agent = Agent(name="DirBot", role="coder", status="idle", org_id="dev-org")
        db_session.add(agent)
        await db_session.commit()

        # Mock Redis pool.
        mock_pool = AsyncMock()
        mock_pool.execute_with_retry = AsyncMock()
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=mock_pool,
        ):
            request = MagicMock()
            request.state.request_id = "test-req-1"
            tenant = TenantContext(org_id="dev-org")
            body = DispatchRequest(
                description="direct dispatch",
                graph_type="research",
            )
            out = await dispatch_task(body=body, request=request, db=db_session, tenant=tenant)
        assert out.status in ("queued", "pending")
        # The Redis xadd was attempted.
        mock_pool.execute_with_retry.assert_awaited_once()
