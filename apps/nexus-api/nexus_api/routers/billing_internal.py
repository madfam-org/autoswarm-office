"""Internal billing endpoints for worker-to-API metering.

Service-to-service (workers -> nexus-api). These write and read the compute
token ledger, so they are authenticated (RFC 0034 P0 / D6): every call must
present a valid Janua JWT or the worker service token via `get_current_user`.
Network policy remains defence-in-depth, but auth is no longer *only* the
network — the previous "unauthenticated, rely on network policy" posture let
anyone in-namespace forge or read cross-tenant billing entries.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import ComputeTokenLedger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing-internal"])


class RecordRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=100)
    amount: int = Field(..., ge=1)
    provider: str | None = None
    model: str | None = None
    agent_id: str | None = None
    task_id: str | None = None
    # Deprecated: org scope is derived from the authenticated caller. A
    # body-supplied value is only accepted when it matches that scope
    # (transition-safety for older workers) and is rejected otherwise.
    org_id: str | None = None


class BudgetResponse(BaseModel):
    daily_limit: int
    used: int
    remaining: int
    over_budget: bool


def _resolve_caller_org(user: dict, body_org_id: str | None) -> str:
    """Derive the org scope from the authenticated caller.

    Mirrors the events-router invariant (AGENTS.md tenant scoping): the body
    may not name an org. A matching body value is tolerated so older workers
    that still send ``org_id`` keep working; a mismatch is a 403.
    """
    caller_org = user.get("org_id") or "default"
    if body_org_id is not None and body_org_id != caller_org:
        raise HTTPException(
            status_code=403,
            detail="org_id in request body does not match authenticated org scope",
        )
    return caller_org


@router.post("/record", status_code=201)
async def record_usage(
    body: RecordRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Record a compute token debit from a worker (authenticated, RFC 0034 P0).

    Org scope comes from the authenticated caller (worker tokens declare it
    via ``X-Selva-Tenant-Org``), never from the request body — a caller must
    not be able to debit another tenant's bucket.
    """
    org_id = _resolve_caller_org(user, body.org_id)
    entry = ComputeTokenLedger(
        action=body.action,
        amount=body.amount,
        provider=body.provider,
        model=body.model,
        org_id=org_id,
    )
    if body.agent_id:
        with contextlib.suppress(ValueError):
            entry.agent_id = uuid.UUID(body.agent_id)
    if body.task_id:
        with contextlib.suppress(ValueError):
            entry.task_id = uuid.UUID(body.task_id)

    db.add(entry)
    await db.flush()
    return {"status": "recorded"}


@router.post("/check-budget", response_model=BudgetResponse)
async def check_budget(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> BudgetResponse:
    """Check the caller's remaining compute token budget for today (authenticated, RFC 0034 P0).

    Scope is the authenticated org — one tenant must not be able to read
    another tenant's spend position.
    """
    org_id = _resolve_caller_org(user, body.get("org_id"))
    from ..services.tier_limits import resolve_org_daily_limit

    daily_limit = await resolve_org_daily_limit(db, org_id)

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(ComputeTokenLedger.amount), 0)).where(
            ComputeTokenLedger.created_at >= today_start,
            ComputeTokenLedger.org_id == org_id,
        )
    )
    used: int = result.scalar_one()

    remaining = max(0, daily_limit - used)
    return BudgetResponse(
        daily_limit=daily_limit,
        used=used,
        remaining=remaining,
        over_budget=remaining <= 0,
    )
