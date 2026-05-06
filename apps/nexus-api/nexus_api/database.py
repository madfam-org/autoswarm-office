"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

logger = logging.getLogger(__name__)


def _normalize_async_database_url(url: str) -> str:
    """Ensure bare PostgreSQL URLs use SQLAlchemy's asyncpg driver."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return a cached async engine configured from settings."""
    settings = get_settings()
    return create_async_engine(
        _normalize_async_database_url(settings.database_url),
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the cached engine."""
    return async_sessionmaker(
        get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def get_admin_engine() -> AsyncEngine:
    """Return a cached async engine for the ``app_admin`` BYPASSRLS role.

    Uses ``Settings.database_admin_url`` when set; otherwise falls back to
    the regular ``database_url`` (dev / SQLite test path -- there is no
    separate admin role to connect as). Logs a warning at first
    construction when the fallback is taken so ops can spot a missed
    rollout.

    The engine has a small pool (default 2 / max overflow 5) because
    cross-tenant ops are rare by design. Bumping the pool is a smell --
    if you find yourself wanting more admin connections, the caller is
    probably hot-pathing a query that should be tenant-scoped.

    See ``admin_session`` for the user-facing context manager.
    """
    settings = get_settings()
    if not settings.database_admin_url:
        # Fallback: reuse the main engine. In production this means
        # admin_session() runs as the regular app role and DOES NOT
        # bypass RLS -- cross-tenant ops will return zero rows under
        # the strict policies installed by migration 0028. Logged
        # loudly so ops can spot a missed rollout.
        #
        # In tests this is the desired behaviour: conftest's SQLite
        # engine creates the schema once on the main engine and the
        # admin "engine" must point at the same in-memory DB to see
        # those tables. Reusing the main engine handle achieves that
        # without a second create_async_engine call (which would create
        # a fresh empty in-memory SQLite -- different connection, no
        # tables, dual-engine breakage).
        logger.warning(
            "DATABASE_ADMIN_URL is not set; admin_session() falls back to the "
            "main database_url. In production this means admin_session() runs "
            "as the regular app role and DOES NOT bypass RLS -- cross-tenant "
            "ops will return zero rows under the strict policies installed by "
            "migration 0028. Set DATABASE_ADMIN_URL to a connection string "
            "for the 'app_admin' role (BYPASSRLS) created by that migration."
        )
        return get_engine()

    return create_async_engine(
        settings.database_admin_url,
        echo=False,
        pool_size=settings.db_admin_pool_size,
        max_overflow=settings.db_admin_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


def get_admin_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the admin engine.

    See ``get_admin_engine`` for pool sizing rationale.
    """
    return async_sessionmaker(
        get_admin_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Backwards-compatible module-level aliases.
engine = get_engine()
async_session_factory = get_session_factory()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def _set_session_org_id(session: AsyncSession) -> None:
    """Set the per-session ``app.current_org_id`` from the auth context.

    Postgres Row-Level Security policies on tenant-scoped tables filter by
    this session variable, so every query made through ``session`` is
    automatically scoped to the authenticated tenant. The variable is
    transaction-local (third arg to ``set_config`` is ``true``).

    No-ops on SQLite (which doesn't support session config or RLS) so
    tests using sqlite stay green. Empty/unset org_id is the documented
    permissive escape hatch for unauthenticated paths (health, demo,
    Alembic migrations, seed scripts) — see migration 0025 for the
    policy that honors NULL/empty as "no tenant context".
    """
    # Lazy import to avoid circular import at module load time.
    from .middleware.security import org_id_var

    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return  # SQLite test path or unbound session.

    try:
        org_id = org_id_var.get()
    except LookupError:
        org_id = ""

    # set_config('key', value, true) is the parameterized equivalent of
    # SET LOCAL — values are escaped, no SQL injection vector.
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": org_id or ""},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Sets ``app.current_org_id`` from the auth context so RLS policies on
    tenant-scoped tables enforce isolation at the DB layer (defense in
    depth — every router still scopes by ``org_id`` at the app layer).

    The session is committed on success and rolled back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            await _set_session_org_id(session)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def tenant_session(org_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Open an async session scoped to ``org_id`` for non-FastAPI call sites.

    Use this anywhere code needs a database session OUTSIDE the
    request-response flow that ``get_db`` covers — WebSocket handlers,
    A2A dispatch helpers, audit-middleware fire-and-forget writes,
    Celery tasks, etc. Without this helper such call sites use
    ``async_session_factory()`` directly, which leaves
    ``app.current_org_id`` unset (the request-flow ``ContextVar`` is
    out of scope or never bound), so the Phase 1 permissive RLS escape
    hatch (``IS NULL OR = ''``) is what makes their queries succeed
    today.

    The Phase 1.5 audit (``docs/RLS_PHASE_1_5_AUDIT.md`` §2.E) catalogues
    five concrete sites where this matters. After the strict-mode
    migration drops the permissive branch from the policy, every one
    of those sites breaks unless it's switched to this helper.

    Behaviour:
        - On Postgres: opens a session, executes
          ``set_config('app.current_org_id', org_id, true)``, yields,
          commits on success / rolls back on exception. Mirrors
          ``get_db`` exactly except the ``org_id`` source is an
          explicit argument instead of the request ``ContextVar``.
        - On SQLite (test paths): opens a session, no-ops the
          set_config call (SQLite doesn't have it), yields. RLS is a
          Postgres-only concept anyway.

    Args:
        org_id: The tenant whose data this session is allowed to see.
            Pass the literal string ``"platform"`` for MADFAM-internal
            cross-tenant queries — that token is honoured by the
            strict-mode policies as the platform-bypass marker (see
            §3 of the RLS audit doc). For genuine cross-tenant
            maintenance ops (e.g. ``reap-stale``), use the
            ``admin_session()`` helper instead so the BYPASSRLS pool
            is selected.

    Example:
        async with tenant_session(org_id="org-abc") as db:
            event = TaskEvent(org_id="org-abc", event_type=...)
            db.add(event)
            # commit happens on context exit
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :org_id, true)"),
                    {"org_id": org_id or ""},
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def admin_session() -> AsyncGenerator[AsyncSession, None]:
    """Open a session against the ``app_admin`` BYPASSRLS connection pool.

    Use this -- and ONLY this -- for cross-tenant maintenance ops that
    need to read or mutate rows belonging to multiple tenants in a single
    query. Examples in the current codebase:

        - ``swarms.reap_stale_tasks`` (sweeps stale tasks across all
          tenants every cron tick)
        - Future Celery jobs that aggregate metrics across tenants
        - Audit / compliance exports

    Logs a WARNING on every entry so cross-tenant access is observable in
    structured logs without needing to grep ``pg_stat_activity``. If you
    are tempted to silence the warning, that is the signal you want
    ``tenant_session("platform")`` instead -- which uses the strict-mode
    platform-bypass marker but still goes through the regular RLS-enforced
    pool, leaving an audit trail.

    Choosing between this and ``tenant_session("platform")``:

        - ``admin_session()``:
            Cross-tenant **maintenance** -- callers that genuinely need to
            see or mutate rows from multiple tenants in one query and
            cannot enumerate them. Selects a separate connection pool
            backed by the ``app_admin`` Postgres role (BYPASSRLS).
            Strongest bypass -- skips every RLS policy check.

        - ``tenant_session("platform")``:
            Platform-internal queries that the strict policies recognise
            via the ``'platform'`` marker. Stays in the regular
            RLS-enforced pool; a misconfigured policy would still deny
            the query, which is the desired defense in depth.

    Behaviour:
        - On Postgres with ``DATABASE_ADMIN_URL`` set: connects as
          ``app_admin``, BYPASSRLS skips every policy. No session var
          is set (it would be a no-op anyway -- the role bypasses).
        - On Postgres WITHOUT ``DATABASE_ADMIN_URL``: falls back to the
          regular pool (logged loudly at engine construction time).
          Strict-mode policies will return zero rows -- this is the
          deliberate misconfiguration signal for ops.
        - On SQLite (test path): opens a regular session, no RLS
          concept exists. Tests assert behaviour by spying on the
          admin_session factory.

    Example:
        async with admin_session() as db:
            stale = await db.execute(
                select(SwarmTask)
                .where(SwarmTask.status == "queued")
                .where(SwarmTask.created_at < cutoff)
            )
            # commits on context exit, rolls back on exception
    """
    logger.warning(
        "admin_session() opened -- cross-tenant access path "
        "(audit doc: docs/RLS_PHASE_1_5_AUDIT.md §3)"
    )
    factory = get_admin_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
