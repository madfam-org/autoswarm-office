"""CRUD endpoints for swarm agents."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoswarm_skills import DEFAULT_ROLE_SKILLS

from ..auth import get_current_user
from ..database import get_db
from ..models import Agent

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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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


@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    department_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[AgentResponse]:
    """List all agents, optionally filtered by department."""
    stmt = select(Agent)
    if department_id is not None:
        try:
            dept_uid = uuid.UUID(department_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid department UUID"
            ) from exc
        stmt = stmt.where(Agent.department_id == dept_uid)

    result = await db.execute(stmt.order_by(Agent.created_at.desc()))
    agents = result.scalars().all()
    return [_agent_to_response(a) for a in agents]


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Draft a new agent."""
    agent = Agent(
        name=body.name,
        role=body.role,
        level=body.level,
        department_id=uuid.UUID(body.department_id) if body.department_id else None,
        skill_ids=body.skill_ids,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
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

    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
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

    agent.department_id = dept_uid
    agent.updated_at = datetime.now(timezone.utc)
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
    await db.delete(agent)
    await db.flush()
