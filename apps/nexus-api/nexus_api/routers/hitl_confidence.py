"""HITL confidence dashboard + internal recording (Sprint 1 — observe only).

Surface:
    GET  /api/v1/hitl/confidence      — admin dashboard: bucket list with
                                        counts, derived confidence, tier.
    GET  /api/v1/hitl/decisions       — admin dashboard: recent decisions
                                        with filters (agent_id, category,
                                        outcome, since).
    POST /api/v1/hitl/decisions       — internal: workers / approval
                                        router post decisions here.
                                        Bearer worker_api_token only.

No tier changes, no enforcement. The data model supports promotion
(see `HitlConfidenceTier`), but Sprint 1 writes `ASK` for every bucket
— the point is to prove the pipeline is clean before we trust it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_permissions import (
    INITIAL_BUCKET_STATE,
    BucketState,
    ConfidenceTier,
    DecisionOutcome,
    apply_decision,
    compute_bucket_key,
    compute_signature,
    promote_if_eligible,
)

from ..auth import CurrentUser, require_roles
from ..config import get_settings
from ..database import get_db
from ..models import HitlConfidence, HitlConfidenceTier, HitlDecision, HitlOutcome

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HITL Confidence"])


# -- Auth dependency for the internal POST endpoint ---------------------------


def _require_worker_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Bearer check against ``worker_api_token``.

    Decisions are produced by the approvals router (running in nexus-api
    itself) and by workers. Both share ``worker_api_token`` today; a
    dedicated token rotation is a Sprint 2+ concern.
    """
    settings = get_settings()
    expected = settings.worker_api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="worker_api_token not configured",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer token",
        )
    import secrets

    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker token",
        )


# -- Schemas ------------------------------------------------------------------


class RecordDecisionRequest(BaseModel):
    """Payload a caller POSTs when a HITL gate resolves."""

    agent_id: str | None = Field(default=None, max_length=255)
    action_category: str = Field(..., min_length=1, max_length=50)
    org_id: str = Field(..., min_length=1, max_length=255)
    context: dict[str, Any] = Field(default_factory=dict)
    outcome: DecisionOutcome
    approver_id: str | None = Field(default=None, max_length=255)
    latency_ms: int | None = Field(default=None, ge=0)
    payload_hash: str | None = Field(default=None, max_length=64)
    diff_hash: str | None = Field(default=None, max_length=64)
    parent_decision_id: str | None = Field(default=None, max_length=36)
    notes: str | None = Field(default=None, max_length=500)


class RecordDecisionResponse(BaseModel):
    decision_id: str
    bucket_key: str
    context_signature: str
    confidence: float
    n_observed: int
    tier: HitlConfidenceTier


class BucketView(BaseModel):
    bucket_key: str
    agent_id: str | None
    action_category: str
    org_id: str
    context_signature: str
    n_observed: int
    n_approved_clean: int
    n_approved_modified: int
    n_rejected: int
    n_timeout: int
    n_reverted: int
    confidence: float
    tier: HitlConfidenceTier
    last_decision_at: str | None


class ConfidenceDashboard(BaseModel):
    total_buckets: int
    total_decisions: int
    buckets: list[BucketView]


class DecisionView(BaseModel):
    id: str
    decided_at: str
    agent_id: str | None
    action_category: str
    org_id: str
    bucket_key: str
    outcome: HitlOutcome
    approver_id: str | None
    latency_ms: int | None
    notes: str | None


class DecisionList(BaseModel):
    total: int
    decisions: list[DecisionView]


# -- Internal helpers ---------------------------------------------------------


async def _load_bucket_state(
    db: AsyncSession, bucket_key: str
) -> tuple[HitlConfidence | None, BucketState]:
    """Return (row, state). Row is None when the bucket is new."""
    result = await db.execute(select(HitlConfidence).where(HitlConfidence.bucket_key == bucket_key))
    row = result.scalar_one_or_none()
    if row is None:
        return None, INITIAL_BUCKET_STATE
    return row, BucketState(
        n_observed=row.n_observed,
        n_approved_clean=row.n_approved_clean,
        n_approved_modified=row.n_approved_modified,
        n_rejected=row.n_rejected,
        n_timeout=row.n_timeout,
        n_reverted=row.n_reverted,
        beta_alpha=row.beta_alpha,
        beta_beta=row.beta_beta,
        tier=ConfidenceTier(row.tier.value),
    )


