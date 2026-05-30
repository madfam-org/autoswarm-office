"""Validation and ranking for Tulana SKU campaign packs."""

from __future__ import annotations

from ..schemas.tulana_campaign import (
    TulanaImportRequest,
    TulanaImportResponse,
    TulanaPackValidation,
    TulanaSkuCampaignPack,
)

_READINESS_SCORE: dict[str, float] = {
    "ready": 100.0,
    "near_ready": 90.0,
    "waived": 70.0,
    "discovery": 50.0,
    "blocked": 10.0,
}


def validate_pack(
    pack: TulanaSkuCampaignPack,
    *,
    allow_blocked: bool,
) -> TulanaPackValidation:
    errors: list[str] = []

    if not pack.sku_key.strip():
        errors.append("sku_key is required")

    if not pack.audience.strip():
        errors.append("audience is required")

    if not pack.ga_readiness:
        errors.append("ga_readiness is required")

    has_proof = len(pack.proof_points) > 0
    waived = str(pack.policy_state) == "waived_by_operator"
    if not has_proof and not waived:
        errors.append("at least one proof_point or policy_state=waived_by_operator is required")

    if not pack.do_not_claim:
        errors.append("do_not_claim guardrails are required (non-empty list)")

    if pack.last_verified_at is None:
        errors.append("last_verified_at is required")

    if pack.ga_readiness == "blocked" and not allow_blocked:
        errors.append("blocked SKU rejected (set allow_blocked=true for waitlist lanes)")

    rank_score: float | None = None
    if not errors:
        base = _READINESS_SCORE.get(pack.ga_readiness, 0.0)
        tulana_rank = float(pack.rank) if pack.rank is not None else 50.0
        # Higher Tulana rank (1 = best) boosts score; invert so rank 1 → +49.
        rank_boost = max(0.0, 50.0 - min(tulana_rank, 50.0))
        rank_score = base + rank_boost

    return TulanaPackValidation(
        sku_key=pack.sku_key,
        accepted=len(errors) == 0,
        errors=errors,
        rank_score=rank_score,
    )


def rank_accepted_packs(packs: list[TulanaSkuCampaignPack]) -> list[TulanaSkuCampaignPack]:
    """Rank accepted packs: closest-to-GA first, then Tulana rank, then sku_key."""

    def sort_key(p: TulanaSkuCampaignPack) -> tuple[float, int, str]:
        readiness = _READINESS_SCORE.get(p.ga_readiness, 0.0)
        rank = p.rank if p.rank is not None else 9999
        return (-readiness, rank, p.sku_key)

    return sorted(packs, key=sort_key)


def import_tulana_packs(request: TulanaImportRequest) -> TulanaImportResponse:
    validations: list[TulanaPackValidation] = []
    accepted: list[TulanaSkuCampaignPack] = []

    for pack in request.packs:
        result = validate_pack(pack, allow_blocked=request.allow_blocked)
        validations.append(result)
        if result.accepted:
            accepted.append(pack)

    ranked = rank_accepted_packs(accepted)
    rejected = [v for v in validations if not v.accepted]

    return TulanaImportResponse(
        accepted=ranked,
        rejected=rejected,
        ranked_sku_keys=[p.sku_key for p in ranked],
        dispatched_task_ids=[],
    )
