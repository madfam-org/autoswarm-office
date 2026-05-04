"""CRUD endpoints for swarm agents."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from selva_skills import DEFAULT_ROLE_SKILLS
except ImportError:
    # Fallback when the workspace package is not importable (e.g. partial
    # install).  Re-annotating the symbol here triggered mypy's `no-redef`;
    # the bare assignment keeps the original `dict[str, list[str]]` type
    # inferred from the import branch.
    DEFAULT_ROLE_SKILLS = {}

from ..auth import get_current_user
from ..database import get_db
from ..models import Agent
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agents"], dependencies=[Depends(get_current_user)])


# -- Request / Response schemas -----------------------------------------------


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="coder", pattern=r"^(planner|coder|reviewer|researcher|crm|support)$")
    level: int = Field(default=1, ge=1, le=10)
    department_id: str | None = None
    skill_ids: list[str] | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(
        default=None, pattern=r"^(planner|coder|reviewer|researcher|crm|support)$"
    )
    status: str | None = Field(
        default=None,
        pattern=r"^(idle|working|waiting_approval|paused|error)$",
    )
    level: int | None = Field(default=None, ge=1, le=10)
    skill_ids: list[str] | None = None


class AgentAssign(BaseModel):
    department_id: str


class AgentResponse(BaseModel):
    id: str
    name: str
    role: str
    status: str
    level: int
    department_id: str | None
    current_task_id: str | None
    skill_ids: list[str] | None
    effective_skills: list[str]
    synergy_data: dict[str, Any] | None
    tasks_completed: int = 0
    tasks_failed: int = 0
    approval_success_count: int = 0
    approval_denial_count: int = 0
    avg_task_duration_seconds: float | None = None
    last_task_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    items: list[AgentResponse]
    total: int
    limit: int
    offset: int


class AgentStatsUpdate(BaseModel):
    """Delta increments for agent performance stats. Worker-to-API."""

    tasks_completed_delta: int = Field(default=0, ge=0)
    tasks_failed_delta: int = Field(default=0, ge=0)
    approval_success_delta: int = Field(default=0, ge=0)
    approval_denial_delta: int = Field(default=0, ge=0)
    task_duration_seconds: float | None = Field(default=None, ge=0)


# -- Helpers ------------------------------------------------------------------


def _agent_to_response(agent: Agent) -> AgentResponse:
    effective_skills = agent.skill_ids or DEFAULT_ROLE_SKILLS.get(agent.role, [])
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        role=agent.role,
        status=agent.status,
        level=agent.level,
        department_id=str(agent.department_id) if agent.department_id else None,
        current_task_id=str(agent.current_task_id) if agent.current_task_id else None,
        skill_ids=agent.skill_ids,
        effective_skills=effective_skills,
        synergy_data=agent.synergy_data,
        tasks_completed=agent.tasks_completed,
        tasks_failed=agent.tasks_failed,
        approval_success_count=agent.approval_success_count,
        approval_denial_count=agent.approval_denial_count,
        avg_task_duration_seconds=agent.avg_task_duration_seconds,
        last_task_at=agent.last_task_at,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def _get_agent_or_404(agent_id: str, db: AsyncSession) -> Agent:
    try:
        uid = uuid.UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(Agent).where(Agent.id == uid))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


# -- Endpoints ----------------------------------------------------------------


@router.get("/", response_model=AgentListResponse)
async def list_agents(
    department_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> AgentListResponse:
    """List agents with pagination, optionally filtered by department."""
    base_stmt = select(Agent).where(Agent.org_id == tenant.org_id)
    if department_id is not None:
        try:
            dept_uid = uuid.UUID(department_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid department UUID"
            ) from exc
        base_stmt = base_stmt.where(Agent.department_id == dept_uid)

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(
        base_stmt.order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    )
    agents = result.scalars().all()
    return AgentListResponse(
        items=[_agent_to_response(a) for a in agents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> AgentResponse:
    """Draft a new agent."""
    agent = Agent(
        name=body.name,
        role=body.role,
        level=body.level,
        department_id=uuid.UUID(body.department_id) if body.department_id else None,
        skill_ids=body.skill_ids,
        org_id=tenant.org_id,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)

    # Audit trail: emit agent.created event. Per-tenant agent roster
    # changes are customer-visible in the office UI sidebar; ops needs
    # the event for "tenant complained their agent vanished — when did
    # the create/delete happen?". See gap doc #7. NOTE: agent.name is
    # PII-adjacent (operator-chosen, but can include user IDs in some
    # tenants), so we deliberately omit it from the payload — the
    # agent_id is enough to look up the row. role/level are not PII.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="agent.created",
            event_category="agent",
            agent_id=agent.id,
            org_id=tenant.org_id,
            payload={
                "agent_id": str(agent.id),
                "role": agent.role,
                "level": agent.level,
                "department_id": str(agent.department_id) if agent.department_id else None,
                "skill_count": len(agent.skill_ids) if agent.skill_ids else 0,
            },
        )
    except Exception:
        logger.warning("Failed to emit agent.created audit event", exc_info=True)

    return _agent_to_response(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Retrieve a single agent by ID."""
    agent = await _get_agent_or_404(agent_id, db)
    return _agent_to_response(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Update mutable agent fields."""
    agent = await _get_agent_or_404(agent_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(agent, field_name, value)

    agent.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(agent)

    # Audit trail: emit agent.updated event. Carries only the *names* of
    # changed fields, not the values — values like name can be PII-adjacent
    # and the agent_id is enough to retrieve the new state. org_id is read
    # from the agent row itself (resource-of-record), matching the
    # update_task_status pattern.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="agent.updated",
            event_category="agent",
            agent_id=agent.id,
            org_id=agent.org_id,
            payload={
                "agent_id": str(agent.id),
                "fields_changed": sorted(update_data.keys()),
            },
        )
    except Exception:
        logger.warning("Failed to emit agent.updated audit event", exc_info=True)

    return _agent_to_response(agent)


@router.post("/{agent_id}/assign", response_model=AgentResponse)
async def assign_agent(
    agent_id: str,
    body: AgentAssign,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Assign an agent to a department."""
    agent = await _get_agent_or_404(agent_id, db)

    try:
        dept_uid = uuid.UUID(body.department_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid department UUID"
        ) from exc

    previous_department_id = agent.department_id
    agent.department_id = dept_uid
    agent.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(agent)

    # Audit trail: emit agent.assigned event. Department reassignments
    # change which patrol zone the agent occupies and which review
    # station it walks to — a customer-visible change that ops needs to
    # answer "who moved my agent at 14:22?". UUIDs only, no PII.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="agent.assigned",
            event_category="agent",
            agent_id=agent.id,
            org_id=agent.org_id,
            payload={
                "agent_id": str(agent.id),
                "previous_department_id": (
                    str(previous_department_id) if previous_department_id else None
                ),
                "new_department_id": str(dept_uid),
            },
        )
    except Exception:
        logger.warning("Failed to emit agent.assigned audit event", exc_info=True)

    return _agent_to_response(agent)


