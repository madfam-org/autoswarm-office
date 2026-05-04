"""Map CRUD, import/export endpoints for the in-browser map editor."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_non_guest
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import Map
from ..tenant import TenantContext, get_tenant

router = APIRouter(tags=["maps"], dependencies=[Depends(get_current_user)])


# -- Request / Response schemas ------------------------------------------------


class MapCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    tmj_content: str = Field(..., min_length=1)


class MapUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tmj_content: str | None = None


class MapResponse(BaseModel):
    id: str
    name: str
    description: str
    tmj_content: str
    org_id: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MapListResponse(BaseModel):
    items: list[MapResponse]
    total: int
    limit: int
    offset: int


class MapImportRequest(BaseModel):
    tmj_content: str = Field(..., min_length=1)


# -- Helpers -------------------------------------------------------------------


def _map_to_response(m: Map) -> MapResponse:
    return MapResponse(
        id=str(m.id),
        name=m.name,
        description=m.description,
        tmj_content=m.tmj_content,
        org_id=m.org_id,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )


def _validate_tmj(tmj_content: str) -> dict[str, Any]:
    """Parse and perform basic validation on TMJ content.

    Returns the parsed dict on success, raises HTTPException on failure.
    """
    try:
        data: Any = json.loads(tmj_content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid TMJ JSON", "errors": [str(exc)]},
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "TMJ content must be a JSON object"},
        )

    # Basic structure validation
    if "layers" not in data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "TMJ must contain a 'layers' field"},
        )

    return data


# -- Endpoints -----------------------------------------------------------------


@router.post(
    "",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_map(
    body: MapCreateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> MapResponse:
    """Create a new map definition.

    Idempotency: replay-safe via the ``Idempotency-Key`` header. A retry
    after a network blip should NOT produce a second Map row with the
    same content. The cached response (containing the original map id)
    is returned on replay.
    """
    if idem.is_replay and idem.cached is not None:
        return MapResponse.model_validate(idem.cached)

    _validate_tmj(body.tmj_content)

    m = Map(
        name=body.name,
        description=body.description,
        tmj_content=body.tmj_content,
        org_id=tenant.org_id,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)

    # Late import to avoid the events router → maps circular risk.
    # Mirror the pattern in stripe_webhooks.py / approvals.py / swarms.py.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="map.created",
        event_category="map",
        org_id=tenant.org_id,
        payload={"map_id": str(m.id), "name": m.name},
    )
    await db.flush()

    response = _map_to_response(m)
    await idem.save(response.model_dump(mode="json"))
    return response


@router.get("", response_model=MapListResponse)
async def list_maps(
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> MapListResponse:
    """List all maps for the current tenant with pagination."""
    base_stmt = select(Map).where(Map.org_id == tenant.org_id)

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(base_stmt.order_by(Map.updated_at.desc()).limit(limit).offset(offset))
    maps = result.scalars().all()
    return MapListResponse(
        items=[_map_to_response(m) for m in maps],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{map_id}", response_model=MapResponse)
async def get_map(
    map_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> MapResponse:
    """Get a single map by ID."""
    m = await _get_map_or_404(map_id, db)
    return _map_to_response(m)


@router.put("/{map_id}", response_model=MapResponse, dependencies=[Depends(require_non_guest)])
async def update_map(
    map_id: str,
    body: MapUpdateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> MapResponse:
    """Update an existing map definition."""
    m = await _get_map_or_404(map_id, db)

    fields_updated: list[str] = []

    if body.tmj_content is not None:
        _validate_tmj(body.tmj_content)
        m.tmj_content = body.tmj_content
        fields_updated.append("tmj_content")

    if body.name is not None:
        m.name = body.name
        fields_updated.append("name")
    if body.description is not None:
        m.description = body.description
        fields_updated.append("description")

    m.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(m)

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="map.updated",
        event_category="map",
        org_id=tenant.org_id,
        payload={
            "map_id": str(m.id),
            "fields_updated": fields_updated,
        },
    )
    await db.flush()

    return _map_to_response(m)


@router.delete(
    "/{map_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_non_guest)],
)
async def delete_map(
    map_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> None:
    """Delete a map definition."""
    m = await _get_map_or_404(map_id, db)
    # Capture identifiers BEFORE delete so the event payload survives the
    # session-level expiration of the deleted ORM object.
    map_id_str = str(m.id)
    map_name = m.name
    await db.delete(m)
    await db.flush()

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="map.deleted",
        event_category="map",
        org_id=tenant.org_id,
        payload={"map_id": map_id_str, "name": map_name},
    )
    await db.flush()


@router.post("/export")
async def export_map(
    body: MapImportRequest,
) -> dict[str, str]:
    """Validate TMJ content and return it (for download)."""
    _validate_tmj(body.tmj_content)
    return {"tmj_content": body.tmj_content}


@router.post("/import", response_model=MapResponse, status_code=status.HTTP_201_CREATED)
async def import_map(
    body: MapImportRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> MapResponse:
    """Import a TMJ file as a new map.

    Idempotency: replay-safe via the ``Idempotency-Key`` header. A retried
    upload should NOT produce a duplicate Map row.
    """
    if idem.is_replay and idem.cached is not None:
        return MapResponse.model_validate(idem.cached)

    parsed = _validate_tmj(body.tmj_content)

    # Try to extract a name from TMJ metadata
    name = "Imported Map"
    properties = parsed.get("properties")
    if isinstance(properties, list):
        for prop in properties:
            if isinstance(prop, dict) and prop.get("name") == "name":
                name = str(prop.get("value", name))
                break

    m = Map(
        name=name,
        description="Imported from TMJ file",
        tmj_content=body.tmj_content,
        org_id=tenant.org_id,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="map.imported",
        event_category="map",
        org_id=tenant.org_id,
        payload={"map_id": str(m.id), "name": m.name},
    )
    await db.flush()

    response = _map_to_response(m)
    await idem.save(response.model_dump(mode="json"))
    return response


# -- Internal helpers ----------------------------------------------------------


async def _get_map_or_404(map_id: str, db: AsyncSession) -> Map:
    try:
        uid = uuid.UUID(map_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(Map).where(Map.id == uid))
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")
    return m
