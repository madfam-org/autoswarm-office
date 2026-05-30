"""Scheduled action enqueue API — producer for the worker social_post drain (Phase 2.5)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_non_guest
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..schemas.scheduled_actions import (
    CampaignSocialScheduleRequest,
    ScheduledActionBatchCreate,
    ScheduledActionBatchResponse,
    ScheduledActionCreate,
    ScheduledActionHitlUpdate,
    ScheduledActionResponse,
)
from ..services.scheduled_actions import (
    enqueue_campaign_social_schedule,
    enqueue_scheduled_action,
    list_org_scheduled_actions,
    update_scheduled_action_hitl,
)
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduled-actions", tags=["Scheduled Actions"])


@router.post(
    "/",
    response_model=ScheduledActionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_scheduled_action(
    body: ScheduledActionCreate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ScheduledActionResponse:
    """Enqueue a single due-row for the worker social_post executor."""
    row = await enqueue_scheduled_action(db, org_id=tenant.org_id, body=body)
    await db.commit()
    return row


@router.post(
    "/batch",
    response_model=ScheduledActionBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_scheduled_action_batch(
    body: ScheduledActionBatchCreate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ScheduledActionBatchResponse:
    created: list[ScheduledActionResponse] = []
    for action in body.actions:
        created.append(await enqueue_scheduled_action(db, org_id=tenant.org_id, body=action))
    await db.commit()
    return ScheduledActionBatchResponse(created=created, count=len(created))


@router.get(
    "/",
    response_model=list[ScheduledActionResponse],
    dependencies=[Depends(require_non_guest)],
)
async def list_scheduled_actions(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[ScheduledActionResponse]:
    return await list_org_scheduled_actions(
        db, org_id=tenant.org_id, status_filter=status_filter, limit=limit
    )


@router.patch(
    "/{action_id}/hitl",
    response_model=ScheduledActionResponse,
    dependencies=[Depends(require_non_guest)],
)
async def update_hitl_status(
    action_id: uuid.UUID,
    body: ScheduledActionHitlUpdate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> ScheduledActionResponse:
    """Approve or deny a playbook-gated scheduled social post."""
    row = await update_scheduled_action_hitl(
        db,
        org_id=tenant.org_id,
        action_id=action_id,
        decision=body.decision,
    )
    await db.commit()
    logger.info(
        "Scheduled action %s HITL %s by %s org=%s",
        action_id,
        body.decision,
        user.get("sub"),
        tenant.org_id,
    )
    return row


@router.post(
    "/campaign-social",
    response_model=ScheduledActionBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def schedule_campaign_social_posts(
    body: CampaignSocialScheduleRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> ScheduledActionBatchResponse:
    """Schedule a Tulana campaign social cadence (Phase 2.5)."""
    cached = getattr(idem, "cached", None)
    if getattr(idem, "is_replay", False) and cached is not None:
        return ScheduledActionBatchResponse.model_validate(cached)

    created = await enqueue_campaign_social_schedule(db, org_id=tenant.org_id, body=body)
    await db.commit()
    response = ScheduledActionBatchResponse(created=created, count=len(created))
    await idem.save(response.model_dump(mode="json"))
    return response
