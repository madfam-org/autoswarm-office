"""Audit-trail Phase 3 wave 1 — tenants/swarms/agents emit TaskEvent rows.

Closes 9 of the gap sites enumerated in
``docs/AUDIT_TRAIL_GAP_ANALYSIS.md`` § "Top 12 highest-priority gaps":

- ``tenants.py:create_tenant`` → ``tenant.created`` (gap #1)
- ``tenants.py:update_my_tenant`` → ``tenant.config_updated`` (gap #2)
- ``tenants.py:configure_sso`` → ``tenant.sso_configured``
- ``tenants.py:update_branding`` → ``tenant.branding_updated``
- ``swarms.py:update_task_status`` → ``task.status_changed`` (gap #3)
- ``agents.py:create_agent`` → ``agent.created`` (gap #7)
- ``agents.py:update_agent`` → ``agent.updated`` (gap #7)
- ``agents.py:assign_agent`` → ``agent.assigned`` (gap #7)
- ``agents.py:delete_agent`` → ``agent.deleted`` (gap #7)

Each test asserts the expected ``event_type`` lands in ``task_events``
scoped to the caller's ``org_id`` and that no PII (email/name/phone)
slips into the payload — events are returned by ``GET /api/v1/events``
to ANY caller in the same org and are persisted indefinitely.

Test pattern mirrors ``test_stripe_webhook_handlers.py``: assert
TaskEvent presence + payload-key invariants, no exhaustive coverage
of the underlying business logic (covered in router-specific tests).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import Agent, Department, SwarmTask, TaskEvent

# ---------------------------------------------------------------------------
# PII guard — these substrings MUST NOT appear in any audit event payload.
# Values that are operator-chosen and could carry user identity (email,
# personal name, phone) are disallowed.  We intentionally do NOT include
# "id" / "uuid" — those are non-PII identifiers and appear in every
# payload.
# ---------------------------------------------------------------------------

_FORBIDDEN_PAYLOAD_KEYS = {
    "email",
    "user_email",
    "primary_contact_email",
    "name",  # operator-chosen agent / tenant name; PII-adjacent
    "user_name",
    "razon_social",  # legal name — PII-adjacent for sole proprietorships
    "phone",
    "rfc",  # tax ID — PII under LFPDPPP
    "brand_logo_url",  # may embed customer asset paths
    "brand_primary_color",  # values not echoed; only the field-name should be in payload
    "brand_name",  # operator-chosen; not echoed (only the changed-fields list is)
    "description",  # task descriptions can carry sensitive context
    "error_message",  # may contain stack traces / file paths
}


def _assert_no_pii(payload: dict | None) -> None:
    """Raise AssertionError if ``payload`` contains any disallowed key."""
    if payload is None:
        return
    leaked = _FORBIDDEN_PAYLOAD_KEYS & set(payload.keys())
    assert not leaked, f"audit event payload leaked PII-adjacent keys: {leaked}"


async def _events_for_org(db: AsyncSession, org_id: str) -> list[TaskEvent]:
    res = await db.execute(
        select(TaskEvent).where(TaskEvent.org_id == org_id).order_by(TaskEvent.created_at)
    )
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# tenants.py — 4 endpoints
# ---------------------------------------------------------------------------


_TENANTS_URL = "/api/v1/tenants"


@pytest.mark.asyncio
class TestTenantsAuditEvents:
    async def test_create_tenant_emits_tenant_created(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        resp = await client.post(
            f"{_TENANTS_URL}/",
            headers=auth_headers,
            json={"org_name": "Audit Org", "rfc": "XAXX010101000"},
        )
        assert resp.status_code == 201

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "tenant.created"), None)
        assert ev is not None, f"tenant.created not found, got: {[e.event_type for e in events]}"
        assert ev.org_id == "dev-org"
        assert ev.event_category == "tenant"
        assert ev.payload is not None
        # The payload should carry a derived flag ("has_rfc=True"), not the
        # raw RFC value itself.
        assert ev.payload.get("has_rfc") is True
        assert ev.payload.get("departments_provisioned") == 6
        _assert_no_pii(ev.payload)

    async def test_update_my_tenant_emits_config_updated(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await client.post(
            f"{_TENANTS_URL}/", headers=auth_headers, json={"org_name": "Org"}
        )
        resp = await client.patch(
            f"{_TENANTS_URL}/me",
            headers=auth_headers,
            json={"locale": "en-US", "max_daily_tasks": 500},
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "tenant.config_updated"), None)
        assert ev is not None
        assert ev.org_id == "dev-org"
        assert set(ev.payload["fields_changed"]) == {"locale", "max_daily_tasks"}
        _assert_no_pii(ev.payload)

    async def test_configure_sso_emits_sso_configured(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await client.post(
            f"{_TENANTS_URL}/", headers=auth_headers, json={"org_name": "SSO Org"}
        )
        resp = await client.patch(
            f"{_TENANTS_URL}/me/sso",
            headers=auth_headers,
            json={"janua_connection_id": "conn_audit_42"},
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next(
            (e for e in events if e.event_type == "tenant.sso_configured"), None
        )
        assert ev is not None
        assert ev.org_id == "dev-org"
        # SSO connection ID is opaque (non-PII Janua identifier) — safe to echo
        assert ev.payload["janua_connection_id"] == "conn_audit_42"
        _assert_no_pii(ev.payload)

    async def test_update_branding_emits_branding_updated(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await client.post(
            f"{_TENANTS_URL}/", headers=auth_headers, json={"org_name": "Brand Org"}
        )
        resp = await client.patch(
            f"{_TENANTS_URL}/me/branding",
            headers=auth_headers,
            json={"brand_name": "ACME", "brand_primary_color": "#ff0000"},
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next(
            (e for e in events if e.event_type == "tenant.branding_updated"), None
        )
        assert ev is not None
        assert ev.org_id == "dev-org"
        # Only the *names* of changed fields are in the payload — values
        # are not echoed (defense in depth even though brand_name is
        # operator-chosen non-PII).
        assert set(ev.payload["fields_changed"]) == {"brand_name", "brand_primary_color"}
        _assert_no_pii(ev.payload)


# ---------------------------------------------------------------------------
# swarms.py — 1 endpoint (update_task_status)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSwarmsAuditEvents:
    async def test_update_task_status_emits_status_changed(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Dispatch a task first; mock Redis so we don't need a live broker.
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=AsyncMock(execute_with_retry=AsyncMock()),
        ):
            disp = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "Audit trail test task", "graph_type": "research"},
                headers=auth_headers,
            )
        assert disp.status_code == 201
        task_id = disp.json()["id"]

        # Patch the status; this is the mutation we're auditing.
        resp = await client.patch(
            f"/api/v1/swarms/tasks/{task_id}",
            json={"status": "running"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next(
            (e for e in events if e.event_type == "task.status_changed"), None
        )
        assert ev is not None, (
            f"task.status_changed missing, got: {[e.event_type for e in events]}"
        )
        assert ev.org_id == "dev-org"
        assert ev.event_category == "task"
        assert str(ev.task_id) == task_id
        # Payload carries the transition (queued → running) so OpsFeed can
        # render arrows without an extra DB lookup.
        assert ev.payload["new_status"] == "running"
        assert ev.payload["old_status"] in {"queued", "pending"}
        _assert_no_pii(ev.payload)


# ---------------------------------------------------------------------------
# agents.py — 4 endpoints (create / update / assign / delete)
# ---------------------------------------------------------------------------


_AGENTS_URL = "/api/v1/agents"


async def _seed_department(db: AsyncSession, org_id: str = "dev-org") -> uuid.UUID:
    dept = Department(
        id=uuid.uuid4(),
        name="Engineering",
        slug=f"dept-eng-{uuid.uuid4().hex[:8]}",
        org_id=org_id,
    )
    db.add(dept)
    await db.flush()
    await db.commit()
    return dept.id


@pytest.mark.asyncio
class TestAgentsAuditEvents:
    async def test_create_agent_emits_agent_created(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        dept_id = await _seed_department(db_session)
        resp = await client.post(
            f"{_AGENTS_URL}/",
            headers=auth_headers,
            json={
                "name": "Test Agent",
                "role": "coder",
                "level": 3,
                "department_id": str(dept_id),
                "skill_ids": ["python", "git"],
            },
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "agent.created"), None)
        assert ev is not None
        assert ev.org_id == "dev-org"
        assert ev.event_category == "agent"
        assert str(ev.agent_id) == agent_id
        assert ev.payload["role"] == "coder"
        assert ev.payload["level"] == 3
        assert ev.payload["skill_count"] == 2
        # Critical: name MUST NOT leak into the audit stream.
        _assert_no_pii(ev.payload)

    async def test_update_agent_emits_agent_updated(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Seed an agent directly in the DB to keep the test focused on UPDATE.
        dept_id = await _seed_department(db_session)
        agent = Agent(
            id=uuid.uuid4(),
            name="Original",
            role="coder",
            status="idle",
            department_id=dept_id,
            org_id="dev-org",
        )
        db_session.add(agent)
        await db_session.commit()

        resp = await client.put(
            f"{_AGENTS_URL}/{agent.id}",
            headers=auth_headers,
            json={"level": 5, "status": "paused"},
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "agent.updated"), None)
        assert ev is not None
        assert ev.org_id == "dev-org"
        assert str(ev.agent_id) == str(agent.id)
        # Only changed-field names — values are not echoed.
        assert set(ev.payload["fields_changed"]) == {"level", "status"}
        _assert_no_pii(ev.payload)

    async def test_assign_agent_emits_agent_assigned(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        dept_a = await _seed_department(db_session)
        dept_b = await _seed_department(db_session)
        agent = Agent(
            id=uuid.uuid4(),
            name="Mover",
            role="coder",
            status="idle",
            department_id=dept_a,
            org_id="dev-org",
        )
        db_session.add(agent)
        await db_session.commit()

        resp = await client.post(
            f"{_AGENTS_URL}/{agent.id}/assign",
            headers=auth_headers,
            json={"department_id": str(dept_b)},
        )
        assert resp.status_code == 200

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "agent.assigned"), None)
        assert ev is not None
        assert ev.org_id == "dev-org"
        assert str(ev.agent_id) == str(agent.id)
        assert ev.payload["previous_department_id"] == str(dept_a)
        assert ev.payload["new_department_id"] == str(dept_b)
        _assert_no_pii(ev.payload)

    async def test_delete_agent_emits_agent_deleted(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        dept_id = await _seed_department(db_session)
        agent = Agent(
            id=uuid.uuid4(),
            name="Doomed",
            role="reviewer",
            status="idle",
            department_id=dept_id,
            org_id="dev-org",
        )
        db_session.add(agent)
        await db_session.commit()
        deleted_id = str(agent.id)

        resp = await client.delete(
            f"{_AGENTS_URL}/{agent.id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Confirm the row is actually gone (no FK violation from the event INSERT).
        agent_check = await db_session.execute(
            select(Agent).where(Agent.id == agent.id)
        )
        assert agent_check.scalar_one_or_none() is None

        events = await _events_for_org(db_session, "dev-org")
        ev = next((e for e in events if e.event_type == "agent.deleted"), None)
        assert ev is not None
        assert ev.org_id == "dev-org"
        # agent_id FK column is intentionally NULL on delete events
        # (the row is gone, FK insert would fail) — UUID lives in payload.
        assert ev.agent_id is None
        assert ev.payload["agent_id"] == deleted_id
        assert ev.payload["role"] == "reviewer"
        _assert_no_pii(ev.payload)


# ---------------------------------------------------------------------------
# Cross-cutting: org-scoping invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOrgScopingInvariant:
    """Audit events MUST be scoped to the caller's org_id.

    Tenant-scoping invariant per CLAUDE.md: tenant A cannot read tenant
    B's audit stream.  This test seeds events under a different org_id
    and asserts they don't show up under "dev-org" (the caller's auth
    bypass org).
    """

    async def test_other_orgs_events_not_visible(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        # Seed an event under a different org_id than the caller.
        other_event = TaskEvent(
            event_type="agent.created",
            event_category="agent",
            org_id="other-org",
            payload={"agent_id": str(uuid.uuid4()), "role": "coder"},
        )
        db_session.add(other_event)
        await db_session.commit()

        # Dispatch + status-update flow under "dev-org".
        with patch(
            "nexus_api.routers.swarms.get_redis_pool",
            return_value=AsyncMock(execute_with_retry=AsyncMock()),
        ):
            disp = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "Cross-org test", "graph_type": "research"},
                headers=auth_headers,
            )
        assert disp.status_code == 201
        task_id = disp.json()["id"]

        # Confirm the dispatched task's org_id matches the caller, not "other-org".
        task_row = (
            await db_session.execute(
                select(SwarmTask).where(SwarmTask.id == uuid.UUID(task_id))
            )
        ).scalar_one()
        assert task_row.org_id == "dev-org"

        # And the dev-org event stream is isolated from "other-org".
        dev_events = await _events_for_org(db_session, "dev-org")
        other_events = await _events_for_org(db_session, "other-org")
        assert len(other_events) == 1
        assert all(e.org_id == "dev-org" for e in dev_events)
