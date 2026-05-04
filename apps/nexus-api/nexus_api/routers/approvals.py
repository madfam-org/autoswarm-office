"""Approval request management and real-time WebSocket stream."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..approval_notifier import notify_approval_decision
from ..auth import get_current_user, require_non_guest, verify_jwt
from ..config import get_settings
from ..database import get_db, tenant_session
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import ApprovalRequest, SwarmTask
from ..tenant import TenantContext, get_tenant
from ..ws import MessageRateLimiter, manager

_wave_logger = logging.getLogger(__name__ + ".wave")
logger = logging.getLogger(__name__)

router = APIRouter(tags=["approvals"])

# WebSocket rate limit values come from Settings
# (approvals_ws_rate_limit / approvals_ws_rate_window_seconds) so ops
# can tune per-client flood guards without a code change. Mirrors the
# /events/ws limit defaults (same UI usage pattern) but split so they
# can be tuned independently.
_settings_for_ws = get_settings()
_ws_rate_limiter = MessageRateLimiter(
    max_messages=_settings_for_ws.approvals_ws_rate_limit,
    window_seconds=_settings_for_ws.approvals_ws_rate_window_seconds,
)


# -- Request / Response schemas -----------------------------------------------


class CreateApprovalRequest(BaseModel):
    agent_id: str
    action_category: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    urgency: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    diff: str | None = None
    # NOTE: org_id is NOT accepted from the request body. It is derived
    # server-side from the authenticated worker (X-Selva-Tenant-Org header).


class ApprovalAction(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)


class ApprovalRequestResponse(BaseModel):
    id: str
    agent_id: str
    action_category: str
    action_type: str
    payload: dict[str, Any]
    diff: str | None
    reasoning: str
    urgency: str
    status: str
    feedback: str | None
    responded_by: str | None = None
    created_at: datetime
    responded_at: datetime | None

    model_config = {"from_attributes": True}


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRequestResponse]
    total: int
    limit: int
    offset: int


# -- Helpers ------------------------------------------------------------------


def _approval_to_response(req: ApprovalRequest) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=str(req.id),
        agent_id=str(req.agent_id),
        action_category=req.action_category,
        action_type=req.action_type,
        payload=req.payload,
        diff=req.diff,
        reasoning=req.reasoning,
        urgency=req.urgency,
        status=req.status,
        feedback=req.feedback,
        responded_by=req.responded_by,
        created_at=req.created_at,
        responded_at=req.responded_at,
    )


async def _get_request_or_404(
    request_id: str,
    db: AsyncSession,
    *,
    tenant_org_id: str | None = None,
) -> ApprovalRequest:
    try:
        uid = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    stmt = select(ApprovalRequest).where(ApprovalRequest.id == uid)
    if tenant_org_id is not None:
        # Tenant-scoped: 404 (not 403) on cross-tenant lookup to avoid
        # leaking the existence of approval IDs across tenants.
        stmt = stmt.where(ApprovalRequest.org_id == tenant_org_id)

    result = await db.execute(stmt)
    approval_req = result.scalar_one_or_none()
    if approval_req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    return approval_req


async def _respond_to_request(
    request_id: str,
    decision: str,
    feedback: str | None,
    db: AsyncSession,
    responded_by: str | None = None,
    tenant_org_id: str | None = None,
) -> ApprovalRequestResponse:
    """Apply an approve/deny decision to a pending request."""
    approval_req = await _get_request_or_404(request_id, db, tenant_org_id=tenant_org_id)

    if approval_req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request already resolved with status '{approval_req.status}'",
        )

    approval_req.status = decision
    approval_req.feedback = feedback
    approval_req.responded_by = responded_by
    approval_req.responded_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(approval_req)

    response_data = _approval_to_response(approval_req)

    # Broadcast the decision to WebSocket clients in the same tenant only.
    await manager.send_approval_response(
        response_data.model_dump(mode="json"),
        org_id=approval_req.org_id,
    )

    # Notify workers waiting on Redis pub/sub for this decision.
    await notify_approval_decision(request_id, decision, feedback)

    # Emit approval event for observability (tenant-scoped).
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type=f"approval.{decision}",
            event_category="approval",
            agent_id=approval_req.agent_id,
            org_id=approval_req.org_id,
            payload={
                "action_category": approval_req.action_category,
                "action_type": approval_req.action_type,
                "feedback": feedback,
            },
        )
    except Exception:
        logger.debug("Failed to emit approval event", exc_info=True)

    return response_data


# -- Endpoints ----------------------------------------------------------------


@router.get(
    "/",
    response_model=ApprovalListResponse,
)
async def list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ApprovalListResponse:
    """List all pending approval requests for the caller's tenant.

    Tenant-scoped: only requests with ``org_id == tenant.org_id`` are returned.
    """
    base_stmt = select(ApprovalRequest).where(
        ApprovalRequest.status == "pending",
        ApprovalRequest.org_id == tenant.org_id,
    )

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(
        base_stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset)
    )
    requests = result.scalars().all()
    return ApprovalListResponse(
        items=[_approval_to_response(r) for r in requests],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_approval_request(
    body: CreateApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),  # noqa: B008
) -> ApprovalRequestResponse:
    """Create a new approval request.

    Called by workers when an agent hits a HITL interrupt. Requires Bearer
    authentication (worker shared-secret token, with ``X-Selva-Tenant-Org``
    header declaring the tenant). The persisted request's ``org_id`` is
    derived server-side from the authenticated caller -- callers cannot
    target an arbitrary tenant.

    Only the worker/service role is permitted; user-initiated approval
    creation is not a supported flow.
    """
    roles = user.get("roles", [])
    if "service" not in roles and "worker" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only worker/service callers may create approval requests",
        )

    try:
        agent_uuid = uuid.UUID(body.agent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id UUID"
        ) from exc

    org_id = user.get("org_id") or "default"
    approval_req = ApprovalRequest(
        agent_id=agent_uuid,
        action_category=body.action_category,
        action_type=body.action_type,
        payload=body.payload,
        reasoning=body.reasoning,
        urgency=body.urgency,
        diff=body.diff,
        status="pending",
        org_id=org_id,
    )
    db.add(approval_req)
    await db.flush()
    await db.refresh(approval_req)

    response_data = _approval_to_response(approval_req)

    # Broadcast the new approval request to WebSocket clients in the same
    # tenant only. Cross-tenant clients must never see another tenant's diff.
    await manager.send_approval_request(
        response_data.model_dump(mode="json"),
        org_id=org_id,
    )

    return response_data


@router.get("/{request_id}", response_model=ApprovalRequestResponse)
async def get_approval_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ApprovalRequestResponse:
    """Retrieve a single approval request by ID. Tenant-scoped.

    Used by workers for polling approval status and by tacticians for the
    detail view. Cross-tenant lookups return 404 (not 403) to avoid leaking
    the existence of approval IDs across tenants.
    """
    approval_req = await _get_request_or_404(request_id, db, tenant_org_id=tenant.org_id)
    return _approval_to_response(approval_req)


@router.post(
    "/{request_id}/approve",
    response_model=ApprovalRequestResponse,
)
async def approve_request(
    request_id: str,
    body: ApprovalAction | None = None,
    user: dict = Depends(get_current_user),  # noqa: B008
    _: None = Depends(require_non_guest),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> ApprovalRequestResponse:
    """Approve a pending request (the Tactician presses 'A').

    Idempotency: when the caller sends ``Idempotency-Key`` header, a
    successful approval response is cached for 24h scoped by (org_id,
    POST, /api/v1/approvals/{id}/approve, key). Retries with the same
    key replay the cached response. Only the success path is cached —
    a 404 (not found) or 409 (already resolved) leaves the cache empty
    so the next retry can re-evaluate.
    """
    if idem.is_replay and idem.cached is not None:
        return ApprovalRequestResponse.model_validate(idem.cached)

    feedback = body.feedback if body else None
    # _respond_to_request raises HTTPException on 404 / 409, which short-
    # circuits the caching path below — exactly the contract we want
    # (failure responses must NOT poison the idempotency cache).
    result = await _respond_to_request(
        request_id,
        "approved",
        feedback,
        db,
        responded_by=user.get("sub"),
        tenant_org_id=tenant.org_id,
    )

    # PostHog analytics
    try:
        from nexus_api.analytics import track

        track(
            str(user.get("sub", "")),
            "selva_approval_responded",
            {
                "action": "approved",
                "task_id": result.id,
            },
        )
    except Exception:
        logger.debug(
            "Failed to emit PostHog selva_approval_responded (approved) event",
            exc_info=True,
        )

    # Cache only on success. No-op when Idempotency-Key was absent.
    await idem.save(result.model_dump(mode="json"))

    return result


@router.post(
    "/{request_id}/deny",
    response_model=ApprovalRequestResponse,
)
async def deny_request(
    request_id: str,
    body: ApprovalAction | None = None,
    user: dict = Depends(get_current_user),  # noqa: B008
    _: None = Depends(require_non_guest),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> ApprovalRequestResponse:
    """Deny a pending request with optional feedback (the Tactician presses 'B').

    Idempotency: same contract as ``approve_request``. Only the success
    path is cached — a 404 (not found) or 409 (already resolved) leaves
    the cache empty so the next retry can re-evaluate.
    """
    if idem.is_replay and idem.cached is not None:
        return ApprovalRequestResponse.model_validate(idem.cached)

    feedback = body.feedback if body else None
    result = await _respond_to_request(
        request_id,
        "denied",
        feedback,
        db,
        responded_by=user.get("sub"),
        tenant_org_id=tenant.org_id,
    )

    # PostHog analytics
    try:
        from nexus_api.analytics import track

        track(
            str(user.get("sub", "")),
            "selva_approval_responded",
            {
                "action": "denied",
                "task_id": result.id,
            },
        )
    except Exception:
        logger.debug(
            "Failed to emit PostHog selva_approval_responded (denied) event",
            exc_info=True,
        )

    # Cache only on success. No-op when Idempotency-Key was absent.
    await idem.save(result.model_dump(mode="json"))

    return result


# Roles allowed to call the cross-tenant bulk-expire endpoint. Mirrors
# the ``swarms.reap-stale`` access control list: ``service`` and
# ``worker`` cover automated callers (cron jobs, ops tooling using the
# worker shared-secret token); ``platform`` and ``admin`` cover human
# operators. Any other authenticated caller (regular tactician, guest,
# demo) is rejected with 403.
_BULK_EXPIRE_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"service", "worker", "platform", "admin"}
)


class BulkExpireResponse(BaseModel):
    """Response from the bulk-expire endpoint."""

    expired: int = Field(default=0, description="Number of approvals marked expired")


@router.post("/bulk-expire", response_model=BulkExpireResponse)
async def bulk_expire(
    older_than_hours: int = Query(default=24, ge=1, le=720),  # noqa: B008
    user: dict = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> BulkExpireResponse:
    """Mark long-pending approval requests as ``expired`` (cross-tenant ops).

    Mirrors the ``swarms.reap-stale`` reaper for approvals: any approval
    that has stayed in ``pending`` for more than ``older_than_hours``
    (default 24 h) is flipped to ``expired``. Same access-control gate
    as ``reap-stale`` — only ``service`` / ``worker`` / ``platform`` /
    ``admin`` roles may invoke it.

    Audit trail: a single ``approval.bulk_expired`` summary event is
    emitted (NOT one event per row — see PR description) carrying the
    ``affected_count`` and the list of expired approval IDs. The event
    is recorded under the caller's JWT-derived ``org_id`` (or
    ``"platform"`` when the caller is the cross-tenant worker token)
    rather than each tenant's org_id, because the operation itself is a
    platform-level sweep.
    """
    from datetime import timedelta

    roles = user.get("roles", [])
    if not any(r in _BULK_EXPIRE_ALLOWED_ROLES for r in roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "bulk-expire is a platform-only endpoint; caller must hold "
                "service, worker, platform, or admin role"
            ),
        )

    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
    result = await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "pending")
        .where(ApprovalRequest.created_at < cutoff)
    )
    stale = result.scalars().all()

    expired_ids: list[str] = []
    now = datetime.now(UTC)
    for req in stale:
        req.status = "expired"
        req.responded_at = now
        req.responded_by = "system:bulk-expire"
        expired_ids.append(str(req.id))

    await db.flush()

    # Audit trail: single summary event per call, NOT one per row.
    # Late import to avoid circular import with the events router.
    # ``org_id`` is the caller's JWT-derived org (the cross-tenant
    # worker token resolves to ``"platform"`` per ``auth.py``).
    if expired_ids:
        try:
            from .events import emit_event_db

            await emit_event_db(
                db,
                event_type="approval.bulk_expired",
                event_category="approval",
                org_id=user.get("org_id") or "platform",
                payload={
                    "affected_count": len(expired_ids),
                    "ids": expired_ids,
                    "older_than_hours": older_than_hours,
                    "actor_sub": user.get("sub", "unknown"),
                },
            )
        except Exception:
            logger.debug("Failed to emit approval.bulk_expired event", exc_info=True)

    await db.flush()

    if expired_ids:
        logger.warning(
            "Bulk-expired %d stale approval(s) older than %dh (caller=%s)",
            len(expired_ids),
            older_than_hours,
            user.get("sub", "unknown"),
        )

    return BulkExpireResponse(expired=len(expired_ids))


@router.websocket("/ws")
async def approval_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),  # noqa: B008
) -> None:
    """Real-time approval event stream. Tenant-scoped.

    Authentication: the JWT (or worker shared-secret token) MUST be passed
    as the ``?token=...`` query parameter. The connection is rejected before
    any state is sent if the token is missing or invalid. Worker-token
    streams must additionally pass ``?org_id=<tenant>`` (no header
    propagation across the WS upgrade).

    Tenant scoping: the initial pending-approval batch is filtered by the
    caller's ``org_id``. Relayed events are also filtered per-tenant via
    ``broadcast_to_org`` on the server side.

    Clients connect and receive JSON messages with ``type`` set to either
    ``approval_request`` or ``approval_resolved`` as events occur.
    """
    if not token:
        await websocket.close(code=4401, reason="missing token")
        return

    settings = get_settings()
    org_id: str
    sub: str
    is_worker = False
    try:
        if (
            settings.worker_api_token
            and settings.worker_api_token != "dev-bypass"
            and token == settings.worker_api_token
        ):
            tenant_org = (websocket.query_params.get("org_id") or "").strip()
            if not tenant_org:
                await websocket.close(code=4401, reason="missing tenant scope for worker token")
                return
            org_id = tenant_org
            sub = "service:worker"
            is_worker = True
        elif settings.environment == "development" and settings.dev_auth_bypass:
            org_id = "dev-org"
            sub = "dev-user-00000000"
        else:
            payload = await verify_jwt(token, settings)
            org_id = payload.get("org_id") or "default"
            sub = payload.get("sub") or "anonymous"
    except HTTPException:
        await websocket.close(code=4401, reason="invalid token")
        return
    except Exception:
        logger.warning("Approvals WS auth failed", exc_info=True)
        await websocket.close(code=4401, reason="auth failure")
        return

    client_id = websocket.query_params.get("client_id") or f"{sub}-{uuid.uuid4()}"
    await manager.connect(websocket, client_id, org_id=org_id)

    # Send all pending approval requests for this tenant as an initial batch.
    # tenant_session(org_id) replaces bare async_session_factory() so the
    # SELECT honours RLS Phase 1.5 strict mode — see RLS_PHASE_1_5_AUDIT.md
    # §2.E + §2.H.
    try:
        async with tenant_session(org_id=org_id) as session:
            result = await session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.org_id == org_id,
                )
                .order_by(ApprovalRequest.created_at.desc())
            )
            pending = result.scalars().all()
            batch = [_approval_to_response(r).model_dump(mode="json") for r in pending]
            await websocket.send_json({"type": "approval_batch", "payload": batch})
    except Exception:
        logger.warning("Failed to send initial approval batch to client %s", client_id)

    try:
        while True:
            data = await websocket.receive_text()
            if not _ws_rate_limiter.check(client_id):
                await websocket.send_json({"type": "rate_limited"})
                continue
            if data == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            try:
                message = json.loads(data)
                # gateway:wave is a privileged broadcast from the gateway
                # daemon (which authenticates with the worker token). Reject
                # it from regular tenant clients so they cannot inject tasks
                # into other tenants' queues.
                if message.get("type") == "gateway:wave":
                    if not is_worker:
                        await websocket.send_json(
                            {"type": "error", "message": "gateway:wave requires service role"}
                        )
                        continue
                    await _handle_wave(message.get("data", {}), org_id=org_id)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        _ws_rate_limiter.remove(client_id)
        manager.disconnect(client_id)


# -- Wave-to-task pipeline ----------------------------------------------------

_EVENT_TYPE_TO_GRAPH: dict[str, str] = {
    "pr_review_requested": "coding",
    "ci_failure": "coding",
    "escalation": "research",
    "sla_breach": "crm",
}

MAX_TASKS_PER_WAVE = 10


async def _handle_wave(wave_data: dict[str, Any], *, org_id: str = "default") -> None:
    """Convert a gateway wave into SwarmTasks and enqueue them.

    Tasks are scoped to ``org_id`` (resolved from the gateway's authenticated
    WS connection). The wave broadcast is delivered only to clients in the
    same tenant.
    """
    events = wave_data.get("events", [])
    source = wave_data.get("source", "unknown")
    created = 0

    settings = get_settings()

    # _handle_wave INSERTs new SwarmTask rows on behalf of the wave's
    # tenant. tenant_session(org_id) ensures the INSERT passes RLS
    # Phase 1.5 strict-mode policy (which requires
    # ``app.current_org_id == swarm_tasks.org_id``).
    async with tenant_session(org_id=org_id) as session:
        pool = get_redis_pool(url=settings.redis_url)
        for event in events[:MAX_TASKS_PER_WAVE]:
            event_type = event.get("type", "")
            graph_type = _EVENT_TYPE_TO_GRAPH.get(event_type, "research")
            payload = event.get("payload", {})

            task = SwarmTask(
                description=f"[{source}] {event_type}: {payload.get('title', 'N/A')}",
                graph_type=graph_type,
                payload=payload,
                status="pending",
                org_id=org_id,
            )
            session.add(task)
            await session.flush()
            await session.refresh(task)

            task_msg = json.dumps(
                {
                    "task_id": str(task.id),
                    "graph_type": graph_type,
                    "description": task.description,
                    "payload": payload,
                    "assigned_agent_ids": [],
                    "org_id": org_id,
                }
            )
            try:
                await pool.execute_with_retry("xadd", "autoswarm:task-stream", {"data": task_msg})
            except Exception:
                _wave_logger.warning("Redis unavailable for wave task %s", task.id)
            created += 1

        await session.commit()

    if created > 0:
        await manager.broadcast_to_org(
            org_id,
            {
                "type": "wave_incoming",
                "source": source,
                "task_count": created,
            },
        )
        _wave_logger.info("Wave from %s: created %d tasks (org=%s)", source, created, org_id)
