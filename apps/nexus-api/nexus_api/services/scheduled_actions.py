"""Enqueue and validate scheduled_actions rows (Phase 2.5 producer)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ScheduledActionRow
from ..schemas.scheduled_actions import (
    CampaignSocialScheduleRequest,
    ScheduledActionCreate,
    ScheduledActionResponse,
)

logger = logging.getLogger(__name__)

_SUPPORTED_PLATFORMS = frozenset({"mastodon", "bluesky", "reddit", "email"})
_DEFAULT_PLAYBOOK_BY_PLATFORM: dict[str, str] = {
    "reddit": "reddit_promo_v1",
    "mastodon": "mastodon_promo_v1",
    "bluesky": "bluesky_promo_v1",
}


def _validate_social_payload(platform: str, payload: dict[str, Any]) -> None:
    platform = platform.strip().lower()
    if platform not in _SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported platform '{platform}'",
        )
    if platform == "mastodon" and not (payload.get("instance") and payload.get("status")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mastodon posts require payload.instance and payload.status",
        )
    if platform == "bluesky" and not (payload.get("text") or payload.get("status")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bluesky posts require payload.text or payload.status",
        )
    if platform == "reddit" and not all(
        payload.get(k) for k in ("subreddit", "title", "body")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reddit posts require payload.subreddit, title, and body",
        )
    if platform == "email":
        recipient = payload.get("recipient") or payload.get("to")
        body = payload.get("body") or payload.get("html")
        if not recipient or not payload.get("subject") or not body:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="email posts require recipient/to, subject, and body/html",
            )


def _row_to_response(row: ScheduledActionRow) -> ScheduledActionResponse:
    return ScheduledActionResponse(
        id=str(row.id),
        action_type=row.action_type,
        scheduled_for=row.scheduled_for,
        status=row.status,
        payload=row.payload,
        playbook_id=row.playbook_id,
        hitl_status=row.hitl_status,
        persona_id=row.persona_id,
        org_id=row.org_id,
        retry_count=row.retry_count,
        max_retries=row.max_retries,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalize_scheduled_for(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


async def enqueue_scheduled_action(
    db: AsyncSession,
    *,
    org_id: str,
    body: ScheduledActionCreate,
) -> ScheduledActionResponse:
    if body.action_type != "social_post":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only action_type=social_post is supported today",
        )

    payload = dict(body.payload)
    platform = str(payload.get("platform") or "").strip().lower()
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="payload.platform is required for social_post actions",
        )
    _validate_social_payload(platform, payload)

    playbook_id = body.playbook_id
    hitl_status = body.hitl_status
    if playbook_id and hitl_status is None:
        hitl_status = "pending"

    now = datetime.now(UTC)
    row = ScheduledActionRow(
        id=uuid.uuid4(),
        action_type=body.action_type,
        scheduled_for=_normalize_scheduled_for(body.scheduled_for),
        status="pending",
        payload=payload,
        playbook_id=playbook_id,
        hitl_status=hitl_status,
        persona_id=body.persona_id,
        org_id=org_id,
        max_retries=body.max_retries,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "Enqueued scheduled action id=%s org=%s platform=%s for=%s",
        row.id,
        org_id,
        platform,
        row.scheduled_for.isoformat(),
    )
    return _row_to_response(row)


async def enqueue_campaign_social_schedule(
    db: AsyncSession,
    *,
    org_id: str,
    body: CampaignSocialScheduleRequest,
) -> list[ScheduledActionResponse]:
    playbook_id = body.playbook_id
    if body.require_hitl and playbook_id is None:
        playbook_id = _DEFAULT_PLAYBOOK_BY_PLATFORM.get(body.platform)

    hitl_status: str | None = "pending" if body.require_hitl and playbook_id else None
    created: list[ScheduledActionResponse] = []

    for item in body.posts:
        payload = {
            **item.payload,
            "platform": body.platform,
            "sku_key": body.sku_key,
        }
        if body.campaign_id:
            payload["campaign_id"] = body.campaign_id

        response = await enqueue_scheduled_action(
            db,
            org_id=org_id,
            body=ScheduledActionCreate(
                action_type="social_post",
                scheduled_for=item.scheduled_for,
                payload=payload,
                playbook_id=playbook_id,
                hitl_status=hitl_status,  # type: ignore[arg-type]
                persona_id=body.persona_id,
            ),
        )
        created.append(response)

    return created


async def list_org_scheduled_actions(
    db: AsyncSession,
    *,
    org_id: str,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[ScheduledActionResponse]:
    query = (
        select(ScheduledActionRow)
        .where(ScheduledActionRow.org_id == org_id)
        .order_by(ScheduledActionRow.scheduled_for.desc())
        .limit(min(limit, 200))
    )
    if status_filter:
        query = query.where(ScheduledActionRow.status == status_filter)
    result = await db.execute(query)
    return [_row_to_response(row) for row in result.scalars().all()]


async def update_scheduled_action_hitl(
    db: AsyncSession,
    *,
    org_id: str,
    action_id: uuid.UUID,
    decision: str,
) -> ScheduledActionResponse:
    result = await db.execute(
        select(ScheduledActionRow).where(
            ScheduledActionRow.id == action_id,
            ScheduledActionRow.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled action not found",
        )
    if row.status not in {"pending", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update HITL on status={row.status}",
        )

    row.hitl_status = decision
    row.updated_at = datetime.now(UTC)
    if decision == "denied":
        row.status = "failed"
        row.last_error = "HITL denied"
        row.completed_at = datetime.now(UTC)
    await db.flush()
    return _row_to_response(row)
