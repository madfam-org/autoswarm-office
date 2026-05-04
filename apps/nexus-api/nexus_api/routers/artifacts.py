"""CRUD endpoints for task artifacts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_tools.storage import LocalFSStorage

from ..auth import get_current_user
from ..database import get_db
from ..models import Artifact
from ..tenant import TenantContext, get_tenant

router = APIRouter(tags=["artifacts"], dependencies=[Depends(get_current_user)])  # noqa: B008

_storage = LocalFSStorage()


# -- Response schemas ----------------------------------------------------------


class ArtifactResponse(BaseModel):
    id: str
    task_id: str | None
    agent_id: str | None
    name: str
    content_type: str
    content_hash: str
    size_bytes: int
    metadata: dict | None
    created_at: str

    model_config = {"from_attributes": True}


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactResponse]
    total: int
    limit: int
    offset: int


# -- Endpoints -----------------------------------------------------------------


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts(
    task_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ArtifactListResponse:
    """List artifacts with pagination, optionally filtered by task_id."""
    base_stmt = select(Artifact).where(Artifact.org_id == tenant.org_id)
    if task_id:
        base_stmt = base_stmt.where(Artifact.task_id == uuid.UUID(task_id))

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(
        base_stmt.order_by(Artifact.created_at.desc()).limit(limit).offset(offset)
    )
    rows = result.scalars().all()

    items = [
        ArtifactResponse(
            id=str(a.id),
            task_id=str(a.task_id) if a.task_id else None,
            agent_id=a.agent_id,
            name=a.name,
            content_type=a.content_type,
            content_hash=a.content_hash,
            size_bytes=a.size_bytes,
            metadata=a.extra_metadata,
            created_at=a.created_at.isoformat(),
        )
        for a in rows
    ]
    return ArtifactListResponse(artifacts=items, total=total, limit=limit, offset=offset)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ArtifactResponse:
    """Get artifact metadata by ID."""
    stmt = (
        select(Artifact)
        .where(Artifact.id == uuid.UUID(artifact_id))
        .where(Artifact.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    return ArtifactResponse(
        id=str(artifact.id),
        task_id=str(artifact.task_id) if artifact.task_id else None,
        agent_id=artifact.agent_id,
        name=artifact.name,
        content_type=artifact.content_type,
        content_hash=artifact.content_hash,
        size_bytes=artifact.size_bytes,
        metadata=artifact.extra_metadata,
        created_at=artifact.created_at.isoformat(),
    )


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> Response:
    """Stream artifact content."""
    stmt = (
        select(Artifact)
        .where(Artifact.id == uuid.UUID(artifact_id))
        .where(Artifact.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    try:
        content = await _storage.retrieve(artifact.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact content not found in storage"
        ) from exc

    return Response(
        content=content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.name}"',
        },
    )


class DeleteResponse(BaseModel):
    deleted: bool = Field(default=True)


@router.delete("/{artifact_id}", response_model=DeleteResponse)
async def delete_artifact(
    artifact_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> DeleteResponse:
    """Delete an artifact by ID."""
    stmt = (
        select(Artifact)
        .where(Artifact.id == uuid.UUID(artifact_id))
        .where(Artifact.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    # Capture identifying fields BEFORE delete so the audit payload
    # records them post-deletion (the row + storage object are gone
    # after the delete calls below).
    artifact_id_str = str(artifact.id)
    task_id_str = str(artifact.task_id) if artifact.task_id else None
    content_hash = artifact.content_hash
    size_bytes = artifact.size_bytes

    await _storage.delete(artifact.storage_path)
    await db.delete(artifact)
    await db.commit()

    # Audit trail: emit an event so the office UI activity feed surfaces
    # artifact deletions (this is the only artifact mutation that loses
    # data — list/download/get are read-only). Late import to avoid
    # circular import with the events router. ``org_id`` comes from the
    # JWT-derived tenant context. Payload records IDs + content hash +
    # size, NOT the artifact name (could be tenant content).
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="artifact.deleted",
        event_category="artifact",
        org_id=tenant.org_id,
        payload={
            "artifact_id": artifact_id_str,
            "task_id": task_id_str,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
        },
    )
    await db.commit()

    return DeleteResponse()
