"""Campaign-copy generation skill: governed copy variants from Tulana SKU packs.

Claims discipline (hard requirement):

- Generated copy may ground factual statements ONLY in claims marked
  ``campaign_safe=true`` in the input pack's claims register rows.
- If the pack carries no campaign-safe claims the service REFUSES with a
  structured 422 error (``no_campaign_safe_claims``) instead of inventing
  product capabilities.
- Every returned variant lists the claim keys it used (``claim_keys_used``)
  for auditability; variants citing non-permitted keys are dropped.
- ``do_not_claim`` phrases are scrubbed post-generation via
  :func:`guard_campaign_draft` and reported per variant.

LLM access goes through the shared ``ModelRouter`` singleton (same routing,
fallback, and cost policies as the inference proxy). No new vendors.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from ..schemas.campaign_copy import (
    CampaignCopyRequest,
    CampaignCopyResponse,
    CampaignCopyVariant,
)
from ..schemas.tulana_campaign import TulanaCampaignClaim, TulanaSkuCampaignPack
from .tulana_campaign import guard_campaign_draft, validate_pack

logger = logging.getLogger(__name__)

_MAX_LLM_ATTEMPTS = 2
_COPY_TASK_TYPE = "research"  # same routed task type as the campaign graph drafts

_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "es-MX": (
        "Write all copy in Mexican Spanish (es-MX). Use natural, professional "
        "es-MX phrasing — no Spain-Spanish constructions, no machine-translated "
        "tone. Currency references, if any appear in permitted claims, stay in MXN."
    ),
    "en": "Write all copy in clear, professional English.",
}


def filter_campaign_claims(
    pack: TulanaSkuCampaignPack,
) -> tuple[list[TulanaCampaignClaim], list[TulanaCampaignClaim]]:
    """Split pack claims into (campaign-safe, excluded).

    A claim is campaign-safe only when ``campaign_safe`` is true AND it has no
    blocking reasons — fail closed on any inconsistency between the two.
    """
    safe: list[TulanaCampaignClaim] = []
    excluded: list[TulanaCampaignClaim] = []
    for claim in pack.claims:
        if claim.campaign_safe and not claim.blocking_reasons:
            safe.append(claim)
        else:
            excluded.append(claim)
    return safe, excluded


def build_copy_messages(
    *,
    pack: TulanaSkuCampaignPack,
    safe_claims: list[TulanaCampaignClaim],
    audience: str,
    channel: str,
    language: str,
    variant_count: int,
    tone: str | None,
) -> tuple[str, str]:
    """Return (system_prompt, user_message) for the copy generation call."""
    claim_lines = []
    for claim in safe_claims:
        evidence = f" | evidence: {claim.claim_evidence_url}" if claim.claim_evidence_url else ""
        notes = f" | notes: {claim.notes}" if claim.notes else ""
        claim_lines.append(
            f"- key={claim.feature_key} [{claim.claim_class}] "
            f"{claim.feature_label or claim.feature_key}{evidence}{notes}"
        )
    do_not_claim_lines = [f"- {phrase}" for phrase in pack.do_not_claim]

    system_prompt = (
        "You are Selva's campaign copywriter for the MADFAM ecosystem. "
        "You write conversion-focused, legally-safe campaign copy.\n\n"
        "NON-NEGOTIABLE RULES:\n"
        "1. Every factual statement about the product MUST be grounded in the "
        "PERMITTED CLAIMS list. Never invent capabilities, pricing, "
        "certifications, integrations, or availability.\n"
        "2. Never use any phrase from the DO-NOT-CLAIM list.\n"
        "3. For each variant, report the claim keys you used in "
        '"claim_keys_used" (exact keys from the permitted list, at least one '
        "per variant).\n"
        f"4. {_LANGUAGE_INSTRUCTIONS[language]}\n\n"
        "Output STRICT JSON only, no markdown fences, with this shape:\n"
        '{"variants": [{"subject": str, "preheader": str, "body": str, '
        '"cta": str, "claim_keys_used": [str, ...]}]}\n'
        f"Return exactly {variant_count} variant(s)."
    )

    tone_line = f"Tone: {tone}\n" if tone else ""
    value_prop = pack.value_prop.strip()
    value_prop_block = (
        f"Positioning context (tone/angle only — NOT a source of factual claims): {value_prop}\n"
        if value_prop
        else ""
    )
    user_message = (
        f"SKU: {pack.sku_key}\n"
        f"Audience: {audience}\n"
        f"Channel: {channel}\n"
        f"{tone_line}"
        f"{value_prop_block}\n"
        "PERMITTED CLAIMS (the ONLY allowed factual grounding):\n"
        + "\n".join(claim_lines)
        + "\n\nDO-NOT-CLAIM (never state or imply any of these):\n"
        + ("\n".join(do_not_claim_lines) if do_not_claim_lines else "- (none)")
        + f"\n\nWrite {variant_count} {channel} copy variant(s) "
        "(subject + preheader + body + CTA) for this audience."
    )
    return system_prompt, user_message


def parse_copy_variants(content: str) -> list[dict[str, Any]]:
    """Parse the LLM JSON payload; raise ValueError on any contract breach."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a JSON object")
    variants = parsed.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError('LLM output must contain a non-empty "variants" array')
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            raise ValueError(f"variant {index} is not a JSON object")
    return variants


