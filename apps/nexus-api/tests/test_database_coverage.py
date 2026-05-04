"""Phase 2 critical-path coverage for ``nexus_api.database``.

Targets the gaps in ``_set_session_org_id`` (the postgresql-only
session-config setter) and the ``get_db`` rollback-on-exception path.
The conftest already exercises the success path on every test that uses
the ``client`` fixture, so we only need explicit tests for the branches
the conftest doesn't hit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api import database as _db_mod


class _PostgresDialectStub:
    name = "postgresql"


class _SqliteDialectStub:
    name = "sqlite"


def _make_session(dialect_name: str) -> MagicMock:
    """Build a session mock whose ``get_bind()`` returns a fake-dialect bind."""
    session = MagicMock(spec=AsyncSession)
    bind = MagicMock()
    if dialect_name == "postgresql":
        bind.dialect = _PostgresDialectStub()
    elif dialect_name == "sqlite":
        bind.dialect = _SqliteDialectStub()
    else:
        bind.dialect = MagicMock(name=dialect_name)
    session.get_bind = MagicMock(return_value=bind)
    session.execute = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# _set_session_org_id branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSetSessionOrgId:
    async def test_noop_on_sqlite(self) -> None:
        """SQLite path must NOT issue any SQL (RLS isn't supported)."""
        session = _make_session("sqlite")
        await _db_mod._set_session_org_id(session)
        session.execute.assert_not_called()

    async def test_noop_on_unbound_session(self) -> None:
        session = MagicMock(spec=AsyncSession)
        session.get_bind = MagicMock(return_value=None)
        session.execute = AsyncMock()
        await _db_mod._set_session_org_id(session)
        session.execute.assert_not_called()

    async def test_postgres_issues_set_config_with_org_id(self) -> None:
        from nexus_api.middleware.security import org_id_var

        session = _make_session("postgresql")
        token = org_id_var.set("tenant-42")
        try:
            await _db_mod._set_session_org_id(session)
        finally:
            org_id_var.reset(token)

        session.execute.assert_awaited_once()
        args = session.execute.call_args.args
        # The first positional arg is the TextClause; check the bound parameter.
        assert "set_config" in str(args[0])
        # Second positional is the param dict.
        assert args[1] == {"org_id": "tenant-42"}

    async def test_postgres_falls_back_to_empty_string_when_var_unset(self) -> None:
        """LookupError on ``org_id_var.get()`` must not raise — falls to ''.

        The ``ContextVar`` in security.py has a default, so a real
        LookupError is impossible. We monkeypatch the import inside the
        function to a fresh ContextVar with no default to exercise the
        ``except LookupError`` branch (line 76-77).
        """
        from contextvars import ContextVar

        session = _make_session("postgresql")
        no_default_var: ContextVar[str] = ContextVar("test_no_default")

        # Patch the lookup that the SUT does inside the function
        import nexus_api.middleware.security as _sec_mod

        original = _sec_mod.org_id_var
        _sec_mod.org_id_var = no_default_var  # type: ignore[assignment]
        try:
            await _db_mod._set_session_org_id(session)
        finally:
            _sec_mod.org_id_var = original  # type: ignore[assignment]

        session.execute.assert_awaited_once()
        args = session.execute.call_args.args
        # The org_id param falls back to empty string (safe default).
        assert args[1] == {"org_id": ""}


# ---------------------------------------------------------------------------
# get_db: rollback on exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetDb:
    async def test_rollback_on_exception_propagates(self) -> None:
        """Exceptions raised inside the ``yield`` must trigger rollback + reraise."""
        gen = _db_mod.get_db()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        try:
            await gen.athrow(RuntimeError("boom"))
        except RuntimeError:
            # Generator must reraise — not swallow.
            return
        pytest.fail("get_db should propagate the exception after rollback")

    async def test_commit_on_success(self) -> None:
        """The success path commits and closes — generator exits cleanly."""
        gen = _db_mod.get_db()
        session = await gen.__anext__()
        assert session is not None
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


# ---------------------------------------------------------------------------
# get_engine + get_session_factory: idempotent / cache behaviour
# ---------------------------------------------------------------------------


def test_get_engine_returns_cached_instance() -> None:
    """``@lru_cache`` keeps the engine singleton across calls."""
    e1 = _db_mod.get_engine()
    e2 = _db_mod.get_engine()
    assert e1 is e2


def test_get_session_factory_binds_to_cached_engine() -> None:
    sf = _db_mod.get_session_factory()
    assert sf is not None
    # Same factory bind reuses the singleton engine.
    assert sf.kw["bind"] is _db_mod.get_engine()
