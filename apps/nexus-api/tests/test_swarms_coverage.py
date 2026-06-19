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

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from nexus_api.models import Agent, SwarmTask, TaskEvent
from nexus_api.routers.swarms import (
    DispatchRequest,
    _compute_perf_weight,
    _deployment_dispatch_from_ecosystem_app,
    _deployment_status_from_evidence,
    _parse_ecosystem_app_manifest,
    _pick_first,
    _verify_ecosystem_app_manifest,
)

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
            "campaign", "calibration",
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

    def test_ecosystem_app_manifest_maps_to_deployment_dispatch(self) -> None:
        manifest = {
            "apiVersion": "madfam.io/v1alpha1",
            "kind": "EcosystemApp",
            "metadata": {
                "app_id": "forgesight",
                "environment": "production",
                "idempotency_key": "forgesight-production-v1",
                "desired_state_hash": "sha256:"
                "0000000000000000000000000000000000000000000000000000000000000000",
                "labels": {"environment": "production"},
            },
            "spec": {
                "identity": {"issuer": "https://auth.madfam.io"},
                "runtime": {"namespace": "forgesight"},
                "id": "forgesight",
                "deployment": {
                    "gitops_app": "forgesight-production",
                    "branch": "main",
                    "manifest_path": "apps/forgesight/app.yaml",
                    "repo_path": "madfam-org/forgesight",
                    "smoke_checks": [
                        {"url": "https://forgesight.quest/health", "expect_status": 200}
                    ],
                    "current_pointer": {"git_sha": "abc123"},
                    "rollback_pointer": {"git_sha": "def456"},
                },
                "orchestration": {"audience": "platform"},
                "observability": {"evidence_retention_days": 365},
            },
        }

        req = _deployment_dispatch_from_ecosystem_app(
            manifest,
            assigned_agent_ids=["agent-1"],
            required_skills=["deployment"],
            source="ecosystem-app",
            idempotency_key=None,
        )

        assert req.graph_type == "deployment"
        assert req.assigned_agent_ids == ["agent-1"]
        assert req.required_skills == ["deployment"]
        assert req.payload["service"] == "forgesight"
        assert req.payload["environment"] == "production"
        assert req.payload["gitops_app"] == "forgesight-production"
        assert req.payload["rollback_pointer"] == {"git_sha": "def456"}
        assert req.idempotency_key is not None
        assert req.idempotency_key.startswith("ecosystem-app:forgesight:production:")

    def test_ecosystem_app_verify_returns_derived_read_only_surface(self) -> None:
        manifest = {
            "apiVersion": "madfam.io/v1alpha1",
            "kind": "EcosystemApp",
            "metadata": {
                "app_id": "forgesight",
                "environment": "production",
                "idempotency_key": "ecosystem-app:forgesight:production:abc123",
                "desired_state_hash": "sha256:abc123",
                "labels": {"environment": "production"},
            },
            "spec": {
                "id": "forgesight",
                "identity": {"janua_client_id": "forgesight-app"},
                "runtime": {"namespace": "forgesight"},
                "deployment": {
                    "gitops_app": "forgesight-production",
                    "branch": "main",
                    "manifest_path": "apps/forgesight/app.yaml",
                    "repo_path": "madfam-org/forgesight",
                    "smoke_checks": [
                        {"url": "https://forgesight.quest/health", "expect_status": 200}
                    ],
                    "current_pointer": {"git_sha": "abc123"},
                    "rollback_pointer": {"git_sha": "def456"},
                },
                "orchestration": {"selva_graph": "deployment"},
                "observability": {"health_url": "https://forgesight.quest/health"},
            },
        }

        out = _verify_ecosystem_app_manifest(manifest)

        assert out.ok is True
        assert out.kind == "EcosystemApp"
        assert out.api_version == "madfam.io/v1alpha1"
        assert out.gaps == []
        assert out.unsupported_placeholders == []
        assert out.derived["graph_type"] == "deployment"
        assert out.derived["app_id"] == "forgesight"
        assert out.derived["environment"] == "production"
        assert out.derived["current_pointer"] == {"git_sha": "abc123"}
        assert out.derived["rollback_pointer"] == {"git_sha": "def456"}
        assert out.derived["desired_state_hash"] == out.manifest_hash
        assert out.derived["idempotency_key"].startswith(
            "ecosystem-app:forgesight:production:"
        )

    def test_ecosystem_app_verify_reports_gaps_and_unsupported_placeholders(self) -> None:
        out = _verify_ecosystem_app_manifest(
            {
                "apiVersion": "madfam.io/v1",
                "kind": "EcosystemApp",
                "metadata": {"labels": {"environment": "production"}},
                "spec": {
                    "deployment": {"enclii": {"mode": "future"}},
                    "janua": {"client": "future"},
                },
            }
        )

        assert out.ok is False
        assert "metadata.app_id" in out.gaps
        assert "metadata.environment" in out.gaps
        assert "metadata.idempotency_key" in out.gaps
        assert "metadata.desired_state_hash" in out.gaps
        assert "spec.identity" in out.gaps
        assert "spec.runtime" in out.gaps
        assert "spec.deployment.gitops_app" in out.gaps
        assert "spec.deployment.smoke_checks" in out.gaps
        assert "spec.deployment.rollback_pointer" in out.gaps
        assert "spec.orchestration" in out.gaps
        assert "spec.observability" in out.gaps
        assert out.unsupported_placeholders == ["spec.janua", "spec.deployment.enclii"]

    def test_production_ecosystem_app_requires_safety_fields(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _deployment_dispatch_from_ecosystem_app(
                {
                    "kind": "EcosystemApp",
                    "metadata": {"name": "unsafe", "labels": {"environment": "production"}},
                    "spec": {"deployment": {}},
                },
                assigned_agent_ids=[],
                required_skills=[],
                source="ecosystem-app",
                idempotency_key=None,
            )

        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "production_manifest_missing_safety_fields"

    def test_manifest_helpers_cover_json_yaml_and_error_paths(self) -> None:
        from fastapi import HTTPException

        assert _parse_ecosystem_app_manifest(b'{"kind":"EcosystemApp"}') == {
            "kind": "EcosystemApp"
        }
        assert _parse_ecosystem_app_manifest("kind: EcosystemApp\nmetadata:\n  name: yaml") == {
            "kind": "EcosystemApp",
            "metadata": {"name": "yaml"},
        }

        with pytest.raises(HTTPException) as scalar_exc:
            _parse_ecosystem_app_manifest("[1, 2, 3]")
        assert scalar_exc.value.detail == "manifest must parse to an object"

        with pytest.raises(HTTPException) as invalid_exc:
            _parse_ecosystem_app_manifest("kind: [")
        assert invalid_exc.value.detail == "manifest must be valid EcosystemApp JSON or YAML"

    def test_ecosystem_app_rejects_wrong_kind_and_non_object_sections(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as kind_exc:
            _deployment_dispatch_from_ecosystem_app(
                {"kind": "ConfigMap"},
                assigned_agent_ids=[],
                required_skills=[],
                source="ecosystem-app",
                idempotency_key=None,
            )
        assert kind_exc.value.detail == "manifest.kind must be EcosystemApp"

        with pytest.raises(HTTPException) as shape_exc:
            _deployment_dispatch_from_ecosystem_app(
                {
                    "kind": "EcosystemApp",
                    "metadata": ["not-an-object"],
                    "spec": {"deployment": ["not-an-object"]},
                },
                assigned_agent_ids=[],
                required_skills=[],
                source="ecosystem-app",
                idempotency_key=None,
            )
        assert shape_exc.value.detail == (
            "manifest metadata, spec, and spec.deployment must be objects"
        )

    def test_small_deployment_helpers(self) -> None:
        assert _deployment_status_from_evidence(
            {"deployment_status": "healthy"}, None, "fallback"
        ) == "healthy"
        assert _deployment_status_from_evidence(
            {}, {"deploy_status": "rolled-out"}, "fallback"
        ) == "rolled-out"
        assert _deployment_status_from_evidence({}, None, "fallback") == "fallback"
        assert _pick_first(None, "", [], {}, "first", "second") == "first"
        assert _pick_first(None, "", [], {}) is None


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
        assert set(body["columns"].keys()) == {"todo", "in_progress", "review", "done", "blocked"}
        assert all(len(items) == 0 for items in body["columns"].values())
        assert body["totals"] == {
            "todo": 0, "in_progress": 0, "review": 0, "done": 0, "blocked": 0,
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
            kanban_status="in_progress",
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
        in_progress_items = body["columns"]["in_progress"]
        assert len(in_progress_items) == 1
        item = in_progress_items[0]
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
            kanban_status="done",
            org_id="dev-org",
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get("/api/v1/swarms/tasks/board", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        done_items = body["columns"]["done"]
        assert len(done_items) == 1
        # Falls back to first 8 chars of the agent UUID when name not found.
        assert done_items[0]["agent_names"][0] == ghost_id[:8]


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
            kanban_status="done",
            org_id="dev-org",
        )
        db_session.add(task)
        await db_session.commit()

        out = await get_task_board(db=db_session, tenant=tenant)
        assert "done" in out.columns
        assert any(it.id == str(task.id) for it in out.columns["done"])

    async def test_get_task_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import get_task
        from nexus_api.tenant import TenantContext

        tenant = TenantContext(org_id="dev-org")

        task = SwarmTask(
            description="direct-get", graph_type="research",
            assigned_agent_ids=[], payload={}, status="completed", org_id="dev-org",
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.refresh(task)
        out = await get_task(task_id=str(task.id), db=db_session, tenant=tenant)
        assert out.id == str(task.id)

    async def test_get_task_invalid_uuid_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import get_task
        from nexus_api.tenant import TenantContext

        tenant = TenantContext(org_id="dev-org")

        with pytest.raises(HTTPException) as exc:
            await get_task(task_id="not-a-uuid", db=db_session, tenant=tenant)
        assert exc.value.status_code == 400

    async def test_get_task_404_direct(self, db_session) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.swarms import get_task
        from nexus_api.tenant import TenantContext

        tenant = TenantContext(org_id="dev-org")

        with pytest.raises(HTTPException) as exc:
            await get_task(task_id=str(uuid.uuid4()), db=db_session, tenant=tenant)
        assert exc.value.status_code == 404

    async def test_kanban_management_paths_direct(self, db_session) -> None:
        from nexus_api.routers.swarms import (
            KanbanTaskImportRequest,
            KanbanTaskUpdate,
            TaskClaimRequest,
            TaskCommentCreate,
            claim_available_task,
            create_task_comment,
            export_kanban_tasks,
            get_kanban_metrics,
            import_kanban_tasks,
            list_task_comments,
            list_task_history,
            notify_overdue_tasks,
            update_task_kanban,
        )
        from nexus_api.tenant import TenantContext

        class JsonRequest:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            async def json(self) -> dict[str, object]:
                return self.payload

            async def body(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        tenant = TenantContext(org_id="dev-org")
        user = {"sub": "operator-1", "email": "operator@example.com", "roles": ["admin"]}
        now = datetime.now(UTC)
        due_date = now - timedelta(hours=1)

        dependency = SwarmTask(
            description="dependency",
            graph_type="research",
            assigned_agent_ids=[],
            payload={},
            status="completed",
            kanban_status="done",
            completed_at=now,
            created_at=now,
            updated_at=now,
            labels=["ops"],
            org_id="dev-org",
        )
        task = SwarmTask(
            description="kanban-direct",
            graph_type="research",
            assigned_agent_ids=[],
            payload={},
            status="queued",
            kanban_status="todo",
            priority="medium",
            labels=[],
            created_at=now,
            updated_at=now,
            org_id="dev-org",
        )
        claimable = SwarmTask(
            description="claimable",
            graph_type="research",
            assigned_agent_ids=[],
            payload={},
            status="backlog",
            kanban_status="todo",
            priority="low",
            labels=[],
            created_at=now,
            updated_at=now,
            org_id="dev-org",
        )
        db_session.add_all([dependency, task, claimable])
        await db_session.flush()
        await db_session.refresh(dependency)
        await db_session.refresh(task)
        await db_session.refresh(claimable)

        with patch(
            "nexus_api.routers.swarms._emit_task_lifecycle_notification",
            new=AsyncMock(return_value=True),
        ) as notify:
            updated = await update_task_kanban(
                task_id=str(task.id),
                body=KanbanTaskUpdate(
                    title="Kanban Direct",
                    kanban_status="review",
                    priority="high",
                    labels=["ops", "urgent"],
                    due_date=due_date.isoformat().replace("+00:00", "Z"),
                    parent_task_id=str(dependency.id),
                    depends_on=[str(dependency.id)],
                ),
                user=user,
                db=db_session,
                tenant=tenant,
            )
            assert updated.kanban_status == "review"
            assert updated.priority == "high"

            comment = await create_task_comment(
                task_id=str(task.id),
                body=TaskCommentCreate(body="needs review"),
                user=user,
                db=db_session,
                tenant=tenant,
            )
            assert comment.body == "needs review"
            comments = await list_task_comments(
                task_id=str(task.id),
                db=db_session,
                tenant=tenant,
            )
            assert [item.body for item in comments] == ["needs review"]

            history = await list_task_history(
                task_id=str(task.id),
                db=db_session,
                tenant=tenant,
            )
            assert {item.event_type for item in history} >= {
                "task.kanban_updated",
                "task.comment_added",
            }

            claim = await claim_available_task(
                body=TaskClaimRequest(agent_id="agent-1"),
                user=user,
                db=db_session,
                tenant=tenant,
            )
            assert claim.claimed is True
            assert claim.task is not None
            assert claim.task.kanban_status == "in_progress"

            overdue = await notify_overdue_tasks(db=db_session, tenant=tenant)
            assert overdue.scanned >= 1
            assert overdue.notified >= 1
            assert notify.await_count >= 1

        metrics = await get_kanban_metrics(limit=1000, db=db_session, tenant=tenant)
        assert metrics.total >= 3
        assert metrics.status_counts["review"] >= 1
        assert metrics.workload_by_assignee["agent-1"] >= 1

        exported_json = await export_kanban_tasks(
            format="json",
            kanban_status=None,
            limit=1000,
            db=db_session,
            tenant=tenant,
        )
        exported = json.loads(exported_json.body)
        assert any(item["description"] == "kanban-direct" for item in exported["items"])

        exported_csv = await export_kanban_tasks(
            format="csv",
            kanban_status="review",
            limit=1000,
            db=db_session,
            tenant=tenant,
        )
        assert b"kanban-direct" in exported_csv.body

        import_request = JsonRequest(
            KanbanTaskImportRequest(
                items=[
                    {
                        "title": "Imported task",
                        "description": "imported direct",
                        "graph_type": "research",
                        "kanban_status": "todo",
                        "priority": "medium",
                        "labels": ["imported"],
                    }
                ]
            ).model_dump()
        )
        imported = await import_kanban_tasks(
            request=import_request,  # type: ignore[arg-type]
            format="json",
            user=user,
            db=db_session,
            tenant=tenant,
        )
        assert imported.created == 1
        assert imported.tasks[0].status == "backlog"

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
        """Direct call to ``reap_stale_tasks``.

        Phase 1.5 / migration 0028: the endpoint opens its own
        ``admin_session()`` against the BYPASSRLS pool instead of
        receiving a session via ``Depends(get_db)``. Spy on the
        helper at the module level so the test session is reused
        without a second engine.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        from nexus_api import database as db_module
        from nexus_api.routers.swarms import reap_stale_tasks

        old = SwarmTask(
            description="old-direct", graph_type="research", assigned_agent_ids=[],
            payload={}, status="queued", org_id="dev-org",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db_session.add(old)
        await db_session.commit()

        @asynccontextmanager
        async def _spy_admin_session():
            async with db_module.async_session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        # Caller must hold an allowed role (service / worker / platform / admin).
        platform_caller = {"sub": "ops-cron", "roles": ["service"], "org_id": "platform"}
        with patch.object(db_module, "admin_session", _spy_admin_session):
            out = await reap_stale_tasks(user=platform_caller)
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
            request.headers = {"Authorization": "Bearer user-jwt-token"}
            tenant = TenantContext(org_id="dev-org")
            user = {"sub": "user-123", "roles": ["admin"], "org_id": "dev-org"}
            body = DispatchRequest(
                description="direct dispatch",
                graph_type="research",
            )
            out = await dispatch_task(
                body=body,
                request=request,
                db=db_session,
                tenant=tenant,
                user=user,
            )
        assert out.status in ("queued", "pending")
        # The Redis xadd was attempted.
        mock_pool.execute_with_retry.assert_awaited_once()
        _, _, fields = mock_pool.execute_with_retry.await_args.args
        envelope = json.loads(fields["data"])
        assert envelope["user_jwt"] == "user-jwt-token"
