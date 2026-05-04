"""Workflow CRUD, import/export, validation, and template endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_non_guest
from ..database import get_db
from ..models import Workflow
from ..tenant import TenantContext, get_tenant

router = APIRouter(tags=["workflows"], dependencies=[Depends(get_current_user)])

# Path to the built-in workflow templates directory
_TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "data" / "workflow-templates"

# Category inference from template filename
_FILENAME_CATEGORY_MAP: dict[str, str] = {
    "3d-modeling.yaml": "Creative",
    "video-production.yaml": "Creative",
    "data-analysis.yaml": "Data",
    "devops-pipeline.yaml": "Operations",
    "content-marketing.yaml": "Operations",
}


# -- Request / Response schemas ------------------------------------------------


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    yaml_content: str = Field(..., min_length=1)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    yaml_content: str | None = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    version: str
    description: str
    yaml_content: str
    org_id: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class WorkflowValidationResponse(BaseModel):
    is_valid: bool
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


class WorkflowImportRequest(BaseModel):
    yaml_content: str = Field(..., min_length=1)


class WorkflowTemplateResponse(BaseModel):
    name: str
    description: str
    filename: str
    category: str
    node_count: int


class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class CreateFromTemplateRequest(BaseModel):
    template_filename: str = Field(..., pattern=r"^[a-z0-9-]+\.yaml$")
    name: str | None = None


# -- Helpers -------------------------------------------------------------------


def _workflow_to_response(wf: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=str(wf.id),
        name=wf.name,
        version=wf.version,
        description=wf.description,
        yaml_content=wf.yaml_content,
        org_id=wf.org_id,
        created_at=wf.created_at.isoformat(),
        updated_at=wf.updated_at.isoformat(),
    )


def _validate_yaml(yaml_content: str) -> WorkflowValidationResponse:
    """Parse and validate a YAML workflow definition."""
    from selva_workflows import WorkflowSerializer, WorkflowValidator

    try:
        workflow_def = WorkflowSerializer.from_yaml(yaml_content)
    except Exception as exc:
        return WorkflowValidationResponse(
            is_valid=False,
            errors=[{"code": "PARSE_ERROR", "message": str(exc)}],
            warnings=[],
        )

    validator = WorkflowValidator()
    result = validator.validate(workflow_def)
    return WorkflowValidationResponse(
        is_valid=result.is_valid,
        errors=[
            {"code": e.code, "message": e.message, "node_id": e.node_id} for e in result.errors
        ],
        warnings=[
            {"code": w.code, "message": w.message, "node_id": w.node_id} for w in result.warnings
        ],
    )


# -- Endpoints -----------------------------------------------------------------


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_workflow(
    body: WorkflowCreateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> WorkflowResponse:
    """Create a new workflow definition."""
    # Validate the YAML before persisting
    validation = _validate_yaml(body.yaml_content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid workflow YAML", "errors": validation.errors},
        )

    # Extract version from parsed YAML
    from selva_workflows import WorkflowSerializer

    parsed = WorkflowSerializer.from_yaml(body.yaml_content)

    wf = Workflow(
        name=body.name,
        version=parsed.version,
        description=body.description or parsed.description,
        yaml_content=body.yaml_content,
        org_id=tenant.org_id,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)

    # Late import to avoid the events router → workflows circular risk.
    # Mirror the pattern in stripe_webhooks.py / approvals.py / swarms.py.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="workflow.created",
        event_category="workflow",
        org_id=tenant.org_id,
        payload={
            "workflow_id": str(wf.id),
            "name": wf.name,
            "version": wf.version,
        },
    )
    await db.flush()

    return _workflow_to_response(wf)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> WorkflowListResponse:
    """List all workflows for the current tenant with pagination."""
    base_stmt = select(Workflow).where(Workflow.org_id == tenant.org_id)

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(
        base_stmt.order_by(Workflow.updated_at.desc()).limit(limit).offset(offset)
    )
    workflows = result.scalars().all()
    return WorkflowListResponse(
        items=[_workflow_to_response(wf) for wf in workflows],
        total=total,
        limit=limit,
        offset=offset,
    )


# -- Template endpoints (before /{workflow_id} to avoid route conflict) --------


@router.get("/templates", response_model=list[WorkflowTemplateResponse])
async def list_templates() -> list[WorkflowTemplateResponse]:
    """List available workflow templates from data/workflow-templates/."""
    from selva_workflows import WorkflowSerializer

    templates: list[WorkflowTemplateResponse] = []

    if not _TEMPLATES_DIR.is_dir():
        return templates

    for yaml_file in sorted(_TEMPLATES_DIR.glob("*.yaml")):
        try:
            yaml_content = yaml_file.read_text(encoding="utf-8")
            workflow_def = WorkflowSerializer.from_yaml(yaml_content)
            category = _FILENAME_CATEGORY_MAP.get(yaml_file.name, "Other")
            templates.append(
                WorkflowTemplateResponse(
                    name=workflow_def.name,
                    description=workflow_def.description,
                    filename=yaml_file.name,
                    category=category,
                    node_count=len(workflow_def.nodes),
                )
            )
        except Exception:
            # Skip files that fail to parse
            continue

    return templates


@router.post(
    "/from-template",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_template(
    body: CreateFromTemplateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> WorkflowResponse:
    """Create a new workflow from a built-in template."""
    template_path = _TEMPLATES_DIR / body.template_filename

    if not template_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{body.template_filename}' not found",
        )

    yaml_content = template_path.read_text(encoding="utf-8")

    # Validate the template YAML
    validation = _validate_yaml(yaml_content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Template YAML is invalid",
                "errors": validation.errors,
            },
        )

    from selva_workflows import WorkflowSerializer

    parsed = WorkflowSerializer.from_yaml(yaml_content)
    workflow_name = body.name or parsed.name

    wf = Workflow(
        name=workflow_name,
        version=parsed.version,
        description=parsed.description,
        yaml_content=yaml_content,
        org_id=tenant.org_id,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    return _workflow_to_response(wf)


# -- Parameterized endpoints ---------------------------------------------------


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> WorkflowResponse:
    """Get a single workflow by ID."""
    wf = await _get_workflow_or_404(workflow_id, db)
    return _workflow_to_response(wf)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    dependencies=[Depends(require_non_guest)],
)
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> WorkflowResponse:
    """Update an existing workflow definition."""
    wf = await _get_workflow_or_404(workflow_id, db)

    # Track which fields were updated for the audit-trail payload (no PII).
    fields_updated: list[str] = []

    if body.yaml_content is not None:
        validation = _validate_yaml(body.yaml_content)
        if not validation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Invalid workflow YAML", "errors": validation.errors},
            )
        wf.yaml_content = body.yaml_content

        from selva_workflows import WorkflowSerializer

        parsed = WorkflowSerializer.from_yaml(body.yaml_content)
        wf.version = parsed.version
        fields_updated.append("yaml_content")

    if body.name is not None:
        wf.name = body.name
        fields_updated.append("name")
    if body.description is not None:
        wf.description = body.description
        fields_updated.append("description")

    wf.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(wf)

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="workflow.updated",
        event_category="workflow",
        org_id=tenant.org_id,
        payload={
            "workflow_id": str(wf.id),
            "version": wf.version,
            "fields_updated": fields_updated,
        },
    )
    await db.flush()

    return _workflow_to_response(wf)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_non_guest)],
)
async def delete_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> None:
    """Delete a workflow definition."""
    wf = await _get_workflow_or_404(workflow_id, db)
    # Capture identifiers BEFORE delete so the event payload survives the
    # session-level expiration of the deleted ORM object.
    wf_id = str(wf.id)
    wf_name = wf.name
    wf_version = wf.version
    await db.delete(wf)
    await db.flush()

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="workflow.deleted",
        event_category="workflow",
        org_id=tenant.org_id,
        payload={
            "workflow_id": wf_id,
            "name": wf_name,
            "version": wf_version,
        },
    )
    await db.flush()


@router.post("/validate", response_model=WorkflowValidationResponse)
async def validate_workflow(
    body: WorkflowImportRequest,
) -> WorkflowValidationResponse:
    """Validate a workflow YAML without persisting it."""
    return _validate_yaml(body.yaml_content)


@router.post("/import", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def import_workflow(
    body: WorkflowImportRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> WorkflowResponse:
    """Import a workflow from YAML content."""
    validation = _validate_yaml(body.yaml_content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid workflow YAML", "errors": validation.errors},
        )

    from selva_workflows import WorkflowSerializer

    parsed = WorkflowSerializer.from_yaml(body.yaml_content)

    wf = Workflow(
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        yaml_content=body.yaml_content,
        org_id=tenant.org_id,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)

    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="workflow.imported",
        event_category="workflow",
        org_id=tenant.org_id,
        payload={
            "workflow_id": str(wf.id),
            "name": wf.name,
            "version": wf.version,
        },
    )
    await db.flush()

    return _workflow_to_response(wf)


@router.get("/{workflow_id}/export")
async def export_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Export a workflow as YAML content."""
    wf = await _get_workflow_or_404(workflow_id, db)
    return {"yaml_content": wf.yaml_content}


# -- Internal helpers ----------------------------------------------------------


async def _get_workflow_or_404(workflow_id: str, db: AsyncSession) -> Workflow:
    try:
        uid = uuid.UUID(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(Workflow).where(Workflow.id == uid))
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return wf
