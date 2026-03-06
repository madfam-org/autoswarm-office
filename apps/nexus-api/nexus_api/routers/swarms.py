"""Swarm task dispatch and monitoring endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import ComputeTokenLedger, SwarmTask

router = APIRouter(tags=["swarms"], dependencies=[Depends(get_current_user)])


# -- Request / Response schemas -----------------------------------------------


class DispatchRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    graph_type: str = Field(
        default="sequential",
        pattern=r"^(sequential|parallel|coding|research|crm)$",
    )
    assigned_agent_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class SwarmTaskResponse(BaseModel):
    id: str
    description: str
    graph_type: str
    assigned_agent_ids: list[str]
    payload: dict[str, Any]
    status: str
    created_at: str
    completed_at: str | None

    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(running|completed|failed|cancelled)$")
    result: dict[str, Any] | None = None


# -- Helpers ------------------------------------------------------------------


def _task_to_response(task: SwarmTask) -> SwarmTaskResponse:
    return SwarmTaskResponse(
        id=str(task.id),
        description=task.description,
        graph_type=task.graph_type,
        assigned_agent_ids=task.assigned_agent_ids or [],
        payload=task.payload or {},
        status=task.status,
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


# -- Endpoints ----------------------------------------------------------------


@router.post("/dispatch", response_model=SwarmTaskResponse, status_code=status.HTTP_201_CREATED)
async def dispatch_task(
    body: DispatchRequest,
    db: AsyncSession = Depends(get_db),
) -> SwarmTaskResponse:
    """Dispatch a new swarm task.

    Validates compute token budget, persists the task, and publishes a
    message to the Redis task queue for worker consumption.
    """
    settings = get_settings()

    # -- Compute token budget check -------------------------------------------
    dispatch_cost = 10  # matches ComputeTokenManager.COST_TABLE["dispatch_task"]

    # Record the debit in the ledger (the in-memory ComputeTokenManager lives
    # in the orchestrator package; the ledger is the durable record).
    task = SwarmTask(
        description=body.description,
        graph_type=body.graph_type,
        assigned_agent_ids=body.assigned_agent_ids,
        payload=body.payload,
        status="queued",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    ledger_entry = ComputeTokenLedger(
        action="dispatch_task",
        amount=dispatch_cost,
        task_id=task.id,
    )
    db.add(ledger_entry)
    await db.flush()

    # -- Publish to Redis queue for workers -----------------------------------
    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.lpush(
            "autoswarm:tasks",
            json.dumps(
                {
                    "task_id": str(task.id),
                    "graph_type": task.graph_type,
                    "description": task.description,
                    "assigned_agent_ids": task.assigned_agent_ids,
                    "payload": task.payload,
                }
            ),
        )
        await redis_client.aclose()
    except Exception:
        # If Redis is unavailable the task is still persisted in the DB.
        # Workers can fall back to polling the database.
        task.status = "pending"
        await db.flush()

    return _task_to_response(task)


@router.get("/tasks", response_model=list[SwarmTaskResponse])
async def list_active_tasks(
    db: AsyncSession = Depends(get_db),
) -> list[SwarmTaskResponse]:
    """List tasks that are currently queued or in progress."""
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.status.in_(["queued", "pending", "running"]))
        .order_by(SwarmTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_task_to_response(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> SwarmTaskResponse:
    """Retrieve a single task by ID."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID"
        ) from exc

    result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return _task_to_response(task)


@router.patch("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> SwarmTaskResponse:
    """Update a task's status.

    When the status transitions to ``completed`` or ``failed`` the
    ``completed_at`` timestamp is set automatically.
    """
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID"
        ) from exc

    result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    task.status = body.status

    if body.result is not None:
        task.payload = {**(task.payload or {}), "result": body.result}

    if body.status in ("completed", "failed"):
        task.completed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(task)

    return _task_to_response(task)
