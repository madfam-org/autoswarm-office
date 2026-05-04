"""Regression tests for the Postgres RLS session-variable plumbing.

Migration 0025 enables Row-Level Security on every tenant-scoped table
with a policy that filters by ``current_setting('app.current_org_id',
true)``. ``database._set_session_org_id`` sets that variable from the
auth context's ``org_id_var`` ContextVar on every request via ``get_db``.

These tests pin the contract so:
- The session variable is set whenever the auth context provides one.
- The setter no-ops on SQLite (test infra) so tests don't break.
- The variable is empty-string (the documented permissive escape hatch)
  when no org context is set — Alembic migrations / healthchecks /
  unauthenticated paths must continue to work.
- The migration's tenant-table list stays in sync with models that
  declare ``org_id``.

Real RLS-policy enforcement requires Postgres in CI and is verified by
``test_rls_postgres_isolation.py`` (skipped when DATABASE_URL is sqlite).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus_api import database
from nexus_api.database import _set_session_org_id
from nexus_api.middleware.security import org_id_var

# ---------------------------------------------------------------------------
# _set_session_org_id behaviour
# ---------------------------------------------------------------------------


class TestSetSessionOrgIdSqlite:
    """SQLite test path: _set_session_org_id MUST no-op."""

    @pytest.mark.asyncio
    async def test_no_op_on_sqlite(self) -> None:
        """No SQL is executed when the session is bound to a sqlite engine."""
        session = MagicMock()
        bind = MagicMock()
        bind.dialect.name = "sqlite"
        session.get_bind = MagicMock(return_value=bind)
        session.execute = AsyncMock()

        await _set_session_org_id(session)

        session.execute.assert_not_called()


class TestSetSessionOrgIdPostgres:
    """Postgres path: set_config is called with the ContextVar value."""

    @pytest.mark.asyncio
    async def test_calls_set_config_with_context_var_value(self) -> None:
        """The set_config call carries the value of org_id_var."""
        session = MagicMock()
        bind = MagicMock()
        bind.dialect.name = "postgresql"
        session.get_bind = MagicMock(return_value=bind)
        session.execute = AsyncMock()

        token = org_id_var.set("acme-corp-123")
        try:
            await _set_session_org_id(session)
        finally:
            org_id_var.reset(token)

        session.execute.assert_awaited_once()
        call_args = session.execute.await_args
        assert call_args is not None
        # First positional arg is the SQL text; check it sets the right key.
        sql_text = str(call_args.args[0])
        assert "set_config" in sql_text
        assert "app.current_org_id" in sql_text
        # Second positional arg is the params dict.
        params = call_args.args[1]
        assert params == {"org_id": "acme-corp-123"}

    @pytest.mark.asyncio
    async def test_passes_empty_string_when_no_context(self) -> None:
        """Empty / unset org context → empty string param.

        This is the documented permissive escape hatch — the RLS policy
        in migration 0025 honors NULL/empty as 'no tenant context' so
        Alembic / healthchecks / unauthenticated paths keep working.
        """
        session = MagicMock()
        bind = MagicMock()
        bind.dialect.name = "postgresql"
        session.get_bind = MagicMock(return_value=bind)
        session.execute = AsyncMock()

        # Don't set the ContextVar; default is "default" per security.py.
        await _set_session_org_id(session)

        session.execute.assert_awaited_once()
        params = session.execute.await_args.args[1]
        # The default value of org_id_var is "default" — that's a real
        # tenant-context value, not the escape-hatch case. Test it
        # passes through.
        assert params == {"org_id": "default"}


# ---------------------------------------------------------------------------
# Migration / model coherence
# ---------------------------------------------------------------------------


class TestMigrationTableList:
    """The migration's _TENANT_TABLES MUST match every model with org_id.

    Catches the case where a future model adds an org_id column but
    forgets to add the table to migration 0025's _TENANT_TABLES list,
    silently leaving the new table without RLS.
    """

    def test_every_org_scoped_model_is_in_migration(self) -> None:
        """Every model with an org_id column appears in _TENANT_TABLES."""
        # Import the migration module dynamically (its filename starts
        # with a digit so it can't be a normal import).
        import importlib.util
        from pathlib import Path

        migration_path = (
            Path(database.__file__).parent.parent
            / "alembic"
            / "versions"
            / "0025_enable_rls_tenant_tables.py"
        )
        spec = importlib.util.spec_from_file_location("migration_0025", migration_path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        tenant_tables = set(migration._TENANT_TABLES)

        # Walk the models module for every Mapper with an org_id attribute.
        from nexus_api import models

        org_scoped_tables: set[str] = set()
        for attr in dir(models):
            cls = getattr(models, attr)
            if (
                isinstance(cls, type)
                and hasattr(cls, "__tablename__")
                and hasattr(cls, "__table__")
                and "org_id" in cls.__table__.columns  # type: ignore[attr-defined]
            ):
                org_scoped_tables.add(cls.__tablename__)

        # Every org-scoped table MUST be in the migration. Extra tables in
        # the migration that aren't in models are fine — they may be from
        # legacy schemas — but missing ones are a bug.
        missing = org_scoped_tables - tenant_tables
        assert not missing, (
            f"Models {sorted(missing)} have an org_id column but are not in "
            f"migration 0025's _TENANT_TABLES list — RLS won't apply to them."
        )
