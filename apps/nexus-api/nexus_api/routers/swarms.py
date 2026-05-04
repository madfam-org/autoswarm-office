"""Swarm task dispatch and monitoring endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from selva_orchestrator import ComputeTokenManager
from selva_permissions import Audience as PermissionAudience
from selva_permissions import is_audience_enforcement_enabled, resolve_audience
from selva_redis_pool import get_redis_pool
from selva_skills import SkillAudience, get_skill_registry

from ..auth import get_current_user, require_non_demo, require_non_guest
from ..billing_tiers import get_daily_limit
from ..config import get_settings
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import Agent, ComputeTokenLedger, SwarmTask, TaskEvent, TenantConfig, Workflow
from ..tenant import TenantContext, get_tenant
from ..ws import MessageRateLimiter

router = APIRouter(tags=["swarms"], dependencies=[Depends(get_current_user)])

# -- Per-user dispatch rate limiter -------------------------------------------
_settings = get_settings()
_dispatch_limiter = MessageRateLimiter(
    max_messages=_settings.dispatch_rate_limit,
    window_seconds=float(_settings.dispatch_rate_window),
)

# -- Module-internal constants -------------------------------------------------
# Cost (in compute tokens) of dispatching one swarm task. Sourced from the
# canonical ``ComputeTokenManager.COST_TABLE`` in selva_orchestrator so the
# value lives in exactly one place. Falls back to a hardcoded default if
# the orchestrator package ever drops the entry (defensive — also lets us
# load this module before the orchestrator is initialised).
_DISPATCH_COMPUTE_TOKEN_COST: int = ComputeTokenManager.COST_TABLE.get("dispatch_task", 10)

# Page size for the kanban-style task board endpoint. Bounded so the
# server-side query plus payload serialisation stays within the request
# timeout for orgs with high task volume.
_TASK_BOARD_PAGE_SIZE: int = 100


async def require_dispatch_rate_limit(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    """Reject dispatch requests that exceed the per-user rate limit."""
    user_sub = user.get("sub", "anonymous")
    if not _dispatch_limiter.check(user_sub):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Dispatch rate limit exceeded",
        )


# -- Request / Response schemas -----------------------------------------------


class DispatchRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    graph_type: str = Field(
        default="sequential",
        pattern=r"^(sequential|parallel|coding|research|crm|custom|deployment|puppeteer|meeting|billing|accounting|sales|intelligence|operations)$",
    )
    assigned_agent_ids: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = Field(
        default=None,
        description="UUID of a custom workflow definition (required for graph_type='custom')",
    )


class SwarmTaskResponse(BaseModel):
    id: str
    description: str
    graph_type: str
    assigned_agent_ids: list[str]
    payload: dict[str, Any]
    status: str
    created_at: str
    completed_at: str | None

    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(running|completed|failed|cancelled)$")
    result: dict[str, Any] | None = None
    started_at: str | None = None
    error_message: str | None = None


# -- Helpers ------------------------------------------------------------------


def _compute_perf_weight(agent: Agent) -> float:
    """Compute a 0.0-1.0 performance weight from agent stats.

    ``perf_weight = 0.5 * approval_rate + 0.5 * completion_rate``
    New agents (no history) default to 0.5 (neutral).
    """
    total_tasks = agent.tasks_completed + agent.tasks_failed
    total_approvals = agent.approval_success_count + agent.approval_denial_count

    if total_tasks == 0 and total_approvals == 0:
        return 0.5  # Neutral for new agents

    completion_rate = agent.tasks_completed / total_tasks if total_tasks > 0 else 0.5
    approval_rate = agent.approval_success_count / total_approvals if total_approvals > 0 else 0.5

    return 0.5 * approval_rate + 0.5 * completion_rate


def _task_to_response(task: SwarmTask) -> SwarmTaskResponse:
    return SwarmTaskResponse(
        id=str(task.id),
        description=task.description,
        graph_type=task.graph_type,
        assigned_agent_ids=task.assigned_agent_ids or [],
        payload=task.payload or {},
        status=task.status,
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


# -- Endpoints ----------------------------------------------------------------


@router.post(
    "/dispatch",
    response_model=SwarmTaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_non_guest),
        Depends(require_non_demo),
        Depends(require_dispatch_rate_limit),
    ],
)
async def dispatch_task(
    body: DispatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> SwarmTaskResponse:
    """Dispatch a new swarm task.

    Validates compute token budget, persists the task, and publishes a
    message to the Redis task queue for worker consumption.

    Idempotency: when the caller sends ``Idempotency-Key`` header, a
    successful response is cached for 24h scoped by (org_id, POST,
    /api/v1/swarms/dispatch, key). Retries with the same key replay the
    cached response instead of dispatching a duplicate task. Header
    absent → endpoint behaves exactly as before (no caching).
    """
    # Idempotency replay short-circuit. Must run before any DB work so
    # the second call doesn't even hit the compute-budget ledger.
    if idem.is_replay and idem.cached is not None:
        return SwarmTaskResponse.model_validate(idem.cached)

    settings = get_settings()

    # Extract request_id for cross-service correlation.
    request_id = getattr(request.state, "request_id", None)

    # -- Validate custom workflow dispatch ------------------------------------
    workflow_yaml: str | None = None
    if body.graph_type == "custom":
        if not body.workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workflow_id is required when graph_type is 'custom'",
            )
        try:
            wf_uid = uuid.UUID(body.workflow_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workflow_id UUID",
            ) from exc
        wf_result = await db.execute(select(Workflow).where(Workflow.id == wf_uid))
        wf = wf_result.scalar_one_or_none()
        if wf is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )
        workflow_yaml = wf.yaml_content

    # -- Audience gate --------------------------------------------------------
    # A tenant swarm (org_id != PLATFORM_ORG_ID) cannot dispatch a task
    # that requires platform-audience skills. Platform swarms can
    # dispatch any audience (superset). Unset PLATFORM_ORG_ID means
    # every caller is tenant audience — no platform skills are
    # dispatchable at all, which is the safe default until MADFAM's
    # own org is configured.
    caller_audience = resolve_audience(tenant.org_id)
    if body.required_skills and caller_audience is PermissionAudience.TENANT:
        forbidden: list[str] = []
        try:
            skill_registry = get_skill_registry()
        except Exception:
            skill_registry = None
        if skill_registry is not None:
            for skill_name in body.required_skills:
                meta = skill_registry.get_metadata(skill_name)
                if meta is not None and meta.audience is SkillAudience.PLATFORM:
                    forbidden.append(skill_name)
        if forbidden:
            if is_audience_enforcement_enabled():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "audience_mismatch",
                        "message": ("Tenant swarms cannot dispatch platform-audience skills."),
                        "forbidden_skills": forbidden,
                        "caller_audience": caller_audience.value,
                    },
                )
            # Shadow mode: log + allow. Flip AUDIENCE_FILTER_ENABLED to
            # enforce once the production rate of shadow blocks is known.
            logging.getLogger(__name__).warning(
                "audience_shadow_block caller_org=%s caller_audience=%s "
                "forbidden_skills=%s (permitting — AUDIENCE_FILTER_ENABLED off)",
                tenant.org_id,
                caller_audience.value,
                forbidden,
            )

    # -- Skill-based agent matching (when no explicit agents provided) --------
    assigned_agent_ids = body.assigned_agent_ids
    if not assigned_agent_ids and body.required_skills:
        # Auto-select agents by skill overlap
        try:
            from selva_skills import DEFAULT_ROLE_SKILLS

            result = await db.execute(
                select(Agent).where(Agent.status == "idle").order_by(Agent.created_at)
            )
            idle_agents = result.scalars().all()
            scored: list[tuple[float, Any]] = []
            required = set(body.required_skills)
            for agent in idle_agents:
                agent_skills = set(agent.skill_ids or DEFAULT_ROLE_SKILLS.get(agent.role, []))
                overlap = len(required & agent_skills)
                if overlap > 0:
                    skill_score = overlap / len(required)
                    # Performance-weighted scoring (30% weight)
                    perf_weight = _compute_perf_weight(agent)
                    final_score = skill_score * (0.7 + 0.3 * perf_weight)
                    scored.append((final_score, agent))
            scored.sort(key=lambda x: x[0], reverse=True)
            assigned_agent_ids = [str(a.id) for _, a in scored[:3]]
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to auto-select agents by skill",
                exc_info=True,
            )

    # -- Fallback: auto-assign any idle agent when no agents or skills given --
    if not assigned_agent_ids:
        try:
            fallback_result = await db.execute(
                select(Agent)
                .where(Agent.org_id == tenant.org_id)
                .where(Agent.status == "idle")
                .order_by(Agent.created_at)
                .limit(1)
            )
            fallback_agent = fallback_result.scalar_one_or_none()
            if fallback_agent is None:
                # No idle agents — pick any agent in the org
                fallback_result = await db.execute(
                    select(Agent)
                    .where(Agent.org_id == tenant.org_id)
                    .order_by(Agent.created_at)
                    .limit(1)
                )
                fallback_agent = fallback_result.scalar_one_or_none()
            if fallback_agent is not None:
                assigned_agent_ids = [str(fallback_agent.id)]
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to auto-assign fallback agent",
                exc_info=True,
            )

    # -- Tenant limit enforcement -----------------------------------------------
    tenant_config = None
    try:
        tc_result = await db.execute(
            select(TenantConfig).where(TenantConfig.org_id == tenant.org_id)
        )
        tenant_config = tc_result.scalar_one_or_none()
        if tenant_config is not None:
            # Check daily task limit
            today_start_tc = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            today_count_result = await db.execute(
                select(func.count(SwarmTask.id)).where(
                    SwarmTask.org_id == tenant.org_id,
                    SwarmTask.created_at >= today_start_tc,
                )
            )
            today_count: int = today_count_result.scalar_one()
            if today_count >= tenant_config.max_daily_tasks:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily task limit reached for your organization",
                )

            # Check agent capacity (warn, don't block)
            agent_count_result = await db.execute(
                select(func.count(Agent.id)).where(Agent.org_id == tenant.org_id)
            )
            agent_count: int = agent_count_result.scalar_one()
            if agent_count >= tenant_config.max_agents:
                logging.getLogger(__name__).warning(
                    "Org %s at agent capacity (%d/%d)",
                    tenant.org_id,
                    agent_count,
                    tenant_config.max_agents,
                )
    except HTTPException:
        raise
    except SQLAlchemyError:
        logging.getLogger(__name__).warning(
            "Tenant limit check failed due to DB error; refusing dispatch",
            exc_info=True,
        )
        # Rollback the failed transaction so the session is reusable.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="transient db error during quota check",
        ) from None

    # -- Compute token budget enforcement (Dhanam subscription tier) ----------
    if tenant_config and tenant_config.dhanam_space_id:
        try:
            from ..billing_client import get_billing_status

            billing = await get_billing_status(tenant_config.dhanam_space_id)
            if billing and billing.get("compute_tokens_remaining", float("inf")) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Compute token budget exhausted. Upgrade your subscription at dhan.am",
                )
        except HTTPException:
            raise
        except Exception:
            logging.getLogger(__name__).debug(
                "Compute budget check skipped (Dhanam unavailable)", exc_info=True
            )

    # -- Compute token budget check -------------------------------------------
    dispatch_cost = _DISPATCH_COMPUTE_TOKEN_COST

    # Check remaining budget before dispatching.
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    budget_result = await db.execute(
        select(func.coalesce(func.sum(ComputeTokenLedger.amount), 0)).where(
            ComputeTokenLedger.created_at >= today_start,
            ComputeTokenLedger.org_id == tenant.org_id,
        )
    )
    used: int = budget_result.scalar_one()
    # Default tier limit when no Dhanam-cached entry exists in Redis.
    # billing_internal.check_budget consults the cache; this branch is
    # the fast path that keeps dispatch latency low. Source-of-truth:
    # ``nexus_api.billing_tiers``.
    daily_limit = get_daily_limit(None)
    if used + dispatch_cost > daily_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Compute token budget exceeded for today",
        )

    # Record the debit in the ledger (the in-memory ComputeTokenManager lives
    # in the orchestrator package; the ledger is the durable record).
    wf_uid_value = wf_uid if body.graph_type == "custom" else None
    task = SwarmTask(
        description=body.description,
        graph_type=body.graph_type,
        assigned_agent_ids=assigned_agent_ids,
        payload=body.payload,
        status="queued",
        org_id=tenant.org_id,
        workflow_id=wf_uid_value,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    ledger_entry = ComputeTokenLedger(
        action="dispatch_task",
        amount=dispatch_cost,
        task_id=task.id,
        org_id=tenant.org_id,
    )
    db.add(ledger_entry)
    await db.flush()

    # -- Publish to Redis queue for workers -----------------------------------
    try:
        pool = get_redis_pool(url=settings.redis_url)
        task_msg_data: dict[str, Any] = {
            "task_id": str(task.id),
            "graph_type": task.graph_type,
            "description": task.description,
            "assigned_agent_ids": task.assigned_agent_ids,
            "required_skills": body.required_skills,
            "payload": task.payload,
            "request_id": request_id,
        }
        if workflow_yaml is not None:
            task_msg_data["workflow_yaml"] = workflow_yaml

        # Resolve matching playbook for autonomous execution (Axiom IV)
        try:
            from .playbooks import _playbooks

            trigger_event = (task.payload or {}).get("trigger_event", "")
            if trigger_event:
                for pb in _playbooks.values():
                    if (
                        pb["trigger_event"] == trigger_event
                        and pb["enabled"]
                        and not pb["require_approval"]
                    ):
                        task_msg_data["playbook_id"] = pb["id"]
                        task_msg_data["playbook"] = pb
                        break
        except Exception:
            logging.getLogger(__name__).debug(
                "Failed to resolve autonomous playbook for trigger_event",
                exc_info=True,
            )
        task_msg = json.dumps(task_msg_data)
        await pool.execute_with_retry("xadd", "autoswarm:task-stream", {"data": task_msg})
    except Exception:
        # If Redis is unavailable the task is still persisted in the DB.
        # Workers can fall back to polling the database.
        task.status = "pending"
        await db.flush()

    # Emit task.dispatched event (direct DB insert, no HTTP)
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.dispatched",
            event_category="task",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=tenant.org_id,
            request_id=request_id,
            payload={"description": task.description[:200], "graph_type": task.graph_type},
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task.dispatched event",
            exc_info=True,
        )

    # PostHog analytics
    try:
        from nexus_api.analytics import track

        track(
            str(tenant.org_id),
            "selva_task_dispatched",
            {
                "graph_type": body.graph_type,
                "task_id": str(task.id),
            },
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit PostHog selva_task_dispatched event",
            exc_info=True,
        )

    response = _task_to_response(task)

    # Cache the response BEFORE returning so a network blip mid-response
    # on the first call still gives the second call something to replay.
    # No-op when the caller didn't send Idempotency-Key.
    await idem.save(response.model_dump(mode="json"))

    return response


@router.get("/tasks", response_model=list[SwarmTaskResponse])
async def list_active_tasks(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[SwarmTaskResponse]:
    """List tasks that are currently queued or in progress."""
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.status.in_(["queued", "pending", "running"]))
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_task_to_response(t) for t in tasks]


class TaskBoardItem(BaseModel):
    id: str
    description: str
    graph_type: str
    status: str
    agent_names: list[str]
    created_at: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    total_tokens: int | None
    event_count: int

    model_config = {"from_attributes": True}


class TaskBoardResponse(BaseModel):
    columns: dict[str, list[TaskBoardItem]]
    totals: dict[str, int]


@router.get("/tasks/board", response_model=TaskBoardResponse)
async def get_task_board(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> TaskBoardResponse:
    """Return tasks grouped by status column with aggregated event data."""
    # Fetch recent tasks (last N — see _TASK_BOARD_PAGE_SIZE).
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.created_at.desc())
        .limit(_TASK_BOARD_PAGE_SIZE)
    )
    tasks = result.scalars().all()

    # Aggregate event data per task
    task_ids = [t.id for t in tasks]
    event_agg: dict[str, dict] = {}
    if task_ids:
        agg_result = await db.execute(
            select(
                TaskEvent.task_id,
                func.sum(TaskEvent.duration_ms),
                func.sum(TaskEvent.token_count),
                func.count(TaskEvent.id),
            )
            .where(TaskEvent.task_id.in_(task_ids))
            .group_by(TaskEvent.task_id)
        )
        for row in agg_result:
            event_agg[str(row[0])] = {
                "duration_ms": row[1],
                "total_tokens": row[2],
                "event_count": row[3],
            }

    # Resolve agent names
    all_agent_ids: set[str] = set()
    for t in tasks:
        for aid in t.assigned_agent_ids or []:
            all_agent_ids.add(aid)

    agent_names: dict[str, str] = {}
    if all_agent_ids:
        for aid in all_agent_ids:
            # NOTE: ``uuid.UUID(aid)`` raises ``ValueError`` on malformed IDs,
            # and ``db.execute(...)`` can raise ``SQLAlchemyError`` (not a
            # ``ValueError`` subclass). ``Exception`` is the smallest common
            # ancestor that catches both — name-resolution is best-effort.
            try:
                uid = uuid.UUID(aid)
                agent_result = await db.execute(select(Agent).where(Agent.id == uid))
                agent = agent_result.scalar_one_or_none()
                if agent:
                    agent_names[aid] = agent.name
            except Exception:
                logging.getLogger(__name__).debug(
                    "Failed to resolve agent name for %s",
                    aid,
                    exc_info=True,
                )

    # Build columns
    columns: dict[str, list[TaskBoardItem]] = {
        "queued": [],
        "running": [],
        "completed": [],
        "failed": [],
    }

    status_map = {
        "queued": "queued",
        "pending": "queued",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "failed",
    }

    for t in tasks:
        task_id_str = str(t.id)
        agg = event_agg.get(task_id_str, {})
        col = status_map.get(t.status, "queued")

        item = TaskBoardItem(
            id=task_id_str,
            description=t.description,
            graph_type=t.graph_type,
            status=t.status,
            agent_names=[agent_names.get(aid, aid[:8]) for aid in (t.assigned_agent_ids or [])],
            created_at=t.created_at.isoformat(),
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            duration_ms=agg.get("duration_ms"),
            total_tokens=agg.get("total_tokens"),
            event_count=agg.get("event_count", 0),
        )
        columns[col].append(item)

    totals = {col: len(items) for col, items in columns.items()}

    return TaskBoardResponse(columns=columns, totals=totals)


@router.get("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SwarmTaskResponse:
    """Retrieve a single task by ID."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return _task_to_response(task)