@router.patch("/{agent_id}/stats", response_model=AgentResponse)
async def update_agent_stats(
    agent_id: str,
    body: AgentStatsUpdate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AgentResponse:
    """Apply delta increments to agent performance stats.

    Worker-to-API endpoint — no user auth required (Bearer token only).
    Computes a running average for task duration.
    """
    agent = await _get_agent_or_404(agent_id, db)

    agent.tasks_completed += body.tasks_completed_delta
    agent.tasks_failed += body.tasks_failed_delta
    agent.approval_success_count += body.approval_success_delta
    agent.approval_denial_count += body.approval_denial_delta

    # Compute running average duration
    if body.task_duration_seconds is not None:
        total_tasks = agent.tasks_completed + agent.tasks_failed
        if agent.avg_task_duration_seconds is not None and total_tasks > 1:
            # Incremental mean: new_avg = old_avg + (new_val - old_avg) / n
            agent.avg_task_duration_seconds = (
                agent.avg_task_duration_seconds
                + (body.task_duration_seconds - agent.avg_task_duration_seconds) / total_tasks
            )
        else:
            agent.avg_task_duration_seconds = body.task_duration_seconds

    # Update last_task_at whenever any delta is applied
    if (
        body.tasks_completed_delta
        or body.tasks_failed_delta
        or body.task_duration_seconds is not None
    ):
        agent.last_task_at = datetime.now(UTC)

    agent.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(agent)
    return _agent_to_response(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove an agent permanently."""
    agent = await _get_agent_or_404(agent_id, db)

    # Capture identifying scalars BEFORE deletion — once db.delete() runs
    # and we flush, accessing agent.org_id / agent.id can hit a
    # DetachedInstanceError in some session configurations.
    deleted_agent_id_str = str(agent.id)
    deleted_role = agent.role
    deleted_org_id = agent.org_id

    await db.delete(agent)
    await db.flush()

    # Audit trail: emit agent.deleted event. The most important agent
    # event for ops triage — "tenant complained their agent vanished",
    # answer requires the timestamp + actor in the event log. We
    # deliberately omit the agent name (PII-adjacent) but keep the role
    # so the activity feed can render "Coder agent deleted" without
    # leaking the operator-chosen name.
    #
    # NOTE: agent_id is intentionally NOT passed to the FK column on
    # TaskEvent — the row was just deleted, and even though the FK has
    # ondelete=SET NULL it would still fail the immediate INSERT
    # validation. The deleted UUID lives in payload.agent_id instead so
    # ops can still cross-reference.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="agent.deleted",
            event_category="agent",
            org_id=deleted_org_id,
            payload={
                "agent_id": deleted_agent_id_str,
                "role": deleted_role,
            },
        )
    except Exception:
        logger.warning("Failed to emit agent.deleted audit event", exc_info=True)
