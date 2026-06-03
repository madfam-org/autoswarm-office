"""Task event observability endpoints -- REST + WebSocket stream."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, verify_jwt
from ..config import get_settings
from ..database import get_db, tenant_session
from ..models import TaskEvent
from ..tenant import TenantContext, get_tenant
from ..ws import MessageRateLimiter, event_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

# -- Module-internal constants -------------------------------------------------
# How many recent TaskEvents are sent in the initial batch when a client
# connects to /events/ws. Larger values delay first paint of the OpsFeed
# panel; smaller values force the UI to make a follow-up REST call.
# Tightly coupled to the UI's pagination, so kept module-local rather
# than promoted to Settings.
_EVENTS_INITIAL_BATCH_SIZE: int = 50

# WebSocket rate limit values come from Settings
# (events_ws_rate_limit / events_ws_rate_window_seconds) so ops can
# tune per-client flood guards without a code change.
_settings = get_settings()
_ws_rate_limiter = MessageRateLimiter(
    max_messages=_settings.events_ws_rate_limit,
    window_seconds=_settings.events_ws_rate_window_seconds,
)


# -- Request / Response schemas -----------------------------------------------


class CreateEventRequest(BaseModel):
    event_type: str = Field(..., max_length=50)
    event_category: str = Field(..., max_length=50)
    task_id: str | None = None
    agent_id: str | None = None
    node_id: str | None = None
    graph_type: str | None = None
    payload: dict[str, Any] | None = None
    duration_ms: int | None = None
    provider: str | None = None
    model: str | None = None
    token_count: int | None = None
    error_message: str | None = None
    request_id: str | None = None
    # NOTE: org_id is NOT accepted from the request body. It is derived
    # server-side from the authenticated caller (JWT claim or worker token
    # X-Selva-Tenant-Org header) so a tenant cannot write events into another
    # tenant's observability stream.


class TaskEventResponse(BaseModel):
    id: str
    task_id: str | None
    agent_id: str | None
    event_type: str
    event_category: str
    node_id: str | None
    graph_type: str | None
    payload: dict[str, Any] | None
    duration_ms: int | None
    provider: str | None
    model: str | None
    token_count: int | None
    error_message: str | None
    request_id: str | None
    org_id: str
    created_at: str

    model_config = {"from_attributes": True}


class TimelineResponse(BaseModel):
    task_id: str
    events: list[TaskEventResponse]
    total_duration_ms: int | None
    total_tokens: int | None


# -- Helpers ------------------------------------------------------------------


def _event_to_response(ev: TaskEvent) -> TaskEventResponse:
    return TaskEventResponse(
        id=str(ev.id),
        task_id=str(ev.task_id) if ev.task_id else None,
        agent_id=str(ev.agent_id) if ev.agent_id else None,
        event_type=ev.event_type,
        event_category=ev.event_category,
        node_id=ev.node_id,
        graph_type=ev.graph_type,
        payload=ev.payload,
        duration_ms=ev.duration_ms,
        provider=ev.provider,
        model=ev.model,
        token_count=ev.token_count,
        error_message=ev.error_message,
        request_id=ev.request_id,
        org_id=ev.org_id,
        created_at=ev.created_at.isoformat(),
    )


def _safe_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# -- Endpoints ----------------------------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: CreateEventRequest,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict[str, str]:
    """Create a new task event.

    Requires Bearer token authentication (worker token or JWT). The event's
    ``org_id`` is derived server-side from the authenticated caller -- callers
    cannot specify a target ``org_id`` in the body. Workers declare their
    tenant via the ``X-Selva-Tenant-Org`` header (resolved by ``auth.py``).

    Uses ``tenant_session(org_id)`` instead of ``get_db`` so RLS sees the
    worker/JWT tenant before insert (``get_db`` would run before ``user``).

    Broadcasts only to WebSocket clients in the same tenant.
    """
    org_id = user.get("org_id") or "default"
    async with tenant_session(org_id=org_id) as db:
        event = TaskEvent(
            task_id=_safe_uuid(body.task_id),
            agent_id=_safe_uuid(body.agent_id),
            event_type=body.event_type,
            event_category=body.event_category,
            node_id=body.node_id,
            graph_type=body.graph_type,
            payload=body.payload,
            duration_ms=body.duration_ms,
            provider=body.provider,
            model=body.model,
            token_count=body.token_count,
            error_message=body.error_message,
            request_id=body.request_id,
            org_id=org_id,
        )
        db.add(event)
        await db.flush()
        await db.refresh(event)
        response = _event_to_response(event)

    # Broadcast to WebSocket clients in the same tenant only.
    await event_manager.broadcast_to_org(
        org_id, {"type": "task_event", "payload": response.model_dump()}
    )

    return {"id": str(event.id)}


@router.get(
    "/",
    response_model=list[TaskEventResponse],
)
async def list_events(
    task_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    event_category: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[TaskEventResponse]:
    """List events with optional filters, newest first. Tenant-scoped."""
    query = (
        select(TaskEvent)
        .where(TaskEvent.org_id == tenant.org_id)
        .order_by(TaskEvent.created_at.desc())
    )

    if task_id:
        uid = _safe_uuid(task_id)
        if uid:
            query = query.where(TaskEvent.task_id == uid)
    if agent_id:
        uid = _safe_uuid(agent_id)
        if uid:
            query = query.where(TaskEvent.agent_id == uid)
    if event_type:
        query = query.where(TaskEvent.event_type == event_type)
    if event_category:
        query = query.where(TaskEvent.event_category == event_category)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(TaskEvent.created_at >= since_dt)
        except ValueError:
            pass
    if until:
        try:
            until_dt = datetime.fromisoformat(until)
            query = query.where(TaskEvent.created_at <= until_dt)
        except ValueError:
            pass

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()
    return [_event_to_response(e) for e in events]


@router.get(
    "/tasks/{task_id}/timeline",
    response_model=TimelineResponse,
)
async def get_task_timeline(
    task_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> TimelineResponse:
    """Full execution timeline for a single task. Tenant-scoped.

    Returns only events with ``org_id == tenant.org_id``. A task that
    belongs to another tenant (or does not exist at all) yields an empty
    timeline rather than 404 -- this matches the response shape callers
    expect for newly-dispatched tasks before any events have landed,
    while still preventing cross-tenant data leak.
    """
    uid = _safe_uuid(task_id)
    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(TaskEvent)
        .where(
            TaskEvent.task_id == uid,
            TaskEvent.org_id == tenant.org_id,
        )
        .order_by(TaskEvent.created_at.asc())
    )
    events = result.scalars().all()

    # Aggregate duration and tokens (also tenant-scoped, defense in depth)
    agg = await db.execute(
        select(
            func.sum(TaskEvent.duration_ms),
            func.sum(TaskEvent.token_count),
        ).where(
            TaskEvent.task_id == uid,
            TaskEvent.org_id == tenant.org_id,
        )
    )
    row = agg.one()
    total_duration = row[0]
    total_tokens = row[1]

    return TimelineResponse(
        task_id=task_id,
        events=[_event_to_response(e) for e in events],
        total_duration_ms=total_duration,
        total_tokens=total_tokens,
    )


@router.websocket("/ws")
async def events_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),  # noqa: B008
) -> None:
    """Real-time event stream over WebSocket. Tenant-scoped.

    Authentication: the JWT (or worker shared-secret token) MUST be passed
    as the ``?token=...`` query parameter. The connection is rejected before
    any state is sent if the token is missing or invalid.

    Tenant scoping: the initial 50-event batch is filtered by the caller's
    ``org_id`` (from JWT). Relayed events are also filtered per-tenant via
    ``broadcast_to_org`` on the server side.

    Worker-token streams must additionally pass ``?org_id=<tenant>`` to
    declare the tenant scope (the WS upgrade does not carry our custom
    ``X-Selva-Tenant-Org`` header).

    On connect: sends last ``_EVENTS_INITIAL_BATCH_SIZE`` events for the
    tenant as ``event_batch``. Then relays new events from the
    ``selva:events`` Redis channel.
    """
    if not token:
        await websocket.close(code=4401, reason="missing token")
        return

    settings = get_settings()
    org_id: str
    sub: str
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
        logger.warning("Events WS auth failed", exc_info=True)
        await websocket.close(code=4401, reason="auth failure")
        return

    client_id = websocket.query_params.get("client_id") or f"{sub}-{uuid.uuid4()}"
    await event_manager.connect(websocket, client_id, org_id=org_id)

    # Send initial batch (tenant-scoped).
    # Use tenant_session(org_id) instead of bare async_session_factory() so
    # the SELECT honours RLS Phase 1.5 strict mode. Without it, the WS
    # auth path resolves org_id from ?token= but the session var stays
    # unset, and after tightening the SELECT would return zero rows
    # (NULL session var ≠ org_id, no escape hatch). See
    # docs/RLS_PHASE_1_5_AUDIT.md §2.E + §2.H.
    try:
        async with tenant_session(org_id=org_id) as session:
            result = await session.execute(
                select(TaskEvent)
                .where(TaskEvent.org_id == org_id)
                .order_by(TaskEvent.created_at.desc())
                .limit(_EVENTS_INITIAL_BATCH_SIZE)
            )
            recent = result.scalars().all()
            batch = [_event_to_response(e).model_dump() for e in reversed(recent)]
            await websocket.send_json({"type": "event_batch", "payload": batch})
    except Exception:
        logger.warning("Failed to send initial event batch to client %s", client_id)

    try:
        while True:
            data = await websocket.receive_text()
            if not _ws_rate_limiter.check(client_id):
                await websocket.send_json({"type": "rate_limited"})
                continue
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _ws_rate_limiter.remove(client_id)
        event_manager.disconnect(client_id)


# -- Direct DB event emission for server-side use ----------------------------


async def emit_event_db(
    db: AsyncSession,
    *,
    event_type: str,
    event_category: str,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    org_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Insert a TaskEvent directly (for server-side emission without HTTP).

    Fire-and-forget: exceptions are logged but never raised.

    Callers SHOULD pass ``org_id`` so the event is broadcast to the right
    tenant's WS clients. When omitted the column default (``"default"``) is
    used and the broadcast is org-scoped to "default".
    """
    try:
        if org_id is not None:
            kwargs["org_id"] = org_id
        event = TaskEvent(
            task_id=task_id,
            agent_id=agent_id,
            event_type=event_type,
            event_category=event_category,
            **kwargs,
        )
        db.add(event)
        await db.flush()
        await db.refresh(event)

        response = _event_to_response(event)
        await event_manager.broadcast_to_org(
            event.org_id, {"type": "task_event", "payload": response.model_dump()}
        )
    except Exception:
        logger.warning("Failed to emit DB event %s", event_type, exc_info=True)