@router.patch("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SwarmTaskResponse:
    """Update a task's status.

    When the status transitions to ``completed`` or ``failed`` the
    ``completed_at`` timestamp is set automatically.
    """
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Capture old status for the audit event payload (lets OpsFeed render
    # "queued → running" arrows without a follow-up DB query).
    old_status = task.status

    task.status = body.status

    if body.result is not None:
        task.payload = {**(task.payload or {}), "result": body.result}

    if body.started_at is not None:
        task.started_at = datetime.fromisoformat(body.started_at)

    if body.error_message is not None:
        task.error_message = body.error_message

    if body.status in ("completed", "failed"):
        task.completed_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(task)

    # Audit trail: emit task.status_changed event. Worker writes back
    # queued → running → completed/failed via this PATCH; today the table
    # holds the truth but the event stream doesn't, forcing OpsFeed to
    # poll. Carrying old → new in the payload lets clients render
    # transitions without an extra fetch. See gap doc #3.
    #
    # org_id is taken from the task row itself (the resource being
    # mutated), not from the worker's X-Selva-Tenant-Org header — the
    # truth-of-record for "which tenant owns this task" lives on the
    # row. error_message is intentionally excluded from the payload
    # because it can carry stack traces / file paths that other tenants
    # in the same org should not necessarily see in the activity feed.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.status_changed",
            event_category="task",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=task.org_id,
            payload={
                "task_id": str(task.id),
                "old_status": old_status,
                "new_status": task.status,
            },
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task.status_changed event",
            exc_info=True,
        )

    return _task_to_response(task)


# Roles allowed to call the cross-tenant reap-stale endpoint. ``service``
# and ``worker`` cover automated callers (cron jobs, ops tooling using the
# worker shared-secret token); ``platform`` and ``admin`` cover human
# operators. Any other authenticated caller (regular tactician, guest,
# demo) is rejected with 403.
_REAP_STALE_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"service", "worker", "platform", "admin"}
)


