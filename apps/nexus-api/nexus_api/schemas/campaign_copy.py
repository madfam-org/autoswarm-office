"""Pydantic contract for the campaign-copy generation skill.

Takes a Tulana SKU campaign pack (with its campaign claims register rows),
an audience descriptor, and a channel, and returns governed copy variants
grounded ONLY in campaign-safe claims. See ``services/campaign_copy.py``
for the claims-discipline enforcement.

Channels:

- ``email`` — variants carry subject + preheader + body + cta.
- ``social_post`` — short posts for the schedule-social pipeline
  (Mastodon / Bluesky / Reddit via ``social_post_executor``). Variants
  carry body + cta only (``subject``/``preheader`` are ``None``) and the
  body must fit ``max_chars`` (default 300 = Bluesky; Mastodon allows 500).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .tulana_campaign import TulanaSkuCampaignPack

CopyChannel = Literal["email", "social_post"]
CopyLanguage = Literal["es-MX", "en"]

# Per-target post-body ceilings the ``max_chars`` policy is derived from.
# One social variant may be scheduled to either platform, so the request
# default (300) is the strictest common target; callers doing
# Mastodon-only batches may raise it to 500.
SOCIAL_MAX_CHARS_BLUESKY = 300
SOCIAL_MAX_CHARS_MASTODON = 500
SOCIAL_MAX_CHARS_FLOOR = 120


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
        description=(
            "Delivery channel. ``email`` for campaign emails; ``social_post`` "
            "for short posts destined for schedule-social (Mastodon, Bluesky, "
            "Reddit). SMS/WhatsApp are follow-ups."
        ),
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
    max_chars: int = Field(
        default=SOCIAL_MAX_CHARS_BLUESKY,
        ge=SOCIAL_MAX_CHARS_FLOOR,
        le=SOCIAL_MAX_CHARS_MASTODON,
        description=(
            "social_post only: hard ceiling for each post body. Default 300 "
            "(Bluesky, the strictest supported target); Mastodon-only batches "
            "may raise to 500. Ignored for the email channel."
        ),
    )


class CampaignCopyVariant(BaseModel):
    variant_id: str
    language: CopyLanguage
    subject: str | None = Field(
        default=None,
        max_length=500,
        description="Email subject line. Always set for email; None for social_post.",
    )
    preheader: str | None = Field(
        default=None,
        max_length=500,
        description="Email preheader. Email-only; None for social_post.",
    )
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
        description=(
            "Reasons for generated variants rejected by claims enforcement "
            "(non-permitted claim keys, scrub-emptied copy, or over-length "
            "social bodies)."
        ),
    )
    provider: str
    model: str
    generated_at: datetime
