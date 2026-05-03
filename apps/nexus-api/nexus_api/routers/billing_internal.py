"""Internal billing endpoints for worker-to-API metering.

These endpoints are not protected by user authentication -- they are intended
for internal service-to-service calls (workers -> nexus-api). In production,
network policy should restrict access to these endpoints.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..config import get_settings
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
    org_id: str = "default"


class BudgetResponse(BaseModel):
    daily_limit: int
    used: int
    remaining: int
    over_budget: bool


@router.post("/record", status_code=201)
async def record_usage(
    body: RecordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Record a compute token debit from a worker."""
    entry = ComputeTokenLedger(
        action=body.action,
        amount=body.amount,
        provider=body.provider,
        model=body.model,
        org_id=body.org_id,
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
) -> BudgetResponse:
    """Check whether an org has remaining compute token budget for today."""
    org_id = body.get("org_id", "default")
    daily_limit = 1000  # Default; production reads from Redis tier cache

    # Look up cached tier limit from Redis
    try:
        settings = get_settings()
        pool = get_redis_pool(url=settings.redis_url)
        cached = await pool.execute_with_retry("get", f"autoswarm:tier:{org_id}")
        if cached:
            daily_limit = int(cached)  # type: ignore[call-overload]
    except Exception:
        logger.debug("Failed to fetch cached tier limit from Redis", exc_info=True)

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
