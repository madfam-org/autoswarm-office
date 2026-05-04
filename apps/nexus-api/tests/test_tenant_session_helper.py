"""Regression tests for the tenant_session helper + migrated call sites.

Phase 1.5 RLS audit (`docs/RLS_PHASE_1_5_AUDIT.md` §2.E) catalogued
five "no tenant context" sites that use ``async_session_factory()``
directly and would break under strict-mode RLS. This PR adds the
``tenant_session(org_id=...)`` helper and migrates every site to it.

What we pin here:
- The helper sets ``app.current_org_id`` on Postgres binds.
- The helper is a no-op on SQLite (test path).
- The helper commits on success, rolls back on exception.
- Empty / missing ``org_id`` resolves to ``""`` (matches the Phase 1
  permissive-policy contract — strict mode treats this as the
  "no tenant" case which the policy will reject).
- The migrated call sites import ``tenant_session`` (catches future
  reverts that would silently re-introduce the bug).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTenantSessionContract:
    """The helper's externally-observable behaviour."""

    @pytest.mark.asyncio
    async def test_yields_a_session_and_commits_on_success(
        self, db_session  # noqa: ARG002 — fixture wires up SQLite engine
    ) -> None:
        """Happy path: open, yield, commit. SQLite path (no set_config call).

        Uses TaskEvent because it has minimal required columns (no FK
        deps on agents/swarm_tasks) so the test stays focused on the
        helper's commit-on-exit contract.
        """
        from nexus_api.database import tenant_session
        from nexus_api.models import TaskEvent

        async with tenant_session(org_id="org-A") as session:
            event = TaskEvent(
                org_id="org-A",
                event_type="test.commit_on_exit",
                event_category="test",
                payload={"k": "v"},
            )
            session.add(event)

        # After exit, a fresh session sees the committed row.
        from sqlalchemy import select

        from nexus_api.database import async_session_factory

        async with async_session_factory() as fresh:
            rows = (
                await fresh.execute(
                    select(TaskEvent).where(TaskEvent.org_id == "org-A")
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].event_type == "test.commit_on_exit"

    @pytest.mark.asyncio
    async def test_rolls_back_on_exception(self, db_session) -> None:  # noqa: ARG002
        """If the body raises, the txn rolls back and no row persists."""
        from nexus_api.database import async_session_factory, tenant_session
        from nexus_api.models import TaskEvent

        with pytest.raises(RuntimeError, match="boom"):
            async with tenant_session(org_id="org-rollback") as session:
                event = TaskEvent(
                    org_id="org-rollback",
                    event_type="test.should_rollback",
                    event_category="test",
                )
                session.add(event)
                raise RuntimeError("boom")

        from sqlalchemy import select

        async with async_session_factory() as fresh:
            rows = (
                await fresh.execute(
                    select(TaskEvent).where(TaskEvent.org_id == "org-rollback")
                )
            ).scalars().all()
            assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_skips_set_config_on_sqlite(self, db_session) -> None:  # noqa: ARG002
        """SQLite has no set_config function — helper must NOT execute it."""
        from nexus_api.database import tenant_session

        # If the helper tried to run set_config on SQLite, this would raise
        # (sqlite3.OperationalError: no such function: set_config). Assert
        # the body completes cleanly.
        async with tenant_session(org_id="org-X") as session:
            assert session is not None

    @pytest.mark.asyncio
    async def test_calls_set_config_on_postgres_bind(self) -> None:
        """On a Postgres bind the helper MUST set the session var.

        This is the load-bearing assertion for Phase 1.5 — without it
        the strict policy would reject every query inside the context.
        """
        from nexus_api import database as db_module

        # Build a mock session that reports a postgresql bind.
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"

        mock_session = MagicMock()
        mock_session.get_bind.return_value = mock_bind
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        # Async context manager wrapping the mock session.
        class _MockFactoryCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *args):
                return None

        mock_factory = MagicMock(return_value=_MockFactoryCM())

        with patch.object(db_module, "get_session_factory", return_value=mock_factory):
            async with db_module.tenant_session(org_id="org-pg-A") as s:
                assert s is mock_session

        # First execute call MUST be the set_config statement bound to org-pg-A.
        first_call = mock_session.execute.await_args_list[0]
        sql_text = str(first_call.args[0])
        params = first_call.args[1]
        assert "set_config" in sql_text
        assert "app.current_org_id" in sql_text
        assert params == {"org_id": "org-pg-A"}

        # Commit happens on context exit; rollback does not.
        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_org_id_normalizes_to_empty_string(self) -> None:
        """Pass-through of empty/None to set_config is the documented contract.

        Strict-mode policy rejects empty string — that's the intended
        behaviour. The helper does NOT silently substitute ``"default"``
        or any other value because doing so would mask "no tenant
        context" bugs that strict mode is designed to surface.
        """
        from nexus_api import database as db_module

        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"

        mock_session = MagicMock()
        mock_session.get_bind.return_value = mock_bind
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        class _MockFactoryCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *args):
                return None

        mock_factory = MagicMock(return_value=_MockFactoryCM())

        with patch.object(db_module, "get_session_factory", return_value=mock_factory):
            async with db_module.tenant_session(org_id="") as _:
                pass

        first_call = mock_session.execute.await_args_list[0]
        params = first_call.args[1]
        assert params == {"org_id": ""}


# ---------------------------------------------------------------------------
# Migrated call-site smoke tests — make sure the import is in place so
# a future revert can't silently regress.
# ---------------------------------------------------------------------------


class TestMigratedCallSitesImportTenantSession:
    """Each Phase 1.5 break site should import ``tenant_session``.

    These tests are deliberately import-shape rather than behavioural —
    the behavioural tests for each site live in their own module
    (test_audit_middleware, test_a2a_dispatch, etc). Pinning the import
    catches the most common regression: a maintainer reverts the call
    site to ``async_session_factory()`` and the silent-bug class
    re-emerges.
    """

    def test_audit_middleware_uses_tenant_session(self) -> None:
        from pathlib import Path

        src = Path("apps/nexus-api/nexus_api/middleware/audit.py").read_text()
        assert "tenant_session" in src, (
            "audit middleware reverted to async_session_factory — "
            "see RLS_PHASE_1_5_AUDIT.md §2.E"
        )

    def test_a2a_dispatch_uses_tenant_session(self) -> None:
        from pathlib import Path

        src = Path("apps/nexus-api/nexus_api/main.py").read_text()
        # Both _dispatch_a2a_task and _get_a2a_task_status must use it.
        assert src.count("tenant_session(org_id=\"a2a-external\")") >= 2, (
            "A2A bridge helpers reverted to async_session_factory — "
            "see RLS_PHASE_1_5_AUDIT.md §2.E"
        )

    def test_approvals_ws_initial_batch_uses_tenant_session(self) -> None:
        from pathlib import Path

        src = Path("apps/nexus-api/nexus_api/routers/approvals.py").read_text()
        assert "tenant_session" in src, (
            "approvals router reverted to async_session_factory — "
            "see RLS_PHASE_1_5_AUDIT.md §2.E"
        )

    def test_events_ws_initial_batch_uses_tenant_session(self) -> None:
        from pathlib import Path

        src = Path("apps/nexus-api/nexus_api/routers/events.py").read_text()
        assert "tenant_session" in src, (
            "events router reverted to async_session_factory — "
            "see RLS_PHASE_1_5_AUDIT.md §2.E"
        )
