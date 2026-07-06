"""Pydantic models for Tulana SKU campaign pack import (Phase 2 contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GaReadiness = Literal["near_ready", "waived", "blocked", "ready", "discovery"]
PolicyState = Literal[
    "approved",
    "waived_by_operator",
    "blocked",
    "pending_review",
]


class TulanaProofPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=500)
    source: str = Field(..., min_length=1, max_length=500)
    url: str | None = Field(default=None, max_length=2048)


class TulanaCampaignClaim(BaseModel):
    """Row from Tulana's campaign claims register (feature-matrix export).

    Mirrors the wire shape emitted by Tulana's
    ``tulana_campaign_claims_register --json`` command
    (``madfam_catalog.feature_matrix.build_campaign_claims_register``).
    ``extra="ignore"`` lets Tulana pass full register rows straight through;
    ``campaign_safe`` defaults to ``False`` so unmarked claims fail closed.
    """

    model_config = ConfigDict(extra="ignore")

    feature_key: str = Field(..., min_length=1, max_length=200)
    feature_label: str = Field(default="", max_length=500)
    claim_class: str = Field(default="feature", max_length=100)
    campaign_safe: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
    claim_evidence_url: str | None = Field(default=None, max_length=2048)
    notes: str = Field(default="", max_length=4000)


class TulanaSkuCampaignPack(BaseModel):
    """Minimum Tulana export shape consumed by Selva campaign orchestration."""

    model_config = ConfigDict(extra="ignore")

    generated_at: datetime | None = None
    sku_key: str = Field(..., min_length=1, max_length=200)
    platform: str = Field(default="", max_length=200)
    audience: str = Field(..., min_length=1, max_length=500)
    ga_readiness: GaReadiness
    rank: int | None = Field(default=None, ge=1)
    readiness_reasons: list[str] = Field(default_factory=list)
    value_prop: str = Field(default="", max_length=4000)
    proof_points: list[TulanaProofPoint] = Field(default_factory=list)
    claims: list[TulanaCampaignClaim] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "Campaign claims register rows for this SKU. Only rows with "
            "campaign_safe=true may ground generated campaign copy."
        ),
    )
    do_not_claim: list[str] = Field(default_factory=list)
    policy_state: PolicyState | str = Field(default="pending_review")
    last_verified_at: datetime

    @field_validator("do_not_claim")
    @classmethod
    def _strip_empty_claims(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        return cleaned


class TulanaImportRequest(BaseModel):
    packs: list[TulanaSkuCampaignPack] = Field(..., min_length=1, max_length=100)
    allow_blocked: bool = Field(
        default=False,
        description="When true, blocked SKUs are accepted for waitlist/discovery lanes.",
    )
    dispatch_tasks: bool = Field(
        default=False,
        description="When true, enqueue one intelligence graph task per accepted SKU.",
    )


class TulanaPackValidation(BaseModel):
    sku_key: str
    accepted: bool
    errors: list[str] = Field(default_factory=list)
    rank_score: float | None = None


class TulanaImportResponse(BaseModel):
    accepted: list[TulanaSkuCampaignPack]
    rejected: list[TulanaPackValidation]
    ranked_sku_keys: list[str]
    dispatched_task_ids: list[str] = Field(default_factory=list)


class CrmCampaignHandoffRequest(BaseModel):
    sku_key: str = Field(..., min_length=1, max_length=200)
    audience: str = Field(..., min_length=1, max_length=500)
    draft_variants: list[str] = Field(..., min_length=1, max_length=10)
    tulana_pack: TulanaSkuCampaignPack
    campaign_name: str | None = Field(default=None, max_length=200)
    phynd_list_id: str | None = Field(default=None, max_length=200)


class CrmCampaignHandoffResponse(BaseModel):
    handoff_id: str
    task_id: str
    status: str = "queued"
    message: str


class TulanaBuyerSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(..., min_length=1, max_length=200)
    value: str | int | float
    source: str = Field(default="selva_campaign", max_length=200)


class TulanaFeedbackRequest(BaseModel):
    sku_key: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=4000)
    outcomes: list[TulanaBuyerSignal] = Field(..., min_length=1, max_length=50)
    campaign_name: str | None = Field(default=None, max_length=200)
    handoff_id: str | None = Field(default=None, max_length=200)
    task_id: str | None = Field(default=None, max_length=200)
    evidence_urls: list[str] = Field(default_factory=list, max_length=20)


class TulanaFeedbackResponse(BaseModel):
    status: str
    tulana_event_id: str | None = None
    message: str
