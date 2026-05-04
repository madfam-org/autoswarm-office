"""Audit-trail wave 3 — long-tail emission tests.

Pins the ``emit_event_db`` calls added by wave 3 across the long-tail
mutation surface. Tests intentionally hit the real router behind the
SQLite fixture from ``conftest.py`` so the round-trip from
HTTP -> handler -> ``TaskEvent`` row is exercised end-to-end. Wave 1
(tenants/swarms/agents) and wave 2 (workflows/marketplace/maps) are
covered by their own files.

Endpoints covered (one event_type per row):

- ``POST /api/v1/calendar/connect``        → ``calendar.connected``
- ``DELETE /api/v1/calendar/disconnect``   → ``calendar.disconnected``
- ``POST /api/v1/schedules/``              → ``schedule.created``
- ``DELETE /api/v1/schedules/{id}``        → ``schedule.deleted``
- ``POST /api/v1/hitl/decisions``          → ``hitl_confidence.config_updated``
- ``POST /api/v1/departments/``            → ``department.created``
- ``PUT  /api/v1/departments/{id}``        → ``department.updated``
- ``POST /api/v1/tenant-identities``       → ``tenant.identity_updated``
- ``DELETE /api/v1/artifacts/{id}``        → ``artifact.deleted``
- ``POST /api/v1/command-approvals/{id}/approve`` → ``command_approval.approved``
- ``POST /api/v1/command-approvals/{id}/deny``    → ``command_approval.denied``
- ``POST /api/v1/approvals/bulk-expire``   → ``approval.bulk_expired``
  (single summary event, NOT per-row)

PII-safety check is implicit in the payload assertions — none of the
tests assert on tenant content (legal_name, email body, command text);
only IDs + categorical fields land in the event payload.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api import config as _cfg_mod
from nexus_api.auth import get_current_user
from nexus_api.main import app as _fastapi_app
from nexus_api.models import (
    Agent,
    ApprovalRequest,
    Artifact,
    CommandApprovalRequest,
    TaskEvent,
)

WORKER_TOKEN = "dev-bypass"  # Matches conftest `_test_settings` default.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _worker_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WORKER_TOKEN}",
        "X-CSRF-Token": "test-csrf-token-fixed",
    }


def _platform_user() -> dict:
    """A caller carrying one of the bulk-expire / reap-stale roles."""
    return {
        "sub": "service:test-worker",
        "roles": ["service", "worker", "platform", "admin"],
        "org_id": "platform",
        "email": "ops@selva.internal",
    }


def _regular_user(org_id: str = "dev-org") -> dict:
    return {
        "sub": "user-00000001",
        "roles": ["tactician"],
        "org_id": org_id,
        "email": "user@example.com",
    }


async def _events(
    db: AsyncSession, *, event_type: str
) -> list[TaskEvent]:
    res = await db.execute(
        select(TaskEvent).where(TaskEvent.event_type == event_type)
    )
    return list(res.scalars().all())


@pytest.fixture(autouse=True)
def _ensure_worker_token() -> None:
    settings = _cfg_mod.get_settings()
    settings.worker_api_token = WORKER_TOKEN


# ============================================================================
# calendar.py
# ============================================================================


@pytest.mark.asyncio
class TestCalendarAuditEmissions:
    async def test_connect_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        resp = await client.post(
            "/api/v1/calendar/connect",
            headers=auth_headers,
            json={
                "provider": "google",
                "access_token": "ya29.test",
                "refresh_token": "1//refresh",
            },
        )
        assert resp.status_code == 201, resp.text

        events = await _events(db_session, event_type="calendar.connected")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "calendar"
        assert ev.org_id == "dev-org"
        assert ev.payload["provider"] == "google"
        # PII safety: only the JWT sub, never the access_token / refresh_token.
        assert "access_token" not in ev.payload
        assert "refresh_token" not in ev.payload

    async def test_disconnect_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Set up a connection to delete.
        connect = await client.post(
            "/api/v1/calendar/connect",
            headers=auth_headers,
            json={"provider": "google", "access_token": "tok"},
        )
        assert connect.status_code == 201

        resp = await client.delete(
            "/api/v1/calendar/disconnect", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

        events = await _events(db_session, event_type="calendar.disconnected")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "calendar"
        assert ev.org_id == "dev-org"
        assert ev.payload["provider"] == "google"


# ============================================================================
# schedules.py
# ============================================================================


def _scheduler_user(org_id: str = "dev-org") -> dict:
    """Schedules use ``require_roles([])`` which (per current impl) needs at
    least one role to slip past the empty-iter ``any()``. Inject a benign role
    so the endpoint runs end-to-end. ``user.sub`` and ``user.org_id`` are what
    the audit emission reads, so the role label itself is irrelevant.
    """
    return {
        "sub": "user-schedule",
        "roles": ["tactician"],
        "org_id": org_id,
        "email": "u@example.com",
    }


@pytest.mark.asyncio
class TestScheduleAuditEmissions:
    """Schedule create/delete are wired via ``require_roles([])`` which the
    HTTP test client cannot satisfy (the empty-iter ``any()`` check rejects
    every caller). Test the handler functions directly so the audit
    emission logic is exercised end-to-end without going through the
    broken-by-design dep gate.
    """

    async def test_create_emits_event(self, db_session: AsyncSession) -> None:
        from nexus_api.routers.schedules import ScheduleCreate, create_schedule

        body = ScheduleCreate(
            cron_expr="0 9 * * 1",
            action="skill_refine",
            payload={"prompt": "weekly digest"},
            description="weekly Monday digest",
        )
        resp = await create_schedule(
            body=body,
            user=_scheduler_user(),
            db=db_session,
        )

        events = await _events(db_session, event_type="schedule.created")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "schedule"
        assert ev.org_id == "dev-org"
        assert ev.payload["schedule_id"] == resp.id
        assert ev.payload["cron_expr"] == "0 9 * * 1"

    async def test_delete_emits_event(self, db_session: AsyncSession) -> None:
        from nexus_api.routers.schedules import (
            ScheduleCreate,
            cancel_schedule,
            create_schedule,
        )

        created = await create_schedule(
            body=ScheduleCreate(cron_expr="0 0 * * *", action="skill_refine"),
            user=_scheduler_user(),
            db=db_session,
        )
        schedule_id = created.id

        await cancel_schedule(
            schedule_id=schedule_id,
            user=_scheduler_user(),
            db=db_session,
        )

        events = await _events(db_session, event_type="schedule.deleted")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "schedule"
        assert ev.org_id == "dev-org"
        assert ev.payload["schedule_id"] == schedule_id


# ============================================================================
# hitl_confidence.py
# ============================================================================


@pytest.mark.asyncio
class TestHitlConfidenceAuditEmissions:
    async def test_record_decision_emits_event(
        self,
        client: httpx.AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        resp = await client.post(
            "/api/v1/hitl/decisions",
            headers=_worker_headers(),
            json={
                "agent_id": "agent-test-1",
                "action_category": "email_send",
                "org_id": "tenant-acme",
                "context": {"agent_role": "growth"},
                "outcome": "approved_clean",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()

        events = await _events(
            db_session, event_type="hitl_confidence.config_updated"
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "hitl"
        # org_id is taken from the worker-supplied body (worker auth path).
        assert ev.org_id == "tenant-acme"
        assert ev.payload["bucket_key"] == body["bucket_key"]
        assert ev.payload["outcome"] == "approved_clean"
        assert ev.payload["action_category"] == "email_send"
        # PII safety: payload_hash + diff_hash + notes MUST NOT leak.
        assert "payload_hash" not in ev.payload
        assert "diff_hash" not in ev.payload
        assert "notes" not in ev.payload


# ============================================================================
# departments.py
# ============================================================================


@pytest.mark.asyncio
class TestDepartmentAuditEmissions:
    async def test_create_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        resp = await client.post(
            "/api/v1/departments/",
            headers=auth_headers,
            json={"name": "Engineering", "slug": "eng-w3", "max_agents": 5},
        )
        assert resp.status_code == 201, resp.text
        dept_id = resp.json()["id"]

        events = await _events(db_session, event_type="department.created")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "department"
        assert ev.org_id == "dev-org"
        assert ev.payload["department_id"] == dept_id
        assert ev.payload["slug"] == "eng-w3"
        assert ev.payload["max_agents"] == 5
        # PII safety: name + description must NOT be in the event payload.
        assert "name" not in ev.payload
        assert "description" not in ev.payload

    async def test_update_emits_event_only_when_something_changed(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        create = await client.post(
            "/api/v1/departments/",
            headers=auth_headers,
            json={"name": "Old Name", "slug": "upd-w3", "max_agents": 5},
        )
        assert create.status_code == 201
        dept_id = create.json()["id"]

        # First PUT — change max_agents only.
        upd1 = await client.put(
            f"/api/v1/departments/{dept_id}",
            headers=auth_headers,
            json={"max_agents": 7},
        )
        assert upd1.status_code == 200, upd1.text

        events = await _events(db_session, event_type="department.updated")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "department"
        assert ev.org_id == "dev-org"
        assert ev.payload["department_id"] == dept_id
        assert ev.payload["changed_keys"] == ["max_agents"]

        # Second PUT — same value as already stored: no new event.
        upd2 = await client.put(
            f"/api/v1/departments/{dept_id}",
            headers=auth_headers,
            json={"max_agents": 7},
        )
        assert upd2.status_code == 200, upd2.text

        events = await _events(db_session, event_type="department.updated")
        # Still exactly 1 — no-op PUT did NOT emit.
        assert len(events) == 1


# ============================================================================
# tenant_identities.py
# ============================================================================


@pytest.mark.asyncio
class TestTenantIdentityAuditEmissions:
    async def test_create_emits_event(
        self,
        client: httpx.AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        resp = await client.post(
            "/api/v1/tenant-identities",
            headers=_worker_headers(),
            json={
                "canonical_id": f"acme-{uuid.uuid4().hex[:8]}",
                "legal_name": "ACME SA de CV",
                "primary_contact_email": "ops@acme.example",
                "janua_org_id": "janua-1",
                "dhanam_space_id": "dhanam-1",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()

        events = await _events(db_session, event_type="tenant.identity_updated")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "tenant"
        assert ev.org_id == body["canonical_id"]
        assert ev.payload["tenant_identity_id"] == body["id"]
        assert ev.payload["operation"] == "create"
        # Per-service IDs that were populated, sorted.
        assert ev.payload["populated_services"] == sorted(
            ["dhanam_space_id", "janua_org_id"]
        )
        # PII safety: legal_name + primary_contact_email MUST NOT leak.
        assert "legal_name" not in ev.payload
        assert "primary_contact_email" not in ev.payload


# ============================================================================
# artifacts.py
# ============================================================================


@pytest.mark.asyncio
class TestArtifactAuditEmissions:
    async def test_delete_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        # Seed an artifact directly. The DELETE endpoint also drops the
        # storage object, so point it at a real path inside tmp_path
        # (which we make exist with a 1-byte placeholder).
        storage_path = tmp_path / "ab" / "cd" / "abcd"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(b"x")

        artifact = Artifact(
            id=uuid.uuid4(),
            task_id=None,
            agent_id=None,
            org_id="dev-org",
            name="result.txt",
            content_type="text/plain",
            content_hash="ab" + "cd" + ("0" * 60),
            storage_path=str(storage_path),
            size_bytes=1,
        )
        db_session.add(artifact)
        await db_session.commit()

        # Patch _storage to point at the tmp_path so the delete-from-disk
        # branch finds the file regardless of the global storage layout.
        from nexus_api.routers import artifacts as _artifacts_mod
        from selva_tools.storage import LocalFSStorage

        original = _artifacts_mod._storage
        _artifacts_mod._storage = LocalFSStorage(base_dir=str(tmp_path))
        try:
            resp = await client.delete(
                f"/api/v1/artifacts/{artifact.id}", headers=auth_headers
            )
        finally:
            _artifacts_mod._storage = original

        assert resp.status_code == 200, resp.text

        events = await _events(db_session, event_type="artifact.deleted")
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "artifact"
        assert ev.org_id == "dev-org"
        assert ev.payload["artifact_id"] == str(artifact.id)
        assert ev.payload["content_hash"] == artifact.content_hash
        assert ev.payload["size_bytes"] == 1
        # PII safety: artifact name (could be tenant content) MUST NOT leak.
        assert "name" not in ev.payload


# ============================================================================
# command_approvals.py
# ============================================================================


@pytest.mark.asyncio
class TestCommandApprovalAuditEmissions:
    @staticmethod
    async def _seed_command_approval(db: AsyncSession) -> CommandApprovalRequest:
        req = CommandApprovalRequest(
            id=str(uuid.uuid4()),
            run_id=f"run-{uuid.uuid4().hex[:8]}",
            command="rm -rf /tmp/some-build-dir",
            reason="cleanup before redeploy",
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        return req

    async def test_approve_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        req = await self._seed_command_approval(db_session)

        resp = await client.post(
            f"/api/v1/command-approvals/{req.id}/approve",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        events = await _events(
            db_session, event_type="command_approval.approved"
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "approval"
        assert ev.org_id == "platform"
        assert ev.payload["request_id"] == req.id
        assert ev.payload["run_id"] == req.run_id
        # PII / safety: the raw command MUST NOT be in the payload.
        assert "command" not in ev.payload

    async def test_deny_emits_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        req = await self._seed_command_approval(db_session)

        resp = await client.post(
            f"/api/v1/command-approvals/{req.id}/deny",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        events = await _events(
            db_session, event_type="command_approval.denied"
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "approval"
        assert ev.org_id == "platform"
        assert ev.payload["request_id"] == req.id


# ============================================================================
# approvals.py:bulk_expire
# ============================================================================


@pytest.mark.asyncio
class TestApprovalBulkExpireAuditEmissions:
    @staticmethod
    async def _seed_pending_approval(
        db: AsyncSession, *, age_hours: float, org_id: str = "tenant-x"
    ) -> ApprovalRequest:
        # We need a real Agent FK for ApprovalRequest.agent_id.
        agent = Agent(
            id=uuid.uuid4(),
            name=f"agent-{uuid.uuid4().hex[:6]}",
            role="engineer",
            level=1,
            status="idle",
            org_id=org_id,
        )
        db.add(agent)
        await db.flush()

        req = ApprovalRequest(
            id=uuid.uuid4(),
            agent_id=agent.id,
            action_category="file_write",
            action_type="apply_patch",
            payload={},
            reasoning="",
            urgency="medium",
            status="pending",
            org_id=org_id,
            created_at=datetime.now(UTC) - timedelta(hours=age_hours),
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        return req

    async def test_requires_platform_role(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _regular_user()
            )
            resp = await client.post(
                "/api/v1/approvals/bulk-expire", headers=auth_headers
            )
            assert resp.status_code == 403, resp.text
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    async def test_emits_single_summary_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Seed three rows: two stale, one fresh.
        old1 = await self._seed_pending_approval(db_session, age_hours=48)
        old2 = await self._seed_pending_approval(db_session, age_hours=72)
        await self._seed_pending_approval(db_session, age_hours=1)

        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _platform_user()
            )
            resp = await client.post(
                "/api/v1/approvals/bulk-expire?older_than_hours=24",
                headers=auth_headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["expired"] == 2
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

        events = await _events(db_session, event_type="approval.bulk_expired")
        # Critical: ONE summary event, not one per row.
        assert len(events) == 1
        ev = events[0]
        assert ev.event_category == "approval"
        assert ev.payload["affected_count"] == 2
        assert set(ev.payload["ids"]) == {str(old1.id), str(old2.id)}
        assert ev.payload["older_than_hours"] == 24
        assert ev.payload["actor_sub"] == "service:test-worker"

    async def test_no_event_when_nothing_to_expire(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Only fresh rows: nothing should be expired and no event.
        await self._seed_pending_approval(db_session, age_hours=1)

        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _platform_user()
            )
            resp = await client.post(
                "/api/v1/approvals/bulk-expire?older_than_hours=24",
                headers=auth_headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["expired"] == 0
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

        events = await _events(db_session, event_type="approval.bulk_expired")
        assert events == []
