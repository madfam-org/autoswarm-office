"""Tenant identities — the central cross-service id map.

Backs the Phase 2 tenant_identity tools (tenant_create_identity_record /
tenant_resolve / tenant_validate_consistency). Worker-only surface;
authenticates via WORKER_API_TOKEN.

Surface:
    POST /api/v1/tenant-identities          — create a row
    GET  /api/v1/tenant-identities/resolve  — lookup by any per-service id
    POST /api/v1/tenant-identities/{id}/validate — drift check (stub impl;
        returns services_checked + empty drifts until we wire per-service
        probes — tracked as a follow-up)
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..database import async_session_factory
from ..models import TenantIdentity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tenant Identities"])


_RESOLVE_FIELDS = {
    "canonical_id",
    "janua_org_id",
    "dhanam_space_id",
    "phyndcrm_tenant_id",
    "karafiel_org_id",
}


def _require_worker_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Shared worker auth pattern (mirrors hitl_confidence internal POST)."""
    settings = get_settings()
    expected = settings.worker_api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="worker_api_token not configured",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer token",
        )
    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker token",
        )


# --- Schemas -----------------------------------------------------------------


class TenantIdentityCreate(BaseModel):
    canonical_id: str = Field(..., min_length=1, max_length=128)
    legal_name: str = Field(..., min_length=1, max_length=512)
    primary_contact_email: str | None = None
    janua_org_id: str | None = None
    dhanam_space_id: str | None = None
    phyndcrm_tenant_id: str | None = None
    karafiel_org_id: str | None = None
    resend_domain_ids: list[str] | None = None
    cloudflare_zone_ids: list[str] | None = None
    selva_office_seat_ids: list[str] | None = None
    r2_bucket_names: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TenantIdentityResponse(BaseModel):
    id: str
    canonical_id: str
    legal_name: str
    primary_contact_email: str | None
    janua_org_id: str | None
    dhanam_space_id: str | None
    phyndcrm_tenant_id: str | None
    karafiel_org_id: str | None
    resend_domain_ids: list[str] | None
    cloudflare_zone_ids: list[str] | None
    selva_office_seat_ids: list[str] | None
    r2_bucket_names: list[str] | None
    meta: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ValidateConsistencyResponse(BaseModel):
    canonical_id: str
    services_checked: int
    drifts: list[dict[str, Any]]
    checked_at: datetime


def _to_response(row: TenantIdentity) -> TenantIdentityResponse:
    return TenantIdentityResponse(
        id=str(row.id),
        canonical_id=row.canonical_id,
        legal_name=row.legal_name,
        primary_contact_email=row.primary_contact_email,
        janua_org_id=row.janua_org_id,
        dhanam_space_id=row.dhanam_space_id,
        phyndcrm_tenant_id=row.phyndcrm_tenant_id,
        karafiel_org_id=row.karafiel_org_id,
        resend_domain_ids=row.resend_domain_ids,
        cloudflare_zone_ids=row.cloudflare_zone_ids,
        selva_office_seat_ids=row.selva_office_seat_ids,
        r2_bucket_names=row.r2_bucket_names,
        meta=row.meta,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- Endpoints ---------------------------------------------------------------


@router.post(
    "/tenant-identities",
    response_model=TenantIdentityResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_worker_token)],
)
async def create_tenant_identity(payload: TenantIdentityCreate) -> TenantIdentityResponse:
    """Create a tenant_identities row — call at end of onboarding."""
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(TenantIdentity).where(TenantIdentity.canonical_id == payload.canonical_id)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"tenant_identities row for canonical_id={payload.canonical_id} exists",
            )
        row = TenantIdentity(
            canonical_id=payload.canonical_id,
            legal_name=payload.legal_name,
            primary_contact_email=payload.primary_contact_email,
            janua_org_id=payload.janua_org_id,
            dhanam_space_id=payload.dhanam_space_id,
            phyndcrm_tenant_id=payload.phyndcrm_tenant_id,
            karafiel_org_id=payload.karafiel_org_id,
            resend_domain_ids=payload.resend_domain_ids,
            cloudflare_zone_ids=payload.cloudflare_zone_ids,
            selva_office_seat_ids=payload.selva_office_seat_ids,
            r2_bucket_names=payload.r2_bucket_names,
            meta=payload.metadata,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.info(
            "tenant_identities created canonical_id=%s id=%s",
            row.canonical_id,
            row.id,
        )

        # Audit trail: emit an event when the cross-service identity
        # map row is created. Mirrors the existing
        # ``tenant_identity.updated`` emission in
        # ``onboarding.py:update_tenant_identity`` so the office UI
        # activity feed surfaces every identity-row mutation under one
        # event_type. Payload records IDs + which per-service IDs are
        # populated (NOT the legal_name / primary_contact_email — those
        # are PII and remain in the row, not the audit log). Late
        # import to avoid circular import with the events router.
        from .events import emit_event_db

        populated_services = sorted(
            f
            for f in (
                "janua_org_id",
                "dhanam_space_id",
                "phyndcrm_tenant_id",
                "karafiel_org_id",
            )
            if getattr(row, f)
        )
        await emit_event_db(
            session,
            event_type="tenant.identity_updated",
            event_category="tenant",
            org_id=row.canonical_id,
            payload={
                "tenant_identity_id": str(row.id),
                "canonical_id": row.canonical_id,
                "populated_services": populated_services,
                "operation": "create",
            },
        )
        await session.commit()

        return _to_response(row)


@router.get(
    "/tenant-identities/resolve",
    response_model=TenantIdentityResponse,
    dependencies=[Depends(_require_worker_token)],
)
async def resolve_tenant_identity(
    field: str = Query(
        ...,
        description=(
            "One of: canonical_id, janua_org_id, dhanam_space_id, "
            "phyndcrm_tenant_id, karafiel_org_id"
        ),
    ),
    value: str = Query(..., min_length=1),
) -> TenantIdentityResponse:
    """Resolve a tenant by any per-service id."""
    if field not in _RESOLVE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid field {field!r}; must be one of {sorted(_RESOLVE_FIELDS)}",
        )
    async with async_session_factory() as session:
        col = getattr(TenantIdentity, field)
        row = await session.scalar(select(TenantIdentity).where(col == value))
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no tenant found with {field}={value}",
            )
        return _to_response(row)


@router.post(
    "/tenant-identities/{canonical_id}/validate",
    response_model=ValidateConsistencyResponse,
    dependencies=[Depends(_require_worker_token)],
)
async def validate_tenant_consistency(canonical_id: str) -> ValidateConsistencyResponse:
    """Stub drift check.

    Real implementation needs per-service probes (Janua GET /orgs/{id},
    Dhanam GET /spaces/{id}, PhyndCRM tenants.config, Karafiel GET
    /orgs/{id}, Resend GET /domains/{id}). Tracked as follow-up — this
    endpoint is a placeholder that confirms the row exists and returns
    services_checked based on how many per-service IDs are populated on
    the record.
    """
    async with async_session_factory() as session:
        row = await session.scalar(
            select(TenantIdentity).where(TenantIdentity.canonical_id == canonical_id)
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no tenant_identities row for canonical_id={canonical_id}",
            )
        populated = [
            f
            for f in (
                "janua_org_id",
                "dhanam_space_id",
                "phyndcrm_tenant_id",
                "karafiel_org_id",
            )
            if getattr(row, f)
        ]
        return ValidateConsistencyResponse(
            canonical_id=canonical_id,
            services_checked=len(populated),
            drifts=[],
            checked_at=datetime.now(UTC),
        )
