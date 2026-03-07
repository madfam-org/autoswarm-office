"""Shared fixtures for nexus-api router tests.

This conftest patches the SQLAlchemy engine creation so that all nexus-api
modules use an in-memory SQLite database instead of PostgreSQL.  The patching
MUST happen before ``nexus_api.database`` is imported because that module
creates its engine at import time with PostgreSQL-specific pool arguments.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine as _real_create_async_engine,
)
from sqlalchemy.pool import StaticPool

from nexus_api.config import Settings

# ---------------------------------------------------------------------------
# 1. Patch ``get_settings`` so every module that calls it at import time gets
#    a test-safe Settings instance (SQLite URL, development mode).
# ---------------------------------------------------------------------------

_test_settings = Settings(
    database_url="sqlite+aiosqlite://",
    environment="development",
    dev_auth_bypass=True,
    _env_file=None,  # type: ignore[call-arg]
)

import nexus_api.config as _cfg_mod  # noqa: E402

_cfg_mod.get_settings = lambda: _test_settings


# ---------------------------------------------------------------------------
# 2. Intercept ``create_async_engine`` so that the call inside
#    ``nexus_api.database`` (which passes pool_size / max_overflow) succeeds
#    against an SQLite backend.
# ---------------------------------------------------------------------------


def _patched_create_async_engine(url: str, **kwargs: Any):  # type: ignore[no-untyped-def]
    kwargs.pop("pool_size", None)
    kwargs.pop("max_overflow", None)
    kwargs.pop("pool_pre_ping", None)
    return _real_create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=kwargs.get("echo", False),
    )


_engine_patch = patch(
    "sqlalchemy.ext.asyncio.create_async_engine",
    side_effect=_patched_create_async_engine,
)
_engine_patch.start()

# ---------------------------------------------------------------------------
# 3. NOW it is safe to import the app and database utilities.  The engine
#    created inside ``nexus_api.database`` will point to in-memory SQLite.
# ---------------------------------------------------------------------------

from nexus_api.database import Base, async_session_factory, engine, get_db  # noqa: E402
from nexus_api.main import app as _fastapi_app  # noqa: E402

# Stop the patch -- the module-level engine has already been created.
_engine_patch.stop()

# ---------------------------------------------------------------------------
# 4. Mock out side-effects that require external services (Redis, WebSocket).
# ---------------------------------------------------------------------------

import nexus_api.routers.approvals as _approvals_mod  # noqa: E402

_approvals_mod.notify_approval_decision = AsyncMock()
_approvals_mod.manager.send_approval_request = AsyncMock()
_approvals_mod.manager.send_approval_response = AsyncMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _setup_database() -> AsyncGenerator[None, None]:
    """Create all tables before each test and drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session that shares the same connection as the test client."""
    async with async_session_factory() as session:
        yield session


@pytest.fixture()
def override_get_db() -> None:
    """Override the ``get_db`` dependency with our SQLite-backed session factory."""

    async def _test_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    _fastapi_app.dependency_overrides[get_db] = _test_get_db
    yield  # type: ignore[misc]
    _fastapi_app.dependency_overrides.pop(get_db, None)


_CSRF_TOKEN = "test-csrf-token-fixed"


@pytest.fixture()
async def client(override_get_db: None) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP test client wired to the FastAPI app with SQLite backing."""
    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-CSRF-Token": _CSRF_TOKEN},
    ) as ac:
        ac.cookies.set("csrf-token", _CSRF_TOKEN)
        yield ac


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Return headers accepted by the dev-mode auth bypass, including CSRF token."""
    return {
        "Authorization": "Bearer test-token",
        "X-CSRF-Token": _CSRF_TOKEN,
    }


@pytest.fixture()
def sample_agent_id() -> str:
    """Return a stable UUID string for use as an agent_id in tests."""
    return str(uuid.uuid4())
