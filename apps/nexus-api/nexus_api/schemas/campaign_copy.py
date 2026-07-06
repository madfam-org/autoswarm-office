"""Pydantic contract for the campaign-copy generation skill.

Takes a Tulana SKU campaign pack (with its campaign claims register rows),
an audience descriptor, and a channel, and returns governed copy variants
grounded ONLY in campaign-safe claims. See ``services/campaign_copy.py``
for the claims-discipline enforcement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .tulana_campaign import TulanaSkuCampaignPack

CopyChannel = Literal["email"]
CopyLanguage = Literal["es-MX", "en"]


class CampaignCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tulana_pack: TulanaSkuCampaignPack
    audience: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Audience descriptor (segment, persona, or list description).",
    )
    channel: CopyChannel = Field(
        default="email",
        description="Delivery channel. Email first; SMS/WhatsApp are follow-ups.",
    )
    language: CopyLanguage = Field(
        default="es-MX",
        description="Output language. es-MX is the MADFAM primary; en is optional.",
    )
    variant_count: int = Field(default=3, ge=1, le=5)
    tone: str | None = Field(
        default=None,
        max_length=200,
        description="Optional tone hint (e.g. 'directo y profesional').",
    )


class CampaignCopyVariant(BaseModel):
    variant_id: str
    language: CopyLanguage
    subject: str = Field(..., max_length=500)
    preheader: str | None = Field(default=None, max_length=500)
    body: str = Field(..., max_length=8000)
    cta: str = Field(..., max_length=500)
    claim_keys_used: list[str] = Field(
        default_factory=list,
        description="Campaign-safe claim feature_keys grounding this variant (audit trail).",
    )
    guardrail_violations: list[str] = Field(
        default_factory=list,
        description="do_not_claim phrases that were scrubbed from this variant.",
    )


class CampaignCopyResponse(BaseModel):
    sku_key: str
    channel: CopyChannel
    language: CopyLanguage
    audience: str
    variants: list[CampaignCopyVariant]
    campaign_safe_claim_keys: list[str] = Field(
        default_factory=list,
        description="Claim keys the generator was permitted to use.",
    )
    excluded_claim_keys: list[str] = Field(
        default_factory=list,
        description="Claim keys present in the pack but NOT campaign-safe (never used).",
    )
    dropped_variants: list[str] = Field(
        default_factory=list,
        description="Reasons for generated variants rejected by claims enforcement.",
    )
    provider: str
    model: str
    generated_at: datetime
