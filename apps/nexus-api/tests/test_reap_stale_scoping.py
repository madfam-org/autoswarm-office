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
    4. On a Postgres bind the endpoint resets ``app.current_org_id``
       to ``''`` before the SELECT so the Phase 1 permissive policy
       (``IS NULL OR = '' OR = $org``) returns rows from every tenant.
       (SQLite test path: assertion is structural, not behavioural --
       SQLite has no RLS, so we mock the bind to verify the SQL is
       emitted on the Postgres branch.)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

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
        """A regular tactician without service/worker/platform/admin -> 403.

        Pre-fix any logged-in user could trigger the reaper. Post-fix the
        role allow-list rejects everyone except the four privileged
        roles, so a tactician-only user is rejected.
        """
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
        """Each of the four privileged roles in the allow-list passes the gate.

        Asserts 200 (not 403). Doesn't seed any stale tasks -- the reap
        count is allowed to be 0; what we're pinning here is that the
        role check itself does not reject the request.
        """
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

        This is the core regression test. Pre-fix the endpoint scoped to
        the caller's org, so 3 stale tasks in 3 different orgs would
        only have the caller-org one reaped. Post-fix the session var
        is reset so the policy permits all rows.

        Note on the test DB: SQLite has no RLS, so the SELECT is
        always cross-tenant in tests regardless of the fix. The thing
        we're validating here is the **application-layer** behaviour:
        the endpoint does NOT add a ``WHERE org_id = ...`` clause, so
        on Postgres+permissive-policy it reaches all rows, and on
        Postgres+strict-policy (Phase 1.5) it would also reach all rows
        once the BYPASSRLS path is wired. The Postgres-specific session
        var assertion lives in ``TestReapStaleSessionVarBypass`` below.
        """
        try:
            # Caller is org-A but we expect stale tasks from B and C
            # to also be reaped.
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
            # Sanity control: a fresh task in yet another org must NOT
            # be reaped (status check, not org check).
            fresh_task = SwarmTask(
                description="fresh task in org-D",
                graph_type="research",
                assigned_agent_ids=[],
                payload={},
                status="queued",
                org_id="org-D",
                # default created_at = now -> not stale
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

            # Verify each stale task is now failed and the fresh one
            # is untouched.
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
class TestReapStaleSessionVarBypass:
    """The Postgres-only branch resets the RLS session var to ''."""

    async def test_postgres_bind_emits_empty_session_var_set(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """When the session is bound to Postgres, ``set_config('app.current_org_id', '', true)``
        is emitted before the reap SELECT.

        We can't run real Postgres in this test suite, so we monkey-patch
        the test session's ``get_bind()`` to claim a Postgres dialect and
        intercept ``execute()`` calls to capture the SQL strings. The
        invariant: the very first ``execute()`` MUST be the
        ``set_config`` reset; without it the reap query runs under the
        caller's tenant scope and the bug is back.
        """
        from nexus_api.database import async_session_factory

        # Capture every text() statement passed to db.execute via a wrapper
        # session whose get_bind() claims to be Postgres. We don't override
        # the session itself -- we override get_db so the endpoint receives
        # a session whose underlying behaviour is sqlite but whose
        # introspection lies about the dialect. That's enough to push the
        # endpoint down the Postgres branch.
        executed_statements: list[str] = []

        async def _spy_get_db():
            async with async_session_factory() as session:
                real_execute = session.execute
                real_get_bind = session.get_bind

                def _fake_get_bind():
                    bind = real_get_bind()
                    if bind is None:
                        return None
                    fake = MagicMock(wraps=bind)
                    fake.dialect = MagicMock()
                    fake.dialect.name = "postgresql"
                    return fake

                async def _capturing_execute(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
                    sql_str = str(statement)
                    executed_statements.append(sql_str)
                    # Skip the set_config call -- SQLite has no such
                    # function, so emitting it would explode. Pretend it
                    # succeeded by returning an empty mock result.
                    if "set_config" in sql_str and "current_org_id" in sql_str:
                        result = MagicMock()
                        result.scalars = MagicMock(return_value=MagicMock(all=lambda: []))
                        return result
                    return await real_execute(statement, *args, **kwargs)

                session.get_bind = _fake_get_bind  # type: ignore[method-assign]
                session.execute = _capturing_execute  # type: ignore[method-assign]
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        from nexus_api.database import get_db

        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["service"])
            )
            _fastapi_app.dependency_overrides[get_db] = _spy_get_db

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 200, resp.text

            # The set_config reset MUST be emitted, AND it MUST come
            # before the SwarmTask SELECT. Pre-fix neither of these was
            # true.
            set_config_idx = next(
                (
                    i
                    for i, sql in enumerate(executed_statements)
                    if "set_config" in sql and "current_org_id" in sql
                ),
                None,
            )
            assert set_config_idx is not None, (
                "Expected SELECT set_config('app.current_org_id', '', true) "
                "before the reap query; the endpoint is back to scoping "
                "the SELECT to the caller's tenant. Statements observed: "
                f"{executed_statements!r}"
            )

            # And the SET must be the empty-string form, not the org_id form.
            set_config_sql = executed_statements[set_config_idx]
            assert "''" in set_config_sql or "'', true" in set_config_sql, (
                f"set_config call must reset the var to ''; "
                f"got {set_config_sql!r}"
            )

            # Find the reap SELECT and verify ordering.
            select_idx = next(
                (
                    i
                    for i, sql in enumerate(executed_statements)
                    if "FROM swarm_tasks" in sql or "from swarm_tasks" in sql.lower()
                ),
                None,
            )
            assert select_idx is not None, (
                "Reap SELECT against swarm_tasks not observed; "
                f"statements: {executed_statements!r}"
            )
            assert set_config_idx < select_idx, (
                "set_config reset MUST run before the reap SELECT, else "
                "the SELECT runs under the caller's tenant scope. "
                f"set_config at {set_config_idx}, SELECT at {select_idx}"
            )
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)
            _fastapi_app.dependency_overrides.pop(get_db, None)

    async def test_sqlite_bind_skips_session_var_set(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """On a SQLite bind (test default), the set_config call is skipped.

        SQLite has no ``set_config`` function, so emitting the reset
        would crash. The endpoint must guard the call with a dialect
        check. This test confirms the SQLite path stays clean.
        """
        from nexus_api.database import async_session_factory

        executed_statements: list[str] = []

        async def _spy_get_db():
            async with async_session_factory() as session:
                real_execute = session.execute

                async def _capturing_execute(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
                    executed_statements.append(str(statement))
                    return await real_execute(statement, *args, **kwargs)

                session.execute = _capturing_execute  # type: ignore[method-assign]
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        from nexus_api.database import get_db

        try:
            _fastapi_app.dependency_overrides[get_current_user] = (
                lambda: _user_with_roles(["service"])
            )
            _fastapi_app.dependency_overrides[get_db] = _spy_get_db

            resp = await client.post(
                "/api/v1/swarms/tasks/reap-stale", headers=auth_headers
            )
            assert resp.status_code == 200, resp.text

            assert not any(
                "set_config" in sql and "current_org_id" in sql
                for sql in executed_statements
            ), (
                "SQLite path should NOT emit set_config (no such function "
                f"in SQLite). Statements observed: {executed_statements!r}"
            )
        finally:
            _fastapi_app.dependency_overrides.pop(get_current_user, None)
            _fastapi_app.dependency_overrides.pop(get_db, None)