def _get_router() -> Any:
    """Return the shared ModelRouter singleton (same instance as the proxy)."""
    from ..routers.inference_proxy import _get_router as _proxy_router

    return _proxy_router()


async def _complete_copy(
    *,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> Any:
    from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

    model_router = _get_router()
    request = InferenceRequest(
        messages=[{"role": "user", "content": user_message}],
        policy=RoutingPolicy(
            sensitivity=Sensitivity.INTERNAL,
            max_tokens=max_tokens,
            temperature=0.4,
            task_type=_COPY_TASK_TYPE,
        ),
        system_prompt=system_prompt,
        response_format={"type": "json_object"},
    )
    return await model_router.complete(request)


def _enforce_variant(
    *,
    index: int,
    raw: dict[str, Any],
    safe_keys: set[str],
    do_not_claim: list[str],
    language: str,
) -> CampaignCopyVariant | str:
    """Apply claims discipline to one generated variant.

    Returns the governed variant, or a rejection-reason string when the
    variant breaks the claims contract.
    """
    subject = str(raw.get("subject") or "").strip()
    body = str(raw.get("body") or "").strip()
    cta = str(raw.get("cta") or "").strip()
    preheader_raw = str(raw.get("preheader") or "").strip()
    if not subject or not body or not cta:
        return f"variant {index}: missing subject/body/cta"

    keys_raw = raw.get("claim_keys_used")
    if not isinstance(keys_raw, list):
        keys_raw = []
    claim_keys = [str(k).strip() for k in keys_raw if str(k).strip()]
    claim_keys = list(dict.fromkeys(claim_keys))  # dedupe, keep order
    if not claim_keys:
        return f"variant {index}: no claim_keys_used reported (ungrounded copy)"
    unknown = [k for k in claim_keys if k not in safe_keys]
    if unknown:
        return f"variant {index}: cites non-permitted claim keys {unknown}"

    violations: list[str] = []
    scrubbed: dict[str, str] = {}
    for field_name, text in (
        ("subject", subject),
        ("preheader", preheader_raw),
        ("body", body),
        ("cta", cta),
    ):
        clean, found = guard_campaign_draft(text, do_not_claim)
        scrubbed[field_name] = clean
        violations.extend(found)
    if not scrubbed["subject"] or not scrubbed["body"] or not scrubbed["cta"]:
        return f"variant {index}: emptied by do_not_claim scrub"

    return CampaignCopyVariant(
        variant_id=str(uuid.uuid4()),
        language=language,  # type: ignore[arg-type]
        subject=scrubbed["subject"][:500],
        preheader=scrubbed["preheader"][:500] or None,
        body=scrubbed["body"][:8000],
        cta=scrubbed["cta"][:500],
        claim_keys_used=claim_keys,
        guardrail_violations=list(dict.fromkeys(violations)),
    )


async def generate_campaign_copy(
    body: CampaignCopyRequest,
    *,
    org_id: str,
) -> CampaignCopyResponse:
    """Generate governed campaign copy variants for one Tulana SKU pack."""
    pack = body.tulana_pack

    validation = validate_pack(pack, allow_blocked=False)
    if not validation.accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "invalid_tulana_pack",
                "message": "Invalid Tulana pack",
                "errors": validation.errors,
            },
        )

    safe_claims, excluded_claims = filter_campaign_claims(pack)
    excluded_keys = [c.feature_key for c in excluded_claims]
    if not safe_claims:
        # Refusal path — never generate copy without campaign-permitted claims.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "no_campaign_safe_claims",
                "message": (
                    "Pack has no campaign-permitted claims (campaign_safe=true "
                    "with empty blocking_reasons); refusing to generate copy "
                    "rather than invent product capabilities."
                ),
                "sku_key": pack.sku_key,
                "excluded_claim_keys": excluded_keys,
            },
        )

    safe_keys = {c.feature_key for c in safe_claims}
    system_prompt, user_message = build_copy_messages(
        pack=pack,
        safe_claims=safe_claims,
        audience=body.audience,
        channel=body.channel,
        language=body.language,
        variant_count=body.variant_count,
        tone=body.tone,
    )

    raw_variants: list[dict[str, Any]] | None = None
    provider = ""
    model = ""
    attempt_message = user_message
    last_error = ""
    for attempt in range(_MAX_LLM_ATTEMPTS):
        try:
            response = await _complete_copy(
                system_prompt=system_prompt,
                user_message=attempt_message,
                max_tokens=2048,
            )
        except RuntimeError as exc:
            logger.error("Campaign copy inference failed org=%s: %s", org_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error_code": "inference_unavailable",
                    "message": "Inference service unavailable",
                },
            ) from exc
        provider = response.provider
        model = response.model
        try:
            raw_variants = parse_copy_variants(response.content)
            break
        except ValueError as exc:
            last_error = str(exc)
            logger.warning(
                "Campaign copy JSON parse failed (attempt %d/%d) org=%s: %s",
                attempt + 1,
                _MAX_LLM_ATTEMPTS,
                org_id,
                exc,
            )
            attempt_message = (
                f"{user_message}\n\nYour previous output was rejected: {exc}. "
                "Return STRICT JSON matching the required shape only."
            )

    if raw_variants is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": "copy_generation_failed",
                "message": f"LLM did not return parseable copy variants: {last_error}",
            },
        )

    variants: list[CampaignCopyVariant] = []
    dropped: list[str] = []
    for index, raw in enumerate(raw_variants[: body.variant_count]):
        result = _enforce_variant(
            index=index,
            raw=raw,
            safe_keys=safe_keys,
            do_not_claim=pack.do_not_claim,
            language=body.language,
        )
        if isinstance(result, str):
            dropped.append(result)
        else:
            variants.append(result)

    if not variants:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": "copy_generation_failed",
                "message": "All generated variants violated claims discipline",
                "dropped_variants": dropped,
            },
        )

    return CampaignCopyResponse(
        sku_key=pack.sku_key,
        channel=body.channel,
        language=body.language,
        audience=body.audience,
        variants=variants,
        campaign_safe_claim_keys=sorted(safe_keys),
        excluded_claim_keys=excluded_keys,
        dropped_variants=dropped,
        provider=provider,
        model=model,
        generated_at=datetime.now(UTC),
    )
