"""Tenant provisioning and management API.

Handles multi-tenant enterprise provisioning including business identity
(RFC, razon social), localization defaults, ecosystem integration
(Karafiel, Dhanam, Phyne), feature flags, and resource limit enforcement.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_non_guest, require_roles
from ..config import get_settings
from ..database import get_db
from ..models import Agent, Department, SwarmTask, TenantConfig
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tenants"], dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# RFC validation (SAT pattern)
# ---------------------------------------------------------------------------

# Mexican RFC: 3-4 letter prefix + 6-digit date + 2-3 alphanumeric check
_RFC_PATTERN = re.compile(r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{2,3}$")


def _validate_rfc_format(rfc: str) -> bool:
    """Validate RFC format against SAT structural rules.

    Does NOT verify with Karafiel (that happens asynchronously during
    provisioning).  Returns True if the format is structurally valid.
    """
    return bool(_RFC_PATTERN.match(rfc.upper().strip()))


# ---------------------------------------------------------------------------
# Mexican department templates
# ---------------------------------------------------------------------------

MEXICAN_DEPARTMENTS: list[dict[str, Any]] = [
    {
        "name": "Direccion General",
        "slug": "direccion",
        "description": "Direccion ejecutiva y planeacion estrategica",
        "max_agents": 3,
    },
    {
        "name": "Administracion",
        "slug": "administracion",
        "description": "Gestion administrativa y recursos",
        "max_agents": 4,
    },
    {
        "name": "Contabilidad",
        "slug": "contabilidad",
        "description": "Contabilidad, facturacion y cumplimiento fiscal",
        "max_agents": 4,
    },
    {
        "name": "Ventas",
        "slug": "ventas",
        "description": "Ventas, CRM y atencion al cliente",
        "max_agents": 6,
    },
    {
        "name": "Operaciones",
        "slug": "operaciones",
        "description": "Operaciones, logistica y cadena de suministro",
        "max_agents": 4,
    },
    {
        "name": "Legal",
        "slug": "legal",
        "description": "Cumplimiento legal, contratos y regulacion",
        "max_agents": 2,
    },
]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    """Create a new tenant org with optional Mexican business identity."""

    org_name: str = Field(..., min_length=1, max_length=255, description="Display name")
    rfc: str | None = Field(
        default=None,
        max_length=13,
        description="RFC fiscal identifier (Mexican tax ID)",
    )
    razon_social: str | None = Field(
        default=None, max_length=500, description="Legal business name"
    )
    regimen_fiscal: str | None = Field(default=None, max_length=10, description="SAT regime code")
    locale: str = Field(default="es-MX", max_length=10)
    timezone: str = Field(default="America/Mexico_City", max_length=50)
    currency: str = Field(default="MXN", max_length=3)

    @field_validator("rfc")
    @classmethod
    def validate_rfc_format(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.upper().strip()
            if not _validate_rfc_format(v):
                raise ValueError(
                    "RFC must match SAT format: 3-4 letters + 6 digits + 2-3 check chars"
                )
        return v


class TenantUpdate(BaseModel):
    """Partial update for tenant settings (non-identity fields)."""

    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=3)
    cfdi_enabled: bool | None = None
    intelligence_enabled: bool | None = None
    max_agents: int | None = Field(default=None, ge=1, le=500)
    max_daily_tasks: int | None = Field(default=None, ge=1, le=10000)


class TenantResponse(BaseModel):
    """Tenant configuration response."""

    id: str
    org_id: str
    rfc: str | None = None
    razon_social: str | None = None
    regimen_fiscal: str | None = None
    locale: str
    timezone: str
    currency: str
    karafiel_org_id: str | None = None
    dhanam_space_id: str | None = None
    phyne_tenant_id: str | None = None
    cfdi_enabled: bool
    intelligence_enabled: bool
    max_agents: int
    max_daily_tasks: int
    # Enterprise SSO
    janua_connection_id: str | None = None
    # White-label branding
    brand_name: str | None = None
    brand_logo_url: str | None = None
    brand_primary_color: str | None = None
    # Outbound voice mode — NULL means onboarding incomplete
    voice_mode: str | None = None
    created_at: str
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class TenantUsageResponse(BaseModel):
    """Current usage stats against tenant limits."""

    org_id: str
    agent_count: int
    agent_limit: int
    tasks_today: int
    task_daily_limit: int
    department_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(config: TenantConfig) -> TenantResponse:
    return TenantResponse(
        id=str(config.id),
        org_id=config.org_id,
        rfc=config.rfc,
        razon_social=config.razon_social,
        regimen_fiscal=config.regimen_fiscal,
        locale=config.locale,
        timezone=config.timezone,
        currency=config.currency,
        karafiel_org_id=config.karafiel_org_id,
        dhanam_space_id=config.dhanam_space_id,
        phyne_tenant_id=config.phyne_tenant_id,
        cfdi_enabled=config.cfdi_enabled,
        intelligence_enabled=config.intelligence_enabled,
        max_agents=config.max_agents,
        max_daily_tasks=config.max_daily_tasks,
        janua_connection_id=config.janua_connection_id,
        brand_name=config.brand_name,
        brand_logo_url=config.brand_logo_url,
        brand_primary_color=config.brand_primary_color,
        voice_mode=config.voice_mode,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


async def _get_tenant_config(db: AsyncSession, org_id: str) -> TenantConfig:
    """Load TenantConfig for an org, raising 404 if not found."""
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not configured for this organization",
        )
    return config


async def _get_tenant_config_or_none(db: AsyncSession, org_id: str) -> TenantConfig | None:
    """Load TenantConfig for an org, returning None if not found."""
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    return result.scalar_one_or_none()


async def _count_tasks_today(db: AsyncSession, org_id: str) -> int:
    """Count tasks dispatched today for a given org."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(SwarmTask.id)).where(
            SwarmTask.org_id == org_id,
            SwarmTask.created_at >= today_start,
        )
    )
    return result.scalar_one()


