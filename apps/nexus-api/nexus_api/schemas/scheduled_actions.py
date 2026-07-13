"""Schemas for scheduled_actions enqueue API (Phase 2.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ``x`` (Twitter) and ``linkedin`` are registered channels but their post
# executors SHIP DARK — disabled unless the operator arms
# SELVA_X_POST_ENABLED / SELVA_LINKEDIN_POST_ENABLED and provisions
# credentials. Scheduling a row for them is allowed; the executor fails the
# row closed (clear error, no fake success) until the channel is enabled.
SocialPlatform = Literal["mastodon", "bluesky", "reddit", "x", "linkedin", "email"]
HitlDecision = Literal["approved", "denied", "pending"]


class ScheduledActionCreate(BaseModel):
    action_type: str = Field(default="social_post", max_length=64)
    scheduled_for: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    playbook_id: str | None = Field(default=None, max_length=255)
    hitl_status: HitlDecision | None = None
    persona_id: str | None = Field(default=None, max_length=64)
    max_retries: int = Field(default=3, ge=0, le=10)


class ScheduledActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_type: str
    scheduled_for: datetime
    status: str
    payload: dict[str, Any]
    playbook_id: str | None
    hitl_status: str | None
    persona_id: str | None
    org_id: str
    retry_count: int
    max_retries: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ScheduledActionBatchCreate(BaseModel):
    actions: list[ScheduledActionCreate] = Field(..., min_length=1, max_length=50)


class ScheduledActionBatchResponse(BaseModel):
    created: list[ScheduledActionResponse]
    count: int


class ScheduledActionHitlUpdate(BaseModel):
    decision: Literal["approved", "denied"]


class CampaignSocialPostItem(BaseModel):
    scheduled_for: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class CampaignSocialScheduleRequest(BaseModel):
    sku_key: str = Field(..., min_length=1, max_length=200)
    platform: SocialPlatform
    posts: list[CampaignSocialPostItem] = Field(..., min_length=1, max_length=30)
    playbook_id: str | None = Field(default=None, max_length=255)
    persona_id: str | None = Field(default=None, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=200)
    require_hitl: bool = True
