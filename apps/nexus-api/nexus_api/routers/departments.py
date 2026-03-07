"""CRUD endpoints for departments (virtual office rooms)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Department
from ..tenant import TenantContext, get_tenant

router = APIRouter(tags=["departments"], dependencies=[Depends(get_current_user)])


# -- Request / Response schemas -----------------------------------------------


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9\-]+$")
    description: str = ""
    max_agents: int = Field(default=5, ge=1, le=50)
    position_x: int = 0
    position_y: int = 0


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    max_agents: int | None = Field(default=None, ge=1, le=50)
    position_x: int | None = None
    position_y: int | None = None


class AgentSummary(BaseModel):
    id: str
    name: str
    role: str
    status: str
    level: int
    current_task_id: str | None = None
    effective_skills: list[str] = []

    model_config = {"from_attributes": True}


class DepartmentResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    max_agents: int
    position_x: int
    position_y: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentDetailResponse(DepartmentResponse):
    agents: list[AgentSummary]


# -- Helpers ------------------------------------------------------------------


def _dept_to_response(dept: Department) -> DepartmentResponse:
    return DepartmentResponse(
        id=str(dept.id),
        name=dept.name,
        slug=dept.slug,
        description=dept.description,
        max_agents=dept.max_agents,
        position_x=dept.position_x,
        position_y=dept.position_y,
        created_at=dept.created_at,
        updated_at=dept.updated_at,
    )


def _dept_to_detail(dept: Department) -> DepartmentDetailResponse:
    return DepartmentDetailResponse(
        id=str(dept.id),
        name=dept.name,
        slug=dept.slug,
        description=dept.description,
        max_agents=dept.max_agents,
        position_x=dept.position_x,
        position_y=dept.position_y,
        created_at=dept.created_at,
        updated_at=dept.updated_at,
        agents=[
            AgentSummary(
                id=str(a.id),
                name=a.name,
                role=a.role,
                status=a.status,
                level=a.level,
                current_task_id=str(a.current_task_id) if a.current_task_id else None,
                effective_skills=a.skill_ids or [],
            )
            for a in dept.agents
        ],
    )


async def _get_dept_or_404(dept_id: str, db: AsyncSession) -> Department:
    try:
        uid = uuid.UUID(dept_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID"
        ) from exc

    result = await db.execute(select(Department).where(Department.id == uid))
    dept = result.scalar_one_or_none()
    if dept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found"
        )
    return dept


# -- Endpoints ----------------------------------------------------------------


@router.get("/", response_model=list[DepartmentResponse])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[DepartmentResponse]:
    """List all departments."""
    result = await db.execute(
        select(Department).where(Department.org_id == tenant.org_id).order_by(Department.name)
    )
    departments = result.scalars().all()
    return [_dept_to_response(d) for d in departments]


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> DepartmentResponse:
    """Create a new department."""
    # Uniqueness check on slug.
    existing = await db.execute(select(Department).where(Department.slug == body.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department with slug '{body.slug}' already exists",
        )

    dept = Department(
        name=body.name,
        slug=body.slug,
        description=body.description,
        max_agents=body.max_agents,
        position_x=body.position_x,
        position_y=body.position_y,
        org_id=tenant.org_id,
    )
    db.add(dept)
    await db.flush()
    await db.refresh(dept)
    return _dept_to_response(dept)


@router.get("/{dept_id}", response_model=DepartmentDetailResponse)
async def get_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
) -> DepartmentDetailResponse:
    """Retrieve a department with its agents."""
    dept = await _get_dept_or_404(dept_id, db)
    return _dept_to_detail(dept)


@router.put("/{dept_id}", response_model=DepartmentResponse)
async def update_department(
    dept_id: str,
    body: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
) -> DepartmentResponse:
    """Update mutable department fields."""
    dept = await _get_dept_or_404(dept_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(dept, field_name, value)

    dept.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(dept)
    return _dept_to_response(dept)