async def _persist_decision_and_bucket(
    db: AsyncSession,
    *,
    agent_id: str | None,
    action_category: str,
    org_id: str,
    context_signature: str,
    bucket_key: str,
    next_state: BucketState,
    outcome: DecisionOutcome,
    approver_id: str | None,
    latency_ms: int | None,
    payload_hash: str | None,
    diff_hash: str | None,
    parent_decision_id: str | None,
    notes: str | None,
) -> HitlDecision:
    """Insert the decision row and upsert the rolling bucket."""
    decision = HitlDecision(
        bucket_key=bucket_key,
        agent_id=agent_id,
        action_category=action_category,
        org_id=org_id,
        context_signature=context_signature,
        outcome=HitlOutcome(outcome.value),
        approver_id=approver_id,
        latency_ms=latency_ms,
        payload_hash=payload_hash,
        diff_hash=diff_hash,
        parent_decision_id=parent_decision_id,
        notes=notes,
    )
    db.add(decision)

    existing = await db.execute(
        select(HitlConfidence).where(HitlConfidence.bucket_key == bucket_key)
    )
    bucket = existing.scalar_one_or_none()
    now = datetime.now(UTC)
    if bucket is None:
        bucket = HitlConfidence(
            bucket_key=bucket_key,
            agent_id=agent_id,
            action_category=action_category,
            org_id=org_id,
            context_signature=context_signature,
            tier=HitlConfidenceTier.ASK,
        )
        db.add(bucket)

    bucket.n_observed = next_state.n_observed
    bucket.n_approved_clean = next_state.n_approved_clean
    bucket.n_approved_modified = next_state.n_approved_modified
    bucket.n_rejected = next_state.n_rejected
    bucket.n_timeout = next_state.n_timeout
    bucket.n_reverted = next_state.n_reverted
    bucket.beta_alpha = next_state.beta_alpha
    bucket.beta_beta = next_state.beta_beta
    bucket.confidence = next_state.confidence
    bucket.last_decision_at = now
    # Sprint 2: persist the next-state tier (apply_decision preserves or
    # demotes on revert; the caller has already run promote_if_eligible
    # when the outcome was positive). Also persist locked_until so the
    # repromotion lock window survives restarts.
    bucket.tier = HitlConfidenceTier(next_state.tier.value)
    bucket.locked_until = next_state.locked_until
    if bucket.tier is not HitlConfidenceTier.ASK and bucket.last_promoted_at is None:
        bucket.last_promoted_at = now

    await db.flush()
    await db.refresh(decision)
    return decision


# -- Endpoints ----------------------------------------------------------------