async def _count_agents(db: AsyncSession, org_id: str) -> int:
    """Count total agents for a given org."""
    result = await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org_id))
    return result.scalar_one()


async def _validate_rfc_with_karafiel(rfc: str) -> None:
    """Validate RFC via Karafiel adapter if available.

    Raises HTTPException(400) when the RFC is rejected by Karafiel.
    Silently passes when Karafiel is not configured or unreachable
    (graceful degradation -- format validation already passed).
    """
    settings = get_settings()
    karafiel_url = getattr(settings, "karafiel_api_url", "") or ""
    if not karafiel_url:
        logger.debug("Karafiel API URL not configured; skipping RFC validation")
        return

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{karafiel_url.rstrip('/')}/v1/rfc/validate",
                json={"rfc": rfc},
            )
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("valid", False):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"RFC rejected by Karafiel: {data.get('reason', 'unknown')}",
                    )
            else:
                logger.warning(
                    "Karafiel RFC validation returned %d; proceeding without validation",
                    resp.status_code,
                )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "Karafiel RFC validation unavailable; proceeding without validation",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_tenant(
    body: TenantCreate,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantResponse:
    """Provision a new tenant org with Mexican business defaults.

    Creates the TenantConfig record and auto-generates Mexican department
    structure (Direccion General, Administracion, Contabilidad, Ventas,
    Operaciones, Legal).

    If an RFC is provided it is validated structurally and optionally via
    Karafiel when configured.
    """
    org_id = user.get("org_id") or str(uuid.uuid4())

    # Check for existing tenant config
    existing = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant config already exists for org_id '{org_id}'",
        )

    # Validate RFC via Karafiel if provided
    if body.rfc:
        await _validate_rfc_with_karafiel(body.rfc)

    # Create TenantConfig
    config = TenantConfig(
        org_id=org_id,
        rfc=body.rfc,
        razon_social=body.razon_social,
        regimen_fiscal=body.regimen_fiscal,
        locale=body.locale,
        timezone=body.timezone,
        currency=body.currency,
    )
    db.add(config)

    # Auto-create Mexican department structure
    for dept_def in MEXICAN_DEPARTMENTS:
        # Check slug uniqueness within the org before creating
        slug_check = await db.execute(
            select(Department).where(
                Department.slug == dept_def["slug"],
                Department.org_id == org_id,
            )
        )
        if slug_check.scalar_one_or_none() is not None:
            continue  # Department already exists for this org

        dept = Department(
            name=dept_def["name"],
            slug=dept_def["slug"],
            description=dept_def["description"],
            max_agents=dept_def["max_agents"],
            org_id=org_id,
        )
        db.add(dept)

    await db.flush()
    await db.refresh(config)

    logger.info(
        "Provisioned tenant org_id=%s rfc=%s departments=%d",
        org_id,
        body.rfc or "(none)",
        len(MEXICAN_DEPARTMENTS),
    )

    # Audit trail: emit tenant.created event. Load-bearing for LFPDPPP
    # compliance (Mexican PII regulation requires creation timestamp +
    # creator identity). Late import avoids circular risk with the events
    # router. See docs/AUDIT_TRAIL_GAP_ANALYSIS.md gap #1.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="tenant.created",
            event_category="tenant",
            org_id=org_id,
            payload={
                "tenant_config_id": str(config.id),
                "has_rfc": body.rfc is not None,
                "regimen_fiscal": body.regimen_fiscal,
                "locale": body.locale,
                "timezone": body.timezone,
                "currency": body.currency,
                "departments_provisioned": len(MEXICAN_DEPARTMENTS),
                "actor_sub": user.get("sub"),
            },
        )
    except Exception:
        logger.warning("Failed to emit tenant.created audit event", exc_info=True)

    return _to_response(config)


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantResponse:
    """Get the current user's tenant config."""
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == tenant.org_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not configured for this organization",
        )
    return _to_response(config)


