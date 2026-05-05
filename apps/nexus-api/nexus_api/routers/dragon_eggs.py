"""Dragon-egg REST API — Phase 1 admin-only social-account hatching.

Phase 1 scope: ``admin@madfam.io`` (or ``superadmin`` role) only. The
authorization dependency is documented below; flipping to multi-tenant
in Phase 2 is a one-line change to the dependency body.

Endpoints
---------

::

    POST   /api/v1/dragon-eggs                          — lay a new egg
    GET    /api/v1/dragon-eggs                          — list eggs (filterable)
    GET    /api/v1/dragon-eggs/{id}                     — egg + actions + progress
    POST   /api/v1/dragon-eggs/{id}/transition          — manual status advance
    POST   /api/v1/dragon-eggs/{id}/actions/{aid}/execute — dispatch action now
    POST   /api/v1/dragon-eggs/{id}/actions/{aid}/skip    — operator override
    DELETE /api/v1/dragon-eggs/{id}                     — release/decommission

The router is intentionally thin — most logic lives in
``nexus_api.services.dragon_egg_service``. The router's job is parse,
authorize, dispatch, format.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..database import get_db
from ..services import dragon_egg_service as egg_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dragon-eggs", tags=["dragon-eggs"])


# ---------------------------------------------------------------------------
# Authorization — Phase 1: admin@madfam.io OR superadmin role
# ---------------------------------------------------------------------------


#: Phase 1 hard-coded founder email. Phase 2 will move this gate from
#: "allowlist email" to "tenant has dragon-egg billing entitlement"
#: — the dependency is the one place to flip.
_PHASE_1_ADMIN_EMAILS: frozenset[str] = frozenset({"admin@madfam.io"})

#: Roles that bypass the email allowlist. The ``admin`` role is the
#: dev-bypass role granted by ``auth.get_current_user`` when
#: ``dev_auth_bypass=true`` (so local tests don't need a real Janua
#: token); ``superadmin`` is the production bypass for ops.
_PHASE_1_BYPASS_ROLES: frozenset[str] = frozenset({"admin", "superadmin"})


async def require_dragon_egg_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI dependency that admits a caller to the dragon-egg surface.

    Phase 1 rule: ``email == 'admin@madfam.io'`` OR a role in
    ``_PHASE_1_BYPASS_ROLES`` (admin/superadmin).

    Phase 2 evolution path: replace this body with a check against
    ``tenant_configs.feature_flags`` (or a dedicated
    ``dragon_egg_eligible`` column). Tenant admins will get access
    once their org has the feature entitlement; the email-allowlist
    becomes a developer-only bypass.

    Returns the current user dict on success; raises 403 otherwise.
    """
    email = (user.get("email") or "").lower().strip()
    roles = set(user.get("roles") or [])

    if email in _PHASE_1_ADMIN_EMAILS:
        return user
    if roles & _PHASE_1_BYPASS_ROLES:
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "dragon-egg API is admin-only in Phase 1. "
            "Phase 2 will open this to tenants with the feature entitlement."
        ),
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class LayEggRequest(BaseModel):
    """Lay a new egg (create a social-account warmup plan)."""

    persona_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Selva persona id; matches the existing "
            "MASTODON_ACCESS_TOKEN_<PERSONA_ID> env-var convention."
        ),
    )
    platform: str = Field(
        ...,
        description="One of 'mastodon' | 'bluesky' | 'reddit' (Phase 1 scope).",
    )
    handle: str = Field(..., min_length=1, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    instance_url: str | None = Field(
        default=None,
        max_length=512,
        description="Required for Mastodon-style federated platforms; ignored otherwise.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class WarmupActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    egg_id: uuid.UUID
    action_type: str
    status: str
    scheduled_for: str
    executed_at: str | None
    result: dict[str, Any] | None
    day_offset: int
    notes: str | None
    content_brief: str | None


class EggResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_id: str
    platform: str
    display_name: str
    handle: str
    instance_url: str | None
    status: str
    progress: float
    laid_at: str
    hatched_at: str | None
    matured_at: str | None
    owner_org_id: str
    created_by: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EggDetailResponse(EggResponse):
    """Egg + its full action timeline."""

    actions: list[WarmupActionResponse] = Field(default_factory=list)


class TransitionResponse(BaseModel):
    egg: EggResponse
    transitioned: bool = Field(
        ..., description="True when status changed; false when already at target."
    )


class SkipActionRequest(BaseModel):
    notes: str | None = Field(
        default=None, description="Operator note explaining the skip."
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _egg_to_response(egg: Any) -> EggResponse:
    """Convert a SocialAccountEgg ORM row to the response schema.

    The metadata column is named ``metadata_`` on the ORM (to dodge
    the SQLAlchemy reserved attribute) but exposed as ``metadata`` on
    the wire — the explicit copy keeps the public API clean.
    """
    return EggResponse(
        id=egg.id,
        persona_id=egg.persona_id,
        platform=egg.platform,
        display_name=egg.display_name,
        handle=egg.handle,
        instance_url=egg.instance_url,
        status=egg.status,
        progress=float(egg.progress),
        laid_at=egg.laid_at.isoformat() if egg.laid_at else "",
        hatched_at=egg.hatched_at.isoformat() if egg.hatched_at else None,
        matured_at=egg.matured_at.isoformat() if egg.matured_at else None,
        owner_org_id=egg.owner_org_id,
        created_by=egg.created_by,
        metadata=dict(egg.metadata_ or {}),
    )


def _action_to_response(action: Any) -> WarmupActionResponse:
    return WarmupActionResponse(
        id=action.id,
        egg_id=action.egg_id,
        action_type=action.action_type,
        status=action.status,
        scheduled_for=action.scheduled_for.isoformat()
        if action.scheduled_for
        else "",
        executed_at=action.executed_at.isoformat() if action.executed_at else None,
        result=action.result,
        day_offset=action.day_offset,
        notes=action.notes,
        content_brief=action.content_brief,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=EggDetailResponse, status_code=status.HTTP_201_CREATED)
async def lay_egg(
    body: LayEggRequest,
    user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailResponse:
    """Lay a new egg + generate its 7-day warmup action plan.

    Returns the full egg detail (egg + actions) so the UI doesn't
    need a follow-up GET to render the timeline.
    """
    try:
        egg = await egg_service.lay_egg(
            db,
            persona_id=body.persona_id,
            platform=body.platform,
            handle=body.handle,
            display_name=body.display_name,
            created_by=user.get("sub") or "",
            instance_url=body.instance_url,
            metadata=body.metadata,
        )
    except egg_service.UnsupportedPlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except egg_service.InvalidPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except egg_service.DuplicateEggError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()

    actions = await egg_service.list_actions_for_egg(db, egg.id)
    response_egg = _egg_to_response(egg)
    return EggDetailResponse(
        **response_egg.model_dump(),
        actions=[_action_to_response(a) for a in actions],
    )


@router.get("", response_model=list[EggResponse])
async def list_eggs(
    egg_status: str | None = Query(
        default=None,
        alias="status",
        description="Filter by egg status (laid/incubating/hatching/hatched/matured).",
    ),
    platform: str | None = Query(default=None),
    owner_org_id: str | None = Query(default=None),
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> list[EggResponse]:
    """List eggs, optionally filtered by status / platform / owner_org_id."""
    eggs = await egg_service.list_eggs(
        db,
        owner_org_id=owner_org_id,
        status=egg_status,
        platform=platform,
    )
    return [_egg_to_response(e) for e in eggs]


@router.get("/{egg_id}", response_model=EggDetailResponse)
async def get_egg(
    egg_id: uuid.UUID,
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> EggDetailResponse:
    """Show a single egg with its full action timeline + computed progress."""
    try:
        egg = await egg_service.get_egg(db, egg_id)
    except egg_service.EggNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Recompute progress on read so the UI sees current state without
    # waiting for the next worker tick.
    egg.progress = await egg_service.progress(db, egg.id)
    await db.flush()

    actions = await egg_service.list_actions_for_egg(db, egg.id)
    response_egg = _egg_to_response(egg)
    return EggDetailResponse(
        **response_egg.model_dump(),
        actions=[_action_to_response(a) for a in actions],
    )


@router.post("/{egg_id}/transition", response_model=TransitionResponse)
async def transition_egg(
    egg_id: uuid.UUID,
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> TransitionResponse:
    """Manually advance the egg's status based on completed actions.

    Useful when the worker is paused or when the operator wants to
    sanity-check the state machine after a manual action update.
    """
    try:
        before = await egg_service.get_egg(db, egg_id)
    except egg_service.EggNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    before_status = before.status
    egg = await egg_service.transition(db, egg_id)
    await db.commit()

    return TransitionResponse(
        egg=_egg_to_response(egg),
        transitioned=egg.status != before_status,
    )


@router.post(
    "/{egg_id}/actions/{action_id}/execute",
    response_model=WarmupActionResponse,
)
async def execute_action(
    egg_id: uuid.UUID,
    action_id: uuid.UUID,
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupActionResponse:
    """Mark an action ready for immediate worker dispatch.

    Phase 1 semantics: this flips ``status`` from
    ``planned``/``pending_human`` → ``in_flight`` and updates
    ``scheduled_for`` to NOW. The worker's drain query picks it up
    on the next tick and dispatches the matching social tool. The
    response is the *pre-dispatch* row state — the operator polls
    ``GET /{egg_id}`` to watch the action complete.

    HITL action types (``profile_setup``, ``follow_curated``,
    ``boost_high_signal``, ``reply_substantive``) are documented as
    Phase 1.5 — calling execute on them flips them to ``in_flight``
    but the worker will currently NOT dispatch them; ops marks them
    completed by hand. Phase 1.5 wires the HITL-approval queue at
    that step.
    """
    try:
        action = await egg_service.get_action(db, egg_id, action_id)
    except egg_service.ActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if action.status in ("completed", "skipped"):
        raise HTTPException(
            status_code=409,
            detail=f"action is already {action.status}; cannot re-execute",
        )

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    action.scheduled_for = now
    action = await egg_service.mark_action_in_flight(db, action, now=now)
    await db.commit()

    return _action_to_response(action)


@router.post(
    "/{egg_id}/actions/{action_id}/skip",
    response_model=WarmupActionResponse,
)
async def skip_action(
    egg_id: uuid.UUID,
    action_id: uuid.UUID,
    body: SkipActionRequest = SkipActionRequest(),
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupActionResponse:
    """Operator override: mark an action ``skipped`` (counts toward progress)."""
    try:
        action = await egg_service.get_action(db, egg_id, action_id)
    except egg_service.ActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if action.status in ("completed", "skipped"):
        raise HTTPException(
            status_code=409,
            detail=f"action is already {action.status}; cannot skip",
        )

    action = await egg_service.skip_action(db, action, notes=body.notes)
    # After a skip, the egg's progress changes — recompute via transition
    # so status + progress stay in sync.
    await egg_service.transition(db, egg_id)
    await db.commit()

    return _action_to_response(action)


@router.delete("/{egg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_egg(
    egg_id: uuid.UUID,
    force_status: str | None = Query(
        default=None,
        description=(
            "When set, force the egg to that status (e.g. 'matured' to "
            "skip warmup for a manually-warmed account). Otherwise, "
            "delete the egg + cascade actions."
        ),
    ),
    _user: CurrentUser = Depends(require_dragon_egg_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Release the egg — either force-promote to a status or delete entirely."""
    try:
        await egg_service.release_egg(db, egg_id, force_status=force_status)
    except egg_service.EggNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except egg_service.DragonEggError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
