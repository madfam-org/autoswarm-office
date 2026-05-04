"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

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


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return a cached async engine configured from settings."""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
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
