"""
Gap 2: Command Approvals REST router.

Allows operators to view pending dangerous command approval requests and
resolve them from the API, UI, or any connected gateway channel.

Also emits HITL-confidence decisions (Sprint 1 — observe only): every
approve/deny here becomes a row in ``hitl_decisions`` so the confidence
dashboard can grow statistics without any change in enforcement.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_permissions import (
    DecisionOutcome,
    apply_decision,
    compute_bucket_key,
    compute_signature,
)

from ..auth import CurrentUser, require_roles
from ..database import get_db
from ..models import ApprovalStatus
from ..models import CommandApprovalRequest as ApprovalRequest
from .hitl_confidence import _load_bucket_state, _persist_decision_and_bucket

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/command-approvals", tags=["Command Approvals"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ApprovalRequestResponse(BaseModel):
    id: str
    run_id: str
    command: str
    reason: str
    status: ApprovalStatus
    requested_at: str
    resolved_at: str | None
    resolved_by: str | None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=list[ApprovalRequestResponse])
async def list_pending(
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequestResponse]:
    """List all pending dangerous command approval requests."""
    result = await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == ApprovalStatus.PENDING)
        .order_by(ApprovalRequest.requested_at.desc())
    )
    return [_to_schema(r) for r in result.scalars().all()]


@router.post("/{request_id}/approve", response_model=ApprovalRequestResponse)
async def approve_command(
    request_id: str,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Approve a pending dangerous command."""
    return await _resolve(request_id, approved=True, user=user, db=db)


@router.post("/{request_id}/deny", response_model=ApprovalRequestResponse)
async def deny_command(
    request_id: str,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Deny a pending dangerous command."""
    return await _resolve(request_id, approved=False, user=user, db=db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve(
    request_id: str, approved: bool, user: CurrentUser, db: AsyncSession
) -> ApprovalRequestResponse:
    req = await db.get(ApprovalRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if req.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Request already {req.status}")

    decided_at = datetime.now(tz=UTC)
    # `CurrentUser` is `dict[str, Any]` — see `nexus_api.auth.get_current_user`.
    # The previous `user.sub` access happened to work at runtime because the
    # dict carries a `sub` key, but mypy correctly flagged it as unsafe.
    user_sub = user["sub"]
    req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
    req.resolved_at = decided_at
    req.resolved_by = user_sub

    # Record a HITL-confidence decision alongside the approval row. Best
    # effort: if anything below fails, the approval itself still resolves.
    # Sprint 1 is observe-only, so this write never feeds back into the
    # command-gate itself. Run inside the same commit so the decision + the
    # approval land atomically.
    try:
        await _record_confidence_decision(
            db=db,
            request=req,
            approved=approved,
            decided_at=decided_at,
            approver_id=user_sub,
        )
    except Exception:
        logger.exception("HITL confidence recording failed (observe-only, non-fatal)")

    await db.commit()
    await db.refresh(req)

    # Notify the in-process approval store
    from selva_tools.approval import resolve_approval

    resolve_approval(request_id, approved, resolved_by=user_sub)

    logger.info("Approval %s %s by %s", request_id, req.status, user_sub)
    return _to_schema(req)


async def _record_confidence_decision(
    *,
    db: AsyncSession,
    request: ApprovalRequest,
    approved: bool,
    decided_at: datetime,
    approver_id: str,
) -> None:
    """Emit a HITL decision for this approval resolution.

    The command approval path doesn't carry an agent_id or org_id today,
    so we use the run_id as the agent slot and ``*`` as the org. Workers
    that surface richer context (org, lead-stage, template) should POST
    directly to ``/api/v1/hitl/decisions`` instead of going through this
    router. This wiring exists so the dashboard starts showing data the
    moment Sprint 1 lands, even for the thinnest approval pathway.
    """
    # Latency: approval latency from request creation to resolution.
    latency_ms: int | None = None
    if request.requested_at is not None:
        requested = request.requested_at
        if requested.tzinfo is None:
            # Defensive: older rows may have naive timestamps.

            requested = requested.replace(tzinfo=UTC)
        latency_ms = int((decided_at - requested).total_seconds() * 1000)

    action_category = "infrastructure_exec"  # command-approvals gate dangerous commands
    ctx = {
        "agent_role": "system",
        "run_id": request.run_id,
    }
    signature = compute_signature(action_category, ctx)
    bucket_key = compute_bucket_key(
        agent_id=request.run_id,
        action_category=action_category,
        org_id="*",
        context_signature=signature,
    )
    _, state = await _load_bucket_state(db, bucket_key)
    outcome = DecisionOutcome.APPROVED_CLEAN if approved else DecisionOutcome.REJECTED
    next_state = apply_decision(state, outcome)
    payload_hash = hashlib.sha256((request.command or "").encode("utf-8")).hexdigest()
    await _persist_decision_and_bucket(
        db,
        agent_id=request.run_id,
        action_category=action_category,
        org_id="*",
        context_signature=signature,
        bucket_key=bucket_key,
        next_state=next_state,
        outcome=outcome,
        approver_id=approver_id,
        latency_ms=latency_ms,
        payload_hash=payload_hash,
        diff_hash=None,
        parent_decision_id=None,
        notes=None,
    )


def _to_schema(r: ApprovalRequest) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=r.id,
        run_id=r.run_id,
        command=r.command,
        reason=r.reason,
        status=r.status,
        requested_at=r.requested_at.isoformat() if r.requested_at else "",
        resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
        resolved_by=r.resolved_by,
    )
