"""
Next-Tier: Checkpoints REST router

Exposes session checkpoint management so operators can inspect, rollback,
and re-run ACP workflows from any phase boundary.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, require_roles
from ..checkpoints import CheckpointManager
from ..database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/checkpoints", tags=["Checkpoints"])


class CheckpointListItem(BaseModel):
    id: str
    phase: str
    phase_index: int
    created_at: str


class CheckpointState(BaseModel):
    run_id: str
    phase: str
    state: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{run_id}", response_model=list[CheckpointListItem])
async def list_checkpoints(
    run_id: str,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
    db: AsyncSession = Depends(get_db),
) -> list[CheckpointListItem]:
    """List all phase checkpoints for an ACP run."""
    mgr = CheckpointManager(db)
    items = await mgr.list_checkpoints(run_id)
    return [CheckpointListItem(**item) for item in items]


@router.get("/{run_id}/{phase}", response_model=CheckpointState)
async def get_checkpoint(
    run_id: str,
    phase: str,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
    db: AsyncSession = Depends(get_db),
) -> CheckpointState:
    """Retrieve the state snapshot for a specific phase of a run."""
    mgr = CheckpointManager(db)
    state = await mgr.restore(run_id, phase)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No checkpoint for run={run_id} phase={phase}")
    return CheckpointState(run_id=run_id, phase=phase, state=state)


@router.post("/{run_id}/{phase}/rollback")
async def rollback_to_phase(
    run_id: str,
    phase: str,
    user: CurrentUser = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Restore the ACP run state to a previous phase checkpoint and re-queue
    the workflow from that phase.
    """
    mgr = CheckpointManager(db)
    state = await mgr.restore(run_id, phase)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No checkpoint for run={run_id} phase={phase}")

    # Re-queue the workflow from this phase
    try:
        from nexus_api.tasks.acp_tasks import run_acp_workflow_task

        task = run_acp_workflow_task.delay(
            state.get("target_url", ""),
            resume_state=state,
            resume_phase=phase,
        )
        logger.info("Rollback: run=%s phase=%s → new task %s", run_id, phase, task.id)
        return {"status": "requeued", "new_task_id": task.id, "rolled_back_to": phase}
    except Exception as exc:
        logger.error("Rollback re-queue failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Rollback re-queue failed: {exc}",
        ) from exc
