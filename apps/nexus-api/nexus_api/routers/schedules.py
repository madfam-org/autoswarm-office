"""
Schedules router — Gap 3: Cron Scheduler Integration.

Provides CRUD endpoints for user-defined recurring schedules that Celery Beat
executes unattended, mirroring Hermes Agent's natural-language cron capability.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, require_roles
from ..database import get_db
from ..models import Schedule, ScheduledAction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedules", tags=["Schedules"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ScheduleCreate(BaseModel):
    # `example=` was a pydantic-v1 Field kwarg; v2 surfaces the same value
    # via `json_schema_extra` so the OpenAPI doc still carries the sample
    # crontab.
    cron_expr: str = Field(
        ...,
        description="Standard 5-field crontab expression",
        json_schema_extra={"example": "0 9 * * 1"},
    )
    action: ScheduledAction
    payload: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class ScheduleResponse(BaseModel):
    id: str
    user_id: str
    cron_expr: str
    action: ScheduledAction
    payload: dict[str, Any]
    enabled: bool
    description: str | None
    created_at: str
    last_run_at: str | None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    user: CurrentUser = Depends(require_roles([])),  # Any authenticated user
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    """
    Create a recurring schedule.  The Celery Beat scheduler dynamically
    picks up new entries via the ``schedules`` Postgres table.
    """
    # `CurrentUser` is `dict[str, Any]` — see `nexus_api.auth.get_current_user`.
    # The previous `user.sub` access happened to work at runtime because the
    # dict carries a `sub` key, but mypy correctly flagged it as unsafe.
    user_sub = user["sub"]
    schedule = Schedule(
        user_id=user_sub,
        cron_expr=body.cron_expr,
        action=body.action,
        payload=body.payload,
        description=body.description,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    logger.info(
        "Schedule %s created by user %s: %s @ %s",
        schedule.id,
        user_sub,
        schedule.action,
        schedule.cron_expr,
    )
    return _to_response(schedule)


@router.get("/", response_model=list[ScheduleResponse])
async def list_schedules(
    user: CurrentUser = Depends(require_roles([])),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduleResponse]:
    """Return all schedules owned by the authenticated user."""
    from sqlalchemy import select

    result = await db.execute(
        select(Schedule)
        .where(Schedule.user_id == user["sub"])
        .order_by(Schedule.created_at.desc())
    )
    return [_to_response(s) for s in result.scalars().all()]


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_schedule(
    schedule_id: str,
    user: CurrentUser = Depends(require_roles([])),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Cancel (delete) a schedule. Users may only cancel their own; admins may cancel any."""
    schedule = await db.get(Schedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    user_sub = user["sub"]
    if schedule.user_id != user_sub and "admin" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Cannot cancel another user's schedule")
    await db.delete(schedule)
    await db.commit()
    logger.info("Schedule %s cancelled by %s.", schedule_id, user_sub)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _to_response(s: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=s.id,
        user_id=s.user_id,
        cron_expr=s.cron_expr,
        action=s.action,
        payload=s.payload,
        enabled=s.enabled,
        description=s.description,
        created_at=s.created_at.isoformat() if s.created_at else "",
        last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
    )
