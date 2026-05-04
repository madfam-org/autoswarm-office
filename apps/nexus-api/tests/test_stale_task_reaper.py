"""Tests for stale task reaper endpoint.

Phase 1.5 / migration 0028: ``reap_stale_tasks`` no longer takes
``db: AsyncSession = Depends(get_db)``. It opens its own
``admin_session()`` against the BYPASSRLS pool. These tests spy on
the helper at the ``nexus_api.database`` module to verify the
behaviour without needing a real Postgres engine.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_caller() -> dict[str, object]:
    """Return a JWT user dict carrying the ``service`` privileged role."""
    return {"sub": f"test-{uuid.uuid4().hex[:6]}", "roles": ["service"]}


@asynccontextmanager
async def _spy_admin_session(db: AsyncMock):
    """Yield ``db`` as if it came from ``admin_session()``."""
    yield db


@pytest.mark.asyncio
async def test_reaps_old_queued_tasks() -> None:
    """Tasks queued for more than 1 hour are auto-failed."""
    from nexus_api import database as db_module
    from nexus_api.routers.swarms import reap_stale_tasks

    old_task = MagicMock()
    old_task.id = uuid.uuid4()
    old_task.status = "queued"
    old_task.created_at = datetime.now(UTC) - timedelta(hours=2)
    old_task.error_message = None
    old_task.completed_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [old_task]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    with patch.object(db_module, "admin_session", lambda: _spy_admin_session(db)):
        result = await reap_stale_tasks(user=_make_caller())

    assert result["reaped"] == 1
    assert old_task.status == "failed"
    assert old_task.error_message == "Reaped: stale task older than 1 hour"


@pytest.mark.asyncio
async def test_preserves_running_tasks() -> None:
    """Running tasks should not be reaped."""
    from nexus_api import database as db_module
    from nexus_api.routers.swarms import reap_stale_tasks

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    with patch.object(db_module, "admin_session", lambda: _spy_admin_session(db)):
        result = await reap_stale_tasks(user=_make_caller())
    assert result["reaped"] == 0
