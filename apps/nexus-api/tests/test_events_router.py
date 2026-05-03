"""Tests for the events observability router.

Covers POST /api/v1/events (create), GET /api/v1/events (list with filters),
and GET /api/v1/events/tasks/{task_id}/timeline (task timeline with aggregates).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

# -- Helpers ----------------------------------------------------------------


def _make_event(
    event_type: str = "node_start",
    event_category: str = "lifecycle",
    **overrides: object,
) -> dict:
    """Build a minimal valid CreateEventRequest payload."""
    body: dict = {
        "event_type": event_type,
        "event_category": event_category,
    }
    body.update(overrides)
    return body


# ==========================================================================
# POST /api/v1/events
# ==========================================================================


@pytest.mark.asyncio
class TestCreateEvent:
    """Tests for POST /api/v1/events."""

    async def test_create_event_requires_auth(self, client: httpx.AsyncClient) -> None:
        """POST /events without auth is rejected."""
        resp = await client.post("/api/v1/events/", json=_make_event())
        assert resp.status_code in (401, 403)

    async def test_create_event_returns_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Minimal event creation returns 201 with an id field."""
        resp = await client.post(
            "/api/v1/events/",
            json=_make_event(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        # The id must be a valid UUID string.
        uuid.UUID(body["id"])

    async def test_create_event_all_fields(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Event with every optional field populated returns 201."""
        task_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        payload = _make_event(
            event_type="llm_call",
            event_category="inference",
            task_id=task_id,
            agent_id=agent_id,
            node_id="implement",
            graph_type="coding",
            payload={"prompt_tokens": 100, "completion_tokens": 50},
            duration_ms=1500,
            provider="openai",
            model="gpt-4o",
            token_count=150,
            error_message=None,
            request_id="req-abc-123",
            # org_id deliberately omitted: server derives it from the
            # authenticated caller.
        )
        resp = await client.post("/api/v1/events/", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        assert "id" in resp.json()

    async def test_create_event_required_fields_only(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Only event_type and event_category are required."""
        resp = await client.post(
            "/api/v1/events/",
            json={"event_type": "task_start", "event_category": "lifecycle"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def test_create_event_missing_event_type_422(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Missing required event_type triggers 422 validation error."""
        resp = await client.post(
            "/api/v1/events/",
            json={"event_category": "lifecycle"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_event_missing_event_category_422(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Missing required event_category triggers 422 validation error."""
        resp = await client.post(
            "/api/v1/events/",
            json={"event_type": "node_start"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_event_invalid_task_id_treated_as_null(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A non-UUID task_id is silently coerced to None via _safe_uuid."""
        resp = await client.post(
            "/api/v1/events/",
            json=_make_event(task_id="not-a-uuid"),
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # Fetch the event back -- task_id should be None.
        event_id = resp.json()["id"]
        events = await client.get(
            "/api/v1/events/",
            headers=auth_headers,
        )
        found = [e for e in events.json() if e["id"] == event_id]
        assert len(found) == 1
        assert found[0]["task_id"] is None

    async def test_create_event_org_id_derived_from_caller(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """org_id is derived server-side from the authenticated caller.

        With dev-bypass the caller resolves to org_id="dev-org" -- callers
        cannot override this via the request body (the field is no longer
        accepted on CreateEventRequest).
        """
        resp = await client.post(
            "/api/v1/events/",
            json={
                "event_type": "test_evt",
                "event_category": "test_cat",
                # Attempting to inject a different org_id is silently ignored
                # because the field is not on the schema; if pydantic strict
                # mode is on it would 422 -- either way is safe.
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]

        events = await client.get("/api/v1/events/", headers=auth_headers)
        found = [e for e in events.json() if e["id"] == event_id]
        assert len(found) == 1
        assert found[0]["org_id"] == "dev-org"


# ==========================================================================
# GET /api/v1/events
# ==========================================================================


@pytest.mark.asyncio
class TestListEvents:
    """Tests for GET /api/v1/events (requires auth)."""

    async def test_list_events_empty(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Empty DB returns an empty list."""
        resp = await client.get("/api/v1/events/", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_events_requires_auth(self, client: httpx.AsyncClient) -> None:
        """GET /events without auth is rejected."""
        resp = await client.get("/api/v1/events/")
        assert resp.status_code in (401, 403)

    async def test_list_events_returns_created(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Events created via POST appear in the list."""
        for i in range(3):
            await client.post(
                "/api/v1/events/",
                json=_make_event(event_type=f"evt_{i}"),
                headers=auth_headers,
            )

        resp = await client.get("/api/v1/events/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    async def test_filter_by_event_type(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Filtering by event_type narrows the result set."""
        await client.post(
            "/api/v1/events/", json=_make_event(event_type="llm_call"), headers=auth_headers
        )
        await client.post(
            "/api/v1/events/", json=_make_event(event_type="node_end"), headers=auth_headers
        )

        resp = await client.get(
            "/api/v1/events/",
            params={"event_type": "llm_call"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "llm_call"

    async def test_filter_by_event_category(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Filtering by event_category narrows the result set."""
        await client.post(
            "/api/v1/events/",
            json=_make_event(event_category="inference"),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/events/",
            json=_make_event(event_category="lifecycle"),
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/events/",
            params={"event_category": "inference"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_category"] == "inference"

    async def test_filter_by_task_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Filtering by task_id returns only matching events."""
        task_a = str(uuid.uuid4())
        task_b = str(uuid.uuid4())
        await client.post("/api/v1/events/", json=_make_event(task_id=task_a), headers=auth_headers)
        await client.post("/api/v1/events/", json=_make_event(task_id=task_b), headers=auth_headers)

        resp = await client.get(
            "/api/v1/events/",
            params={"task_id": task_a},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["task_id"] == task_a

    async def test_pagination_limit(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The limit query parameter caps the number of results."""
        for _ in range(8):
            await client.post("/api/v1/events/", json=_make_event(), headers=auth_headers)

        resp = await client.get(
            "/api/v1/events/",
            params={"limit": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 5

    async def test_pagination_offset(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The offset query parameter skips leading results."""
        for i in range(4):
            await client.post(
                "/api/v1/events/",
                json=_make_event(event_type=f"evt_{i}"),
                headers=auth_headers,
            )

        all_resp = await client.get("/api/v1/events/", headers=auth_headers)
        all_data = all_resp.json()

        resp = await client.get(
            "/api/v1/events/",
            params={"offset": 1},
            headers=auth_headers,
        )
        data = resp.json()
        # One fewer because we skipped the first (newest).
        assert len(data) == len(all_data) - 1


# ==========================================================================
# GET /api/v1/events/tasks/{task_id}/timeline
# ==========================================================================


@pytest.mark.asyncio
class TestTaskTimeline:
    """Tests for GET /api/v1/events/tasks/{task_id}/timeline."""

    async def test_timeline_invalid_uuid_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A malformed task_id returns 400."""
        resp = await client.get(
            "/api/v1/events/tasks/bad-uuid/timeline",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid UUID"

    async def test_timeline_empty_for_unknown_task(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A valid UUID with no events returns an empty timeline."""
        task_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/events/tasks/{task_id}/timeline",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == task_id
        assert body["events"] == []
        assert body["total_duration_ms"] is None
        assert body["total_tokens"] is None

    async def test_timeline_ordering_and_aggregates(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Multiple events for the same task appear chronologically with aggregated totals."""
        task_id = str(uuid.uuid4())

        # Create events with duration and token counts.
        await client.post(
            "/api/v1/events/",
            json=_make_event(task_id=task_id, duration_ms=100, token_count=50),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/events/",
            json=_make_event(task_id=task_id, duration_ms=200, token_count=75),
            headers=auth_headers,
        )

        resp = await client.get(
            f"/api/v1/events/tasks/{task_id}/timeline",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == task_id
        assert len(body["events"]) == 2

        # Aggregates should sum the individual values.
        assert body["total_duration_ms"] == 300
        assert body["total_tokens"] == 125

        # Timeline order is ascending (oldest first).
        ts0 = body["events"][0]["created_at"]
        ts1 = body["events"][1]["created_at"]
        assert ts0 <= ts1

    async def test_timeline_requires_auth(self, client: httpx.AsyncClient) -> None:
        """Timeline endpoint requires authentication."""
        task_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/events/tasks/{task_id}/timeline")
        assert resp.status_code in (401, 403)


# ============================================================================
# Tenant-scoping regression tests (commit f35f1b1, wave 3B-B).
#
# Pre-fix: GET /events and GET /events/tasks/{id}/timeline did NOT scope
# their queries by org_id, so any authed user (including guests) could
# read any tenant's observability stream. CreateEventRequest accepted
# org_id from the body.
#
# Post-fix: both endpoints depend on get_tenant + .where(org_id == tenant);
# the body schema no longer declares org_id.
# ============================================================================


def _seed_event_for_org(org_id: str, db_session, **overrides) -> str:
    """Insert a TaskEvent directly with a chosen org_id (bypasses auth)."""
    from nexus_api.models import TaskEvent

    ev = TaskEvent(
        event_type=overrides.get("event_type", "test_evt"),
        event_category=overrides.get("event_category", "test_cat"),
        org_id=org_id,
    )
    db_session.add(ev)
    return str(ev)


@pytest.mark.asyncio
class TestEventsTenantScoping:
    async def test_get_events_filters_by_caller_org(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Events from another tenant MUST NOT appear in the caller's GET.

        Seeds two events: one owned by ``dev-org`` (the dev-bypass
        caller's tenant) and one owned by ``other-tenant``. The GET
        response must contain only the dev-org event.
        """
        from nexus_api.models import TaskEvent

        # Seed an event in dev-org (caller's tenant).
        own_ev = TaskEvent(
            event_type="own_event",
            event_category="lifecycle",
            org_id="dev-org",
        )
        db_session.add(own_ev)
        # Seed an event in a foreign tenant.
        foreign_ev = TaskEvent(
            event_type="foreign_event",
            event_category="lifecycle",
            org_id="other-tenant",
        )
        db_session.add(foreign_ev)
        await db_session.commit()

        resp = await client.get("/api/v1/events/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        types = {e["event_type"] for e in data}
        assert "own_event" in types
        assert "foreign_event" not in types, (
            "Cross-tenant event leaked into GET /events response — "
            "tenant scoping has regressed."
        )

    async def test_get_timeline_filters_by_caller_org(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """A task whose events live in another tenant returns an empty timeline.

        The endpoint deliberately returns an empty timeline (not 404)
        for unknown/foreign task IDs to avoid leaking the existence of
        cross-tenant task IDs. We assert the cross-tenant events are
        NOT included even when they share the same task_id.
        """
        import uuid as _uuid

        from nexus_api.models import TaskEvent

        task_id = _uuid.uuid4()
        # Both events share the same task_id but live in different tenants.
        db_session.add(
            TaskEvent(
                task_id=task_id,
                event_type="own_node",
                event_category="lifecycle",
                org_id="dev-org",
                duration_ms=10,
                token_count=5,
            )
        )
        db_session.add(
            TaskEvent(
                task_id=task_id,
                event_type="foreign_node",
                event_category="lifecycle",
                org_id="other-tenant",
                duration_ms=999,
                token_count=999,
            )
        )
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/events/tasks/{task_id}/timeline",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        types = {e["event_type"] for e in body["events"]}
        assert "own_node" in types
        assert "foreign_node" not in types
        # Aggregates must reflect only the caller's tenant rows.
        assert body["total_duration_ms"] == 10
        assert body["total_tokens"] == 5

    async def test_create_event_uses_caller_org_not_body(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Body-injected ``org_id`` MUST be ignored.

        Pydantic 2 default behaviour drops unknown fields silently,
        but we test the END-TO-END outcome: the persisted row has the
        caller's org_id, not the smuggled value. This protects against
        a future schema change to ``extra="allow"`` that would silently
        re-open the cross-tenant write hole.
        """
        resp = await client.post(
            "/api/v1/events/",
            json={
                "event_type": "tenant_iso_evt",
                "event_category": "test_cat",
                # Hostile field — must be ignored.
                "org_id": "victim-org-9999",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]

        # GET back as dev-org caller — the row must be visible
        # (proving it was written under dev-org, not victim-org).
        listing = await client.get("/api/v1/events/", headers=auth_headers)
        assert listing.status_code == 200
        found = [e for e in listing.json() if e["id"] == event_id]
        assert len(found) == 1
        assert found[0]["org_id"] == "dev-org"
        assert found[0]["org_id"] != "victim-org-9999"
