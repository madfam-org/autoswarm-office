"""
Next-Tier: Session Checkpoint & Rollback System

Mirrors Hermes Agent's Git-checkpoint-based session rollback.
Persists a snapshot of the ACP workflow state to Postgres at the end of
each phase so that a failed or user-aborted run can be resumed or rolled
back to any previous phase boundary.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLAlchemy model (add to alembic migration)
# ---------------------------------------------------------------------------

try:
    from ..database import Base  # type: ignore

    class SessionCheckpoint(Base):
        __tablename__ = "session_checkpoints"

        # NOTE: do not re-add `: str =` style inline annotations.  SQLAlchemy's
        # `Column(...)` returns `Column[T]`, not `T`, so an inline annotation
        # like `id: str = Column(String(36), ...)` makes mypy treat
        # `SessionCheckpoint.id` as a plain `str`, which then breaks
        # `Select.where(SessionCheckpoint.id == foo)` (mypy infers the `==`
        # result as `bool`) and `SessionCheckpoint.created_at.desc()`
        # (mypy thinks `created_at` is a `datetime`).  Either drop the
        # annotations entirely (as below) or use SQLAlchemy 2.x's
        # `Mapped[T]` / `mapped_column` API.
        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        run_id = Column(String(255), nullable=False, index=True)
        phase = Column(String(64), nullable=False)  # e.g. "phase_i", "phase_ii", etc.
        phase_index = Column(Integer, nullable=False)
        state_json = Column(Text, nullable=False)  # JSON-serialized graph state
        created_at = Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(tz=UTC),
        )

except ImportError:
    SessionCheckpoint = None  # type: ignore  # Running outside nexus-api context


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """
    Saves and restores ACP workflow state snapshots at phase boundaries.

    Usage (inside a LangGraph node):
        mgr = CheckpointManager(db_session)
        await mgr.save(run_id="abc", phase="phase_i", state=graph_state)

    Rollback (via REST):
        state = await mgr.restore(run_id="abc", phase="phase_i")
        # Re-invoke the graph from this state
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    async def save(self, run_id: str, phase: str, phase_index: int, state: dict[str, Any]) -> str:
        """Persist a state snapshot. Returns the checkpoint id."""
        checkpoint_id = str(uuid.uuid4())
        state_json = json.dumps(state, default=str)

        if self._db and SessionCheckpoint is not None:
            cp = SessionCheckpoint(
                id=checkpoint_id,
                run_id=run_id,
                phase=phase,
                phase_index=phase_index,
                state_json=state_json,
            )
            self._db.add(cp)
            await self._db.commit()
            logger.info("Checkpoint saved: run=%s phase=%s id=%s", run_id, phase, checkpoint_id)
        else:
            # In-memory fallback (non-persistent; useful in tests)
            _IN_MEMORY_STORE.setdefault(run_id, {})[phase] = state_json
            logger.debug("Checkpoint saved in-memory: run=%s phase=%s", run_id, phase)

        return checkpoint_id

    async def restore(self, run_id: str, phase: str) -> dict[str, Any] | None:
        """Retrieve the most recent checkpoint for *run_id* at *phase*."""
        if self._db and SessionCheckpoint is not None:
            from sqlalchemy import select

            result = await self._db.execute(
                select(SessionCheckpoint)
                .where(
                    SessionCheckpoint.run_id == run_id,
                    SessionCheckpoint.phase == phase,
                )
                .order_by(SessionCheckpoint.created_at.desc())
                .limit(1)
            )
            cp = result.scalar_one_or_none()
            if cp is None:
                return None
            # `cp.state_json` is `Column[str]` to mypy under the legacy
            # `Column()` API, but `str` at runtime once accessed off an
            # instance.  Coerce explicitly so `json.loads` is happy.
            return json.loads(str(cp.state_json))
        else:
            raw = _IN_MEMORY_STORE.get(run_id, {}).get(phase)
            return json.loads(raw) if raw else None

    async def list_checkpoints(self, run_id: str) -> list[dict]:
        """List all checkpoints for *run_id* ordered by phase_index."""
        if self._db and SessionCheckpoint is not None:
            from sqlalchemy import select

            result = await self._db.execute(
                select(SessionCheckpoint)
                .where(SessionCheckpoint.run_id == run_id)
                .order_by(SessionCheckpoint.phase_index.asc())
            )
            return [
                {
                    "id": cp.id,
                    "phase": cp.phase,
                    "phase_index": cp.phase_index,
                    "created_at": cp.created_at.isoformat(),
                }
                for cp in result.scalars().all()
            ]
        return []


# Simple in-memory fallback store for tests / dev
_IN_MEMORY_STORE: dict[str, dict[str, str]] = {}