@router.patch(
    "/me",
    response_model=TenantResponse,
    dependencies=[Depends(require_non_guest)],
)
async def update_my_tenant(
    body: TenantUpdate,
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantResponse:
    """Update tenant settings (locale, timezone, currency, feature flags, limits).

    Business identity fields (rfc, razon_social, regimen_fiscal) are
    immutable after creation to ensure audit trail integrity.
    """
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == tenant.org_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not configured for this organization",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(config, field_name, value)

    config.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(config)

    # Audit trail: emit tenant.config_updated event. Surfaces tenant
    # self-service knob changes (locale, feature flags, limits) into the
    # office UI activity feed. Payload carries only the keys that changed
    # — never the surrounding identity fields. See gap doc #2.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="tenant.config_updated",
            event_category="tenant",
            org_id=tenant.org_id,
            payload={
                "tenant_config_id": str(config.id),
                "fields_changed": sorted(update_data.keys()),
            },
        )
    except Exception:
        logger.warning(
            "Failed to emit tenant.config_updated audit event", exc_info=True
        )

    return _to_response(config)


@router.get("/me/usage", response_model=TenantUsageResponse)
async def tenant_usage(
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantUsageResponse:
    """Get current tenant usage stats against configured limits.

    Returns agent count, daily task count, and department count alongside
    the configured limits from TenantConfig.
    """
    # Load tenant config (defaults if not provisioned)
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == tenant.org_id))
    config = result.scalar_one_or_none()
    agent_limit = config.max_agents if config else 10
    task_daily_limit = config.max_daily_tasks if config else 100

    agent_count = await _count_agents(db, tenant.org_id)
    tasks_today = await _count_tasks_today(db, tenant.org_id)

    dept_result = await db.execute(
        select(func.count(Department.id)).where(Department.org_id == tenant.org_id)
    )
    department_count = dept_result.scalar_one()

    return TenantUsageResponse(
        org_id=tenant.org_id,
        agent_count=agent_count,
        agent_limit=agent_limit,
        tasks_today=tasks_today,
        task_daily_limit=task_daily_limit,
        department_count=department_count,
    )