@router.post("/tasks/reap-stale")
async def reap_stale_tasks(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict[str, int]:
    """Auto-fail queued/pending tasks older than 1 hour (cross-tenant ops).

    This is a platform health endpoint that operators or a cron job call
    to clean up stuck tasks across **all tenants**. The role gate is the
    access control: only callers carrying ``service``, ``worker``,
    ``platform``, or ``admin`` roles may invoke it.

    Tenancy bypass (Phase 1.5 -- migration 0028):
        Uses ``admin_session()`` which opens a session against the
        ``app_admin`` BYPASSRLS connection pool. This is the canonical
        way to express "I genuinely need to read/mutate rows belonging
        to multiple tenants in one query" under the strict RLS policies
        installed by migration 0028.

        Pre-migration-0028 this endpoint relied on the Phase 1 permissive
        policy (``IS NULL OR = '' OR = $org``) and manually reset the
        session var to ``""`` to fall through to the IS NULL leg. That
        leg no longer exists -- under the strict policies a reset
        session var would return zero rows. ``admin_session()`` logs at
        WARNING on every entry, so the cross-tenant access is visible in
        structured logs without needing to parse pg_stat_activity.

        See ``docs/RLS_PHASE_1_5_AUDIT.md`` §2.C and §3 for the full
        rationale.
    """
    from datetime import timedelta

    from ..database import admin_session

    roles = user.get("roles", [])
    if not any(r in _REAP_STALE_ALLOWED_ROLES for r in roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "reap-stale is a platform-only endpoint; caller must hold "
                "service, worker, platform, or admin role"
            ),
        )

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    async with admin_session() as db:
        result = await db.execute(
            select(SwarmTask)
            .where(SwarmTask.status.in_(["queued", "pending"]))
            .where(SwarmTask.created_at < cutoff)
        )
        stale_tasks = result.scalars().all()

        for task in stale_tasks:
            task.status = "failed"
            task.error_message = "Reaped: stale task older than 1 hour"
            task.completed_at = datetime.now(UTC)

        await db.flush()
        reaped_count = len(stale_tasks)

    if reaped_count:
        logging.getLogger(__name__).warning(
            "Reaped %d stale task(s) across all tenants (caller=%s)",
            reaped_count,
            user.get("sub", "unknown"),
        )

    return {"reaped": reaped_count}
