"""Regression tests for the cross-tenant ``reap-stale`` endpoint fix.

Pre-fix behaviour (the bug from ``docs/RLS_PHASE_1_5_AUDIT.md`` §2.C):
    ``POST /api/v1/swarms/tasks/reap-stale`` had no role gate and
    accepted any authenticated caller. ``Depends(get_db)`` set
    ``app.current_org_id`` to the caller's ``org_id`` (or ``"default"``
    in the dev bypass). Under Postgres RLS this scoped the SELECT to
    ONE org -- in practice always ``"default"`` because no real tenant
    ever calls this endpoint -- so stale tasks in real tenant queues
    accumulated forever.

Post-fix behaviour pinned by these tests:
    1. Anonymous (no Bearer header) returns 401/403 from the router-level
       ``Depends(get_current_user)``.
    2. Authenticated caller without ``service``/``worker``/``platform``/
       ``admin`` role returns 403.
    3. Authenticated caller WITH one of those roles succeeds and reaps
       stale tasks across every tenant in one call.
    4. The endpoint opens an ``admin_session()`` (BYPASSRLS pool) instead
       of a regular tenant-scoped session. This is the Phase 1.5
       (migration 0028) replacement for the Phase 1
       ``set_config('app.current_org_id', '', true)`` hack -- under the
       strict policies the manual reset would return zero rows.
       ``TestReapStaleAdminSessionUsage`` pins the new contract.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from nexus_api.auth import get_current_user
from nexus_api.main import app as _fastapi_app
from nexus_api.models import SwarmTask


def _user_with_roles(roles: list[str], org_id: str = "caller-org") -> dict[str, Any]:
    return {
        "sub": f"user-{uuid.uuid4().hex[:8]}",
        "roles": roles,
        "org_id": org_id,
        "email": "test@example.com",
    }


@pytest.mark.asyncio
class TestReapStaleAuthGate:
    """Authentication is enforced by the router-level dependency."""

    async def test_unauthenticated_returns_401_or_403(
        self, client: httpx.AsyncClient
    ) -> None:
        """No Bearer header -> rejected by router-level get_current_user.

        FastAPI's ``HTTPBearer(auto_error=True)`` returns 403 when the
        Authorization header is missing; some configs return 401. Either
        is acceptable -- the assertion is "not 200, not 500, not silently
        accepted". The dev bypass in conftest does NOT fire because we
        omit the Authorization header entirely.
        """
        resp = await client.post(
            "/api/v1/swarms/tasks/reap-stale",
            # NO auth_headers fixture -- truly anonymous request.
            headers={"X-CSRF-Token": "test-csrf-token-fixed"},
        )
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for anonymous reap-stale; got {resp.status_code}"
        )


@pytest.mark.asyncio
class TestReapStaleRoleGate:
    """Only privileged roles may invoke the cross-tenant reaper."""

    async def test_non_privileged_role_returns_403(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A regular tactician without service/worker/platform/admin -> 403."""
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["tactician"])
            )

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 403
            detail = resp.json().get("detail", "").lower()
            assert "platform" in detail or "service" in detail or "admin" in detail
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    async def test_guest_role_returns_403(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A guest user is explicitly NOT in the allow-list -> 403."""
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["guest"])
            )

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 403
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    async def test_demo_role_returns_403(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A demo user is explicitly NOT in the allow-list -> 403."""
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["demo"])
            )

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 403
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.parametrize("role", ["service", "worker", "platform", "admin"])
    async def test_privileged_role_allowed(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        role: str,
    ) -> None:
        """Each of the four privileged roles in the allow-list passes the gate."""
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles([role])
            )

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 200, (
                f"Role '{role}' should be in the allow-list; got "
                f"{resp.status_code}: {resp.text}"
            )
            assert "reaped" in resp.json()
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
class TestReapStaleCrossTenant:
    """The SELECT must visit every tenant, not just the caller's org."""

    async def test_reaps_stale_tasks_across_orgs(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session,  # type: ignore[no-untyped-def]
    ) -> None:
        """Seed stale tasks in 3 distinct orgs; one reap call must catch all 3.

        SQLite has no RLS, so the SELECT is always cross-tenant in tests
        regardless of the fix. The thing we're validating here is the
        **application-layer** behaviour: the endpoint does NOT add a
        ``WHERE org_id = ...`` clause, so on Postgres+permissive-policy
        and on Postgres+strict-policy-via-app_admin (Phase 1.5) it
        reaches all rows. The Postgres-specific ``admin_session()``
        usage assertion lives in ``TestReapStaleAdminSessionUsage`` below.
        """
        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["service"], org_id="org-A")
            )

            stale_age = datetime.now(UTC) - timedelta(hours=2)
            stale_tasks = [
                SwarmTask(
                    description=f"stale task in {org}",
                    graph_type="research",
                    assigned_agent_ids=[],
                    payload={},
                    status="queued",
                    org_id=org,
                    created_at=stale_age,
                )
                for org in ("org-A", "org-B", "org-C")
            ]
            fresh_task = SwarmTask(
                description="fresh task in org-D",
                graph_type="research",
                assigned_agent_ids=[],
                payload={},
                status="queued",
                org_id="org-D",
            )
            db_session.add_all([*stale_tasks, fresh_task])
            await db_session.commit()

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 200
            assert resp.json()["reaped"] == 3, (
                f"Expected to reap 3 stale tasks across orgs A/B/C; "
                f"got {resp.json()['reaped']}. Pre-fix behaviour "
                f"would have reaped only the caller-org slice."
            )

            for task in (*stale_tasks, fresh_task):
                await db_session.refresh(task)
            for task in stale_tasks:
                assert task.status == "failed", (
                    f"Stale task in {task.org_id} should be failed; "
                    f"got {task.status}"
                )
                assert task.error_message and "stale" in task.error_message.lower()
            assert fresh_task.status == "queued"
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
class TestReapStaleAdminSessionUsage:
    """The endpoint opens ``admin_session()`` instead of ``Depends(get_db)``.

    Phase 1.5 / migration 0028 replaces the Phase 1
    ``set_config('app.current_org_id', '', true)`` hack -- which only
    worked because the permissive policy honoured the NULL / empty-string
    escape hatch -- with the ``app_admin`` BYPASSRLS Postgres role
    accessed via the ``admin_session()`` helper. Under the strict
    policies the old hack returns zero rows.
    """

    async def test_endpoint_no_longer_depends_on_get_db(self) -> None:
        """The handler signature must NOT include ``Depends(get_db)``.

        If ``get_db`` re-appears, ``_set_session_org_id`` writes the
        caller's ``org_id`` into the session var, the strict-mode RLS
        policy then scopes the reap SELECT to that one org, and the
        cross-tenant bug is back.
        """
        import inspect

        from nexus_api.routers.swarms import reap_stale_tasks

        sig = inspect.signature(reap_stale_tasks)
        param_names = set(sig.parameters)
        assert "db" not in param_names, (
            "reap_stale_tasks reverted to Depends(get_db) -- under strict "
            "RLS this scopes the SELECT to the caller's tenant. Use "
            "admin_session() inside the handler body instead."
        )

    async def test_endpoint_opens_admin_session(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """``admin_session()`` is invoked exactly once per call.

        Spies on the helper at the ``nexus_api.database`` module the
        router imports it from. Reuses the SQLite-backed factory inside
        the spy so the endpoint can still flush its updates.
        """
        from nexus_api import database as db_module

        admin_session_calls: list[None] = []

        @asynccontextmanager
        async def _spy_admin_session():
            admin_session_calls.append(None)
            async with db_module.async_session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["service"])
            )
            with patch.object(db_module, "admin_session", _spy_admin_session):
                resp = await client.post(
                    "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
                )

            assert resp.status_code == 200, resp.text
            assert len(admin_session_calls) == 1, (
                f"admin_session() should be invoked exactly once per "
                f"reap-stale call; got {len(admin_session_calls)}"
            )
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)