@router.post(
    "/hitl/decisions",
    response_model=RecordDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_decision(
    body: RecordDecisionRequest,
    _auth: None = Depends(_require_worker_token),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RecordDecisionResponse:
    """Record a HITL decision into the append-only log + roll the bucket."""
    context_signature = compute_signature(body.action_category, body.context)
    bucket_key = compute_bucket_key(
        body.agent_id, body.action_category, body.org_id, context_signature
    )
    _, state = await _load_bucket_state(db, bucket_key)
    next_state = apply_decision(state, body.outcome)
    # Sprint 2: on positive outcomes, let the bucket earn a higher tier.
    # Negative outcomes (reject/timeout/revert) never promote — revert
    # actively demotes inside apply_decision itself.
    if body.outcome in (
        DecisionOutcome.APPROVED_CLEAN,
        DecisionOutcome.APPROVED_MODIFIED,
    ):
        next_state = promote_if_eligible(next_state, body.action_category)

    decision = await _persist_decision_and_bucket(
        db,
        agent_id=body.agent_id,
        action_category=body.action_category,
        org_id=body.org_id,
        context_signature=context_signature,
        bucket_key=bucket_key,
        next_state=next_state,
        outcome=body.outcome,
        approver_id=body.approver_id,
        latency_ms=body.latency_ms,
        payload_hash=body.payload_hash,
        diff_hash=body.diff_hash,
        parent_decision_id=body.parent_decision_id,
        notes=body.notes,
    )

    # Audit trail: emit an event when bucket configuration changes
    # (tier promotion/demotion is the policy-relevant change). The
    # ``org_id`` here is the worker-supplied org_id from the request
    # body — this endpoint is worker-authenticated, so the body field
    # is the only available signal. We do NOT include payload_hash /
    # diff_hash / notes (PII risk); only IDs + tier + confidence.
    # Late import to avoid circular import with the events router.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="hitl_confidence.config_updated",
        event_category="hitl",
        agent_id=None,
        org_id=body.org_id,
        payload={
            "decision_id": str(decision.id),
            "bucket_key": bucket_key,
            "action_category": body.action_category,
            "outcome": body.outcome.value,
            "tier": next_state.tier.value,
            "confidence": next_state.confidence,
            "n_observed": next_state.n_observed,
        },
    )
    await db.commit()

    return RecordDecisionResponse(
        decision_id=str(decision.id),
        bucket_key=bucket_key,
        context_signature=context_signature,
        confidence=next_state.confidence,
        n_observed=next_state.n_observed,
        tier=HitlConfidenceTier(next_state.tier.value),
    )


@router.get("/hitl/confidence", response_model=ConfidenceDashboard)
async def list_confidence(
    action_category: str | None = Query(default=None),
    org_id: str | None = Query(default=None),
    min_observed: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _user: CurrentUser = Depends(require_roles(["admin"])),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ConfidenceDashboard:
    """Admin dashboard over all buckets. Filterable, capped."""
    q = select(HitlConfidence)
    if action_category:
        q = q.where(HitlConfidence.action_category == action_category)
    if org_id:
        q = q.where(HitlConfidence.org_id == org_id)
    if min_observed > 0:
        q = q.where(HitlConfidence.n_observed >= min_observed)
    q = q.order_by(desc(HitlConfidence.n_observed)).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    totals = (await db.execute(select(func.count()).select_from(HitlConfidence))).scalar_one()
    decisions_total = (
        await db.execute(select(func.count()).select_from(HitlDecision))
    ).scalar_one()

    return ConfidenceDashboard(
        total_buckets=int(totals),
        total_decisions=int(decisions_total),
        buckets=[
            BucketView(
                bucket_key=r.bucket_key,
                agent_id=r.agent_id,
                action_category=r.action_category,
                org_id=r.org_id,
                context_signature=r.context_signature,
                n_observed=r.n_observed,
                n_approved_clean=r.n_approved_clean,
                n_approved_modified=r.n_approved_modified,
                n_rejected=r.n_rejected,
                n_timeout=r.n_timeout,
                n_reverted=r.n_reverted,
                confidence=r.confidence,
                tier=r.tier,
                last_decision_at=r.last_decision_at.isoformat() if r.last_decision_at else None,
            )
            for r in rows
        ],
    )


@router.get("/hitl/decisions", response_model=DecisionList)
async def list_decisions(
    agent_id: str | None = Query(default=None),
    action_category: str | None = Query(default=None),
    outcome: HitlOutcome | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user: CurrentUser = Depends(require_roles(["admin"])),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> DecisionList:
    """Recent HITL decisions with filters. Observe-only; no mutation path."""
    q = select(HitlDecision)
    if agent_id:
        q = q.where(HitlDecision.agent_id == agent_id)
    if action_category:
        q = q.where(HitlDecision.action_category == action_category)
    if outcome is not None:
        q = q.where(HitlDecision.outcome == outcome)
    q = q.order_by(desc(HitlDecision.decided_at)).limit(limit)

    rows = (await db.execute(q)).scalars().all()
    total = (await db.execute(select(func.count()).select_from(HitlDecision))).scalar_one()

    return DecisionList(
        total=int(total),
        decisions=[
            DecisionView(
                id=str(r.id),
                decided_at=r.decided_at.isoformat(),
                agent_id=r.agent_id,
                action_category=r.action_category,
                org_id=r.org_id,
                bucket_key=r.bucket_key,
                outcome=r.outcome,
                approver_id=r.approver_id,
                latency_ms=r.latency_ms,
                notes=r.notes,
            )
            for r in rows
        ],
    )
