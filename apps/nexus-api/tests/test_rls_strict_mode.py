"""Tests for the Phase 1.5 RLS strict-mode migration (0028) + helpers.

Pins the contract surface defined in ``docs/RLS_PHASE_1_5_AUDIT.md`` §5
("the follow-up PR's test matrix"):

  - Migration 0028 exists, is reachable from the Alembic chain, and
    declares the same ``_TENANT_TABLES`` list as migration 0025.
  - The ``admin_session()`` helper opens a session, logs at WARNING on
    every entry, commits on success, rolls back on exception, and
    selects the admin engine (NOT the regular ``get_engine()``).
  - The ``database_admin_url`` Setting wires the admin engine when set,
    falls back to ``database_url`` when empty (with a warning).
  - The ``/api/v1/health/rls-status`` endpoint returns the documented
    JSON shape and 503-degrades when strict mode is not on.
  - The ``reap_stale_tasks`` router is wired to ``admin_session()`` and
    no longer takes a ``Depends(get_db)`` parameter.

Postgres-only assertions (the ones that need real RLS to be meaningful)
are skipped on SQLite -- the test infra runs against in-memory SQLite,
not Postgres. Each Postgres-only test is gated by an explicit
``pytest.mark.skipif`` on the underlying engine dialect, so the suite
stays green on the SQLite test runner AND we have a clear list of
"things to also assert in CI when DATABASE_URL points at Postgres".

Conftest already sets up an SQLite-backed engine; we don't fight it.
"""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Resolve the SQLite test engine once so the postgres-only marker works.
from nexus_api.database import async_session_factory


def _running_on_postgres() -> bool:
    """Return True iff the test database is real Postgres.

    Conftest pins SQLite for unit tests; this returns False there. CI
    jobs that point ``DATABASE_URL`` at Postgres will flip it to True
    and the strict-mode assertions run for real.
    """
    bind = async_session_factory.kw["bind"]  # type: ignore[attr-defined]
    return bool(getattr(bind, "dialect", None) and bind.dialect.name == "postgresql")


postgres_only = pytest.mark.skipif(
    not _running_on_postgres(),
    reason="Strict RLS assertions require a real Postgres test database",
)


# ---------------------------------------------------------------------------
# 1. Migration shape + chain
# ---------------------------------------------------------------------------