# ---------------------------------------------------------------------------
# Enterprise SSO Configuration
# ---------------------------------------------------------------------------


class SSOConfig(BaseModel):
    """Enterprise SSO connection configuration."""

    janua_connection_id: str = Field(..., min_length=1, max_length=255)


@router.patch(
    "/me/sso",
    dependencies=[Depends(require_non_guest)],
)
async def configure_sso(
    body: SSOConfig,
    user: dict[str, Any] = Depends(require_roles(["admin"])),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Configure enterprise SSO connection for this tenant.

    Stores the Janua connection ID so that users in this org are redirected
    to the correct IdP during authentication.  Requires admin role.
    """
    org_id = user.get("org_id", "default")
    config = await _get_tenant_config(db, org_id)
    config.janua_connection_id = body.janua_connection_id
    config.updated_at = datetime.now(UTC)
    await db.flush()

    # Audit trail: emit tenant.sso_configured event. SSO connection IDs
    # are not PII (Janua-side opaque identifiers) so the value is safe to
    # echo in the payload — but actor_sub is included so ops can answer
    # "which admin re-pointed SSO at 03:14?". Aligned with the broader
    # tenant config-change audit surface in gap doc.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="tenant.sso_configured",
            event_category="tenant",
            org_id=org_id,
            payload={
                "tenant_config_id": str(config.id),
                "janua_connection_id": body.janua_connection_id,
                "actor_sub": user.get("sub"),
            },
        )
    except Exception:
        logger.warning(
            "Failed to emit tenant.sso_configured audit event", exc_info=True
        )

    return {"status": "configured", "janua_connection_id": body.janua_connection_id}


# ---------------------------------------------------------------------------
# White-Label Branding
# ---------------------------------------------------------------------------


class BrandingConfig(BaseModel):
    """White-label branding settings for the office UI."""

    brand_name: str | None = Field(default=None, max_length=255)
    brand_logo_url: str | None = Field(default=None, max_length=500)
    brand_primary_color: str | None = Field(default=None, max_length=7)


@router.get("/me/branding")
async def get_branding(
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Get tenant branding config for white-label UI.

    Returns sensible defaults when the tenant has no custom branding.
    """
    org_id = user.get("org_id", "default")
    config = await _get_tenant_config_or_none(db, org_id)
    if not config:
        return {
            "brand_name": "Selva Office",
            "brand_logo_url": None,
            "brand_primary_color": "#4a9e6e",
        }
    return {
        "brand_name": config.brand_name or "Selva Office",
        "brand_logo_url": config.brand_logo_url,
        "brand_primary_color": config.brand_primary_color or "#4a9e6e",
    }


@router.patch(
    "/me/branding",
    dependencies=[Depends(require_non_guest)],
)
async def update_branding(
    body: BrandingConfig,
    user: dict[str, Any] = Depends(require_roles(["admin"])),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Update white-label branding for this tenant.

    Only non-null fields in the request body are applied.  Requires admin role.
    """
    org_id = user.get("org_id", "default")
    config = await _get_tenant_config(db, org_id)

    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(config, field_name, value)

    config.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(config)

    # Audit trail: emit tenant.branding_updated event. Brand name + logo
    # URL + primary color are not PII (these are public-facing UI knobs),
    # so the changed-fields list is safe to include without echoing the
    # values themselves.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="tenant.branding_updated",
            event_category="tenant",
            org_id=org_id,
            payload={
                "tenant_config_id": str(config.id),
                "fields_changed": sorted(update_data.keys()),
                "actor_sub": user.get("sub"),
            },
        )
    except Exception:
        logger.warning(
            "Failed to emit tenant.branding_updated audit event", exc_info=True
        )

    return {
        "brand_name": config.brand_name or "Selva Office",
        "brand_logo_url": config.brand_logo_url,
        "brand_primary_color": config.brand_primary_color or "#4a9e6e",
    }
