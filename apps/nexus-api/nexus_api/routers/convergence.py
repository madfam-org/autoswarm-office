"""Convergence read surface for converge-dash (RFC 0034 P1b / D7).

converge-dash's SelvaClient calls `GET /api/v1/convergence/ai-tasks` to ingest
AI-task metrics for the executive dashboard, but the route did not exist — the
convergence view of AI activity 404'd. This adds it.

It joins SwarmTask (the agent-task record) with the compute-token ledger (the
RFC 0034 P1 usage ledger, now carrying real per-call tokens + USD) to return
the SelvaAiTask contract converge-dash validates:
    task_id, workflow_name, agent_name?, status, started_at?, completed_at?,
    cost_mxn?, tokens_in?, tokens_out?, tool_call_count?, human_interventions?,
    error_class?

Boundary note (RFC 0034 D4): Selva reports its NATIVE cost in USD via
`cost_usd`. It does NOT convert to MXN — FX is Dhanam's concern (Banxico
ownership). `cost_mxn` is therefore omitted here; converge-dash treats it as
optional and can apply FX from its own Dhanam-sourced rate. This keeps the
intelligence plane out of the money/FX plane.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import ComputeTokenLedger, SwarmTask

router = APIRouter(tags=["convergence"])


class ConvergenceAiTask(BaseModel):
    task_id: str
    workflow_name: str
    agent_name: str | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    # Selva's native cost is USD (RFC 0034 P1). cost_mxn intentionally omitted —
    # FX conversion is Dhanam's concern, not the intelligence plane's.
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tool_call_count: int | None = None
    human_interventions: int | None = None
    error_class: str | None = None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/ai-tasks", response_model=list[ConvergenceAiTask])
async def list_ai_tasks(
    period_start: str = Query(..., description="ISO datetime, inclusive lower bound"),
    period_end: str = Query(..., description="ISO datetime, exclusive upper bound"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> list[ConvergenceAiTask]:
    """AI-task metrics for the executive convergence dashboard (converge-dash)."""
    try:
        start = datetime.fromisoformat(period_start)
        end = datetime.fromisoformat(period_end)
    except ValueError:
        # Malformed window → empty rather than 500; the caller controls the range.
        return []

    tasks = (
        await db.execute(
            select(SwarmTask)
            .where(SwarmTask.created_at >= start, SwarmTask.created_at < end)
            .order_by(SwarmTask.created_at)
        )
    ).scalars().all()

    if not tasks:
        return []

    # One aggregate query for tokens + USD per task from the P1 ledger, so the
    # dashboard sees real inference cost, not a flat guess.
    task_ids = [t.id for t in tasks]
    ledger_rows = (
        await db.execute(
            select(
                ComputeTokenLedger.task_id,
                func.coalesce(func.sum(ComputeTokenLedger.amount), 0),
                func.coalesce(func.sum(ComputeTokenLedger.cost_usd), 0),
            )
            .where(ComputeTokenLedger.task_id.in_(task_ids))
            .group_by(ComputeTokenLedger.task_id)
        )
    ).all()
    ledger_by_task = {row[0]: (int(row[1]), float(row[2])) for row in ledger_rows}

    result: list[ConvergenceAiTask] = []
    for t in tasks:
        tokens, cost_usd = ledger_by_task.get(t.id, (None, None))
        result.append(
            ConvergenceAiTask(
                task_id=str(t.id),
                workflow_name=t.graph_type,
                agent_name=(str(t.assigned_agent_ids[0]) if t.assigned_agent_ids else None),
                status=t.status,
                started_at=_iso(t.started_at),
                completed_at=_iso(t.completed_at),
                cost_usd=cost_usd,
                # We record total tokens per task (amount); the in/out split is a
                # per-call detail on the activity stream, not the ledger, so the
                # dashboard gets the total under tokens_in with tokens_out null.
                tokens_in=tokens,
            )
        )
    return result