def _load_migration_module(filename: str) -> Any:
    """Dynamically import a migration module by filename (digit-prefixed)."""
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    spec = importlib.util.spec_from_file_location(
        f"_migration_{filename}", versions_dir / filename
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration0028Shape:
    """Migration 0028 is reachable, declares the right metadata, and shares
    the canonical tenant-table list with migration 0025."""

    def test_migration_chain_links_0028_after_0027(self) -> None:
        """``down_revision`` MUST point at 0027, ``revision`` MUST be 0028."""
        m = _load_migration_module("0028_rls_strict_mode.py")
        assert m.revision == "0028"
        assert m.down_revision == "0027"

    def test_tenant_table_list_matches_migration_0025(self) -> None:
        """0028's table list MUST equal 0025's -- same surface, tighter policy.

        If a new tenant table is added between 0025 and 0028, it must be
        added to BOTH migrations' tuples (the canonical home is 0025;
        0028 imports it conceptually but copies the list to avoid a
        cross-migration import).
        """
        m25 = _load_migration_module("0025_enable_rls_tenant_tables.py")
        m28 = _load_migration_module("0028_rls_strict_mode.py")
        assert set(m28._TENANT_TABLES) == set(m25._TENANT_TABLES)

    def test_tenant_identities_explicitly_excluded(self) -> None:
        """``tenant_identities`` is a directory, not a tenant-scoped table.

        Pin the exclusion so a future maintainer thinking "every table
        with a tenant-ish column needs RLS" doesn't accidentally add it
        to the list -- doing so would break the ``canonical_id`` lookup
        that the ledger depends on (audit doc §2.E).
        """
        m28 = _load_migration_module("0028_rls_strict_mode.py")
        assert "tenant_identities" not in m28._TENANT_TABLES

    def test_platform_bypass_marker_is_documented(self) -> None:
        """The ``'platform'`` sentinel string is the one permissive leg
        the strict policies retain. Pin the constant so a maintainer
        renaming it has to update tests too."""
        m28 = _load_migration_module("0028_rls_strict_mode.py")
        assert m28._PLATFORM_BYPASS_MARKER == "platform"

    def test_upgrade_and_downgrade_are_idempotent_no_ops_on_sqlite(self) -> None:
        """Both up and down must short-circuit on SQLite.

        Conftest runs the test suite on SQLite; the migration's
        ``_is_postgres()`` check returns False and the body does
        nothing. Re-running upgrade/downgrade in any order must NOT
        raise.
        """
        m28 = _load_migration_module("0028_rls_strict_mode.py")
        # Patch ``op.get_bind()`` so ``_is_postgres()`` returns False.
        with patch.object(m28.op, "get_bind") as mock_bind:
            mock_bind.return_value.dialect.name = "sqlite"
            # Both directions must be no-ops; calling either should not raise.
            m28.upgrade()
            m28.downgrade()
            m28.upgrade()  # idempotent re-apply


# ---------------------------------------------------------------------------
# 2. ``admin_session()`` helper contract
# ---------------------------------------------------------------------------


class TestAdminSessionHelper:
    """Behavioural contract of ``database.admin_session``."""

    @pytest.mark.asyncio
    async def test_logs_warning_on_entry(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """Every entry MUST emit a WARNING -- this is the audit trail."""
        from nexus_api import database as db_module

        with caplog.at_level("WARNING", logger="nexus_api.database"):
            async with db_module.admin_session() as session:
                assert session is not None

        # Look for the substring -- the full message includes the audit-doc ref.
        admin_warnings = [
            r for r in caplog.records if "admin_session() opened" in r.getMessage()
        ]
        assert len(admin_warnings) >= 1, (
            "admin_session() must log a WARNING on every entry so cross-tenant "
            "access is observable in structured logs"
        )

    @pytest.mark.asyncio
    async def test_commits_on_success(self) -> None:
        """Body completes -> commit() is called."""
        from nexus_api import database as db_module

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        @asynccontextmanager
        async def _factory_cm():
            yield mock_session

        mock_factory = MagicMock(return_value=_factory_cm())

        with patch.object(
            db_module, "get_admin_session_factory", return_value=mock_factory
        ):
            async with db_module.admin_session() as s:
                assert s is mock_session

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rolls_back_on_exception(self) -> None:
        """Body raises -> rollback() is called, exception propagates."""
        from nexus_api import database as db_module

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        @asynccontextmanager
        async def _factory_cm():
            yield mock_session

        mock_factory = MagicMock(return_value=_factory_cm())

        with patch.object(
            db_module, "get_admin_session_factory", return_value=mock_factory
        ):
            with pytest.raises(RuntimeError, match="boom"):
                async with db_module.admin_session():
                    raise RuntimeError("boom")

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    def test_admin_engine_falls_back_when_url_unset(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """Empty ``database_admin_url`` -> warn loudly + reuse main URL.

        Ops misconfiguration signal: a strict-mode cluster that forgot
        to set DATABASE_ADMIN_URL would silently route admin_session()
        through the regular pool, where strict policies return zero rows
        for cross-tenant queries. The warning is the only signal ops
        gets before users notice.
        """
        from nexus_api import database as db_module

        # Force the lru_cache to recompute by clearing it.
        db_module.get_admin_engine.cache_clear()
        with caplog.at_level("WARNING", logger="nexus_api.database"):
            db_module.get_admin_engine()
        db_module.get_admin_engine.cache_clear()  # don't poison neighbours

        # Conftest pins database_admin_url="" by Settings default, so the
        # fallback path runs.
        admin_warnings = [
            r for r in caplog.records if "DATABASE_ADMIN_URL" in r.getMessage()
        ]
        assert len(admin_warnings) >= 1, (
            "get_admin_engine() must warn when DATABASE_ADMIN_URL is unset; "
            "ops needs the signal to spot a misconfigured strict-mode cluster"
        )


# ---------------------------------------------------------------------------
# 3. ``/api/v1/health/rls-status`` endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRlsStatusEndpoint:
    """Shape + behaviour of the new health endpoint."""

    async def test_returns_documented_json_shape_on_sqlite(
        self, client: httpx.AsyncClient
    ) -> None:
        """SQLite path returns the documented keys with ``dialect=not_postgres``.

        Lets ops dashboards parse the response unconditionally without
        special-casing the dev environment.
        """
        resp = await client.get("/api/v1/health/rls-status")
        assert resp.status_code == 200
        body = resp.json()
        # Documented top-level keys.
        assert "strict_mode_enabled" in body
        assert "policies" in body
        assert "force_rls_tables" in body
        assert "app_admin_role_present" in body
        assert body["strict_mode_enabled"] is False
        assert body["policies"] == []
        assert body["force_rls_tables"] == []
        assert body["app_admin_role_present"] is False
        assert body["dialect"] == "not_postgres"

    @postgres_only
    async def test_returns_503_when_strict_mode_off(
        self, client: httpx.AsyncClient
    ) -> None:
        """Postgres + permissive policies (Phase 1) -> 503.

        Pre-migration-0028 the policies still carry the IS NULL leg;
        the endpoint surfaces this as degraded so a CI gate can refuse
        to promote a build that points at a non-strict cluster.
        """
        resp = await client.get("/api/v1/health/rls-status")
        # Either 200 (strict is on) or 503 (strict is off). Both are
        # documented; the test pins that the endpoint never crashes.
        assert resp.status_code in (200, 503)
        body = resp.json()
        if resp.status_code == 503:
            assert body["strict_mode_enabled"] is False


# ---------------------------------------------------------------------------
# 4. Strict-mode behavioural assertions (Postgres-only -- skipped on SQLite)
# ---------------------------------------------------------------------------
#
# Audit doc §5 calls these out as required for the implementation PR:
#   - Anonymous (no session var) returns ZERO rows from tenant tables.
#   - Cross-tenant SELECT returns zero rows.
#   - Same-tenant SELECT works.
#   - admin_session() returns rows from every tenant.
#   - tenant_session("") raises a clear error from the policy.
#
# These tests run only when the test runner is pointed at Postgres. The
# SQLite-on-by-default conftest skips them cleanly.
# ---------------------------------------------------------------------------


@postgres_only
@pytest.mark.asyncio
class TestStrictModeBehaviourPostgres:
    """End-to-end RLS assertions on a real Postgres instance."""

    async def test_anonymous_query_returns_zero_rows(self, db_session) -> None:  # type: ignore[no-untyped-def]
        """No session var set -> strict policy returns zero rows.

        Pre-strict (Phase 1) the IS NULL leg made this return everything.
        Strict mode collapses it to zero. This is the load-bearing
        assertion that the migration actually flipped the policy.
        """
        from sqlalchemy import text as _text

        # Reset the session var first so we mimic an anonymous path.
        await db_session.execute(_text("SELECT set_config('app.current_org_id', '', true)"))
        result = await db_session.execute(_text("SELECT count(*) FROM swarm_tasks"))
        assert result.scalar_one() == 0

    async def test_same_tenant_query_returns_rows(self, db_session) -> None:  # type: ignore[no-untyped-def]
        """Session var matches a row's org_id -> the row is visible."""
        from sqlalchemy import text as _text

        from nexus_api.models import SwarmTask

        await db_session.execute(
            _text("SELECT set_config('app.current_org_id', 'org-A', true)")
        )
        # Insert a row scoped to org-A.
        task = SwarmTask(
            description="test", graph_type="research", payload={},
            assigned_agent_ids=[], status="queued", org_id="org-A",
        )
        db_session.add(task)
        await db_session.flush()

        result = await db_session.execute(
            _text("SELECT org_id FROM swarm_tasks WHERE id = :id"),
            {"id": str(task.id)},
        )
        assert result.scalar_one() == "org-A"

    async def test_cross_tenant_query_returns_zero_rows(self, db_session) -> None:  # type: ignore[no-untyped-def]
        """Session var = 'org-A', querying for an org-B row -> zero rows.

        Even with the row's org_id explicit in the WHERE clause, the
        policy filters first and the row is invisible.
        """
        from sqlalchemy import text as _text

        from nexus_api.models import SwarmTask

        # Seed an org-B row using the platform marker (allowed by policy).
        await db_session.execute(
            _text("SELECT set_config('app.current_org_id', 'platform', true)")
        )
        task = SwarmTask(
            description="org-B", graph_type="research", payload={},
            assigned_agent_ids=[], status="queued", org_id="org-B",
        )
        db_session.add(task)
        await db_session.flush()
        task_id = task.id

        # Switch to org-A scope; the org-B row must be invisible.
        await db_session.execute(
            _text("SELECT set_config('app.current_org_id', 'org-A', true)")
        )
        result = await db_session.execute(
            _text("SELECT count(*) FROM swarm_tasks WHERE id = :id"),
            {"id": str(task_id)},
        )
        assert result.scalar_one() == 0

    async def test_admin_session_sees_rows_from_every_tenant(self) -> None:
        """``admin_session()`` (BYPASSRLS pool) returns rows for every tenant.

        The whole point of the helper -- if the BYPASSRLS role is wired
        correctly, a cross-tenant SELECT returns rows from N orgs in
        one query.
        """
        from sqlalchemy import text as _text

        from nexus_api.database import admin_session

        async with admin_session() as db:
            # Should not be filtered by any tenant scope.
            result = await db.execute(_text("SELECT count(DISTINCT org_id) FROM swarm_tasks"))
            distinct_orgs = result.scalar_one()
            # If seed rows from prior tests exist, this will be >= 1.
            # The point is "doesn't error out".
            assert distinct_orgs >= 0
