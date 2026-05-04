"""Calendar Integration REST API: connect, list events, check status."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_calendar import (
    CalendarEvent,
    CalendarProvider,
    GoogleCalendarAdapter,
    MicrosoftCalendarAdapter,
)

from ..auth import get_current_user, require_non_guest
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import CalendarConnection
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calendar"], dependencies=[Depends(get_current_user)])  # noqa: B008


# -- Request / Response schemas ------------------------------------------------


class ConnectCalendarRequest(BaseModel):
    """Request body for connecting a calendar provider."""

    provider: CalendarProvider
    access_token: str = Field(..., min_length=1)
    refresh_token: str | None = None


class CalendarStatusResponse(BaseModel):
    """Response for calendar connection status."""

    connected: bool
    provider: str | None = None
    connected_at: str | None = None


class CalendarEventResponse(BaseModel):
    """Public representation of a calendar event."""

    id: str
    title: str
    start: str
    end: str
    is_all_day: bool
    meeting_url: str | None
    organizer: str
    attendees: list[str]
    provider: str


class CalendarEventsListResponse(BaseModel):
    """List of calendar events."""

    events: list[CalendarEventResponse]
    is_busy: bool


class ConnectResponse(BaseModel):
    """Response after connecting a calendar."""

    connected: bool = True
    provider: str


class DisconnectResponse(BaseModel):
    """Response after disconnecting a calendar."""

    disconnected: bool = True


# -- Helpers -------------------------------------------------------------------


def _event_to_response(event: CalendarEvent) -> CalendarEventResponse:
    """Convert a CalendarEvent to the API response model."""
    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        start=event.start.isoformat(),
        end=event.end.isoformat(),
        is_all_day=event.is_all_day,
        meeting_url=event.meeting_url,
        organizer=event.organizer,
        attendees=event.attendees,
        provider=event.provider.value,
    )


async def _get_user_connection(
    user_id: str,
    org_id: str,
    db: AsyncSession,
) -> CalendarConnection | None:
    """Fetch the calendar connection for a user, if any."""
    stmt = (
        select(CalendarConnection)
        .where(CalendarConnection.user_id == user_id)
        .where(CalendarConnection.org_id == org_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _fetch_events(
    connection: CalendarConnection,
    time_min: datetime,
    time_max: datetime,
) -> list[CalendarEvent]:
    """Fetch events from the appropriate calendar provider."""
    # Both adapters expose the same `list_events` / `close` surface, but
    # mypy infers `adapter` as `GoogleCalendarAdapter` from the first
    # branch alone.  Annotate the union so the Microsoft branch type-checks.
    adapter: GoogleCalendarAdapter | MicrosoftCalendarAdapter
    if connection.provider == CalendarProvider.GOOGLE.value:
        adapter = GoogleCalendarAdapter(connection.access_token)
    elif connection.provider == CalendarProvider.MICROSOFT.value:
        adapter = MicrosoftCalendarAdapter(connection.access_token)
    else:
        raise ValueError(f"Unknown provider: {connection.provider}")

    try:
        return await adapter.list_events(time_min, time_max)
    finally:
        await adapter.close()


# -- Endpoints -----------------------------------------------------------------


@router.get("/events", response_model=CalendarEventsListResponse)
async def list_events(
    hours: int = 8,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> CalendarEventsListResponse:
    """List upcoming calendar events for the current user.

    Returns events in the next *hours* hours (default 8) and a ``is_busy``
    flag indicating whether the user is currently in a meeting.
    """
    user_id = user.get("sub", "unknown")
    connection = await _get_user_connection(user_id, tenant.org_id, db)

    if not connection:
        return CalendarEventsListResponse(events=[], is_busy=False)

    now = datetime.now(UTC)
    time_max = now + timedelta(hours=hours)

    try:
        events = await _fetch_events(connection, now, time_max)
    except Exception:
        logger.warning("Failed to fetch calendar events for user %s", user_id, exc_info=True)
        return CalendarEventsListResponse(events=[], is_busy=False)

    # Determine if user is currently busy
    is_busy = any(event.start <= now <= event.end and not event.is_all_day for event in events)

    return CalendarEventsListResponse(
        events=[_event_to_response(e) for e in events],
        is_busy=is_busy,
    )


@router.post(
    "/connect",
    response_model=ConnectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def connect_calendar(
    body: ConnectCalendarRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> ConnectResponse:
    """Store a calendar connection for the current user.

    If a connection already exists it is updated with the new tokens.

    Idempotency: replay-safe via the ``Idempotency-Key`` header. A retry
    after a network blip should NOT re-store the same OAuth tokens twice
    (which would emit a duplicate ``calendar.connected`` audit event and
    potentially trigger downstream re-syncs). The cached response is
    returned without touching the DB on replay.
    """
    if idem.is_replay and idem.cached is not None:
        return ConnectResponse.model_validate(idem.cached)

    user_id = user.get("sub", "unknown")
    existing = await _get_user_connection(user_id, tenant.org_id, db)

    if existing:
        existing.provider = body.provider.value
        existing.access_token = body.access_token
        existing.refresh_token = body.refresh_token
        await db.flush()
    else:
        connection = CalendarConnection(
            user_id=user_id,
            provider=body.provider.value,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
            org_id=tenant.org_id,
        )
        db.add(connection)
        await db.flush()

    # Audit trail: emit an event so the office UI activity feed surfaces
    # calendar connections. Late import to avoid circular import with the
    # events router. Fire-and-forget — errors swallowed inside
    # ``emit_event_db`` so the connection always succeeds even if the
    # audit pipeline is degraded.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="calendar.connected",
        event_category="calendar",
        org_id=tenant.org_id,
        payload={
            "provider": body.provider.value,
            "user_sub": user_id,
        },
    )

    response = ConnectResponse(provider=body.provider.value)
    await idem.save(response.model_dump(mode="json"))
    return response


@router.delete(
    "/disconnect",
    response_model=DisconnectResponse,
    dependencies=[Depends(require_non_guest)],
)
async def disconnect_calendar(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> DisconnectResponse:
    """Remove the current user's calendar connection."""
    user_id = user.get("sub", "unknown")
    connection = await _get_user_connection(user_id, tenant.org_id, db)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No calendar connection found",
        )

    provider_value = connection.provider
    await db.delete(connection)
    await db.flush()

    # Audit trail: emit an event so the office UI activity feed surfaces
    # calendar disconnections. Late import to avoid circular import with
    # the events router. Fire-and-forget — errors swallowed inside
    # ``emit_event_db``.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="calendar.disconnected",
        event_category="calendar",
        org_id=tenant.org_id,
        payload={
            "provider": provider_value,
            "user_sub": user_id,
        },
    )

    return DisconnectResponse()


@router.get("/status", response_model=CalendarStatusResponse)
async def calendar_status(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> CalendarStatusResponse:
    """Check the current user's calendar connection status."""
    user_id = user.get("sub", "unknown")
    connection = await _get_user_connection(user_id, tenant.org_id, db)

    if not connection:
        return CalendarStatusResponse(connected=False)

    return CalendarStatusResponse(
        connected=True,
        provider=connection.provider,
        connected_at=connection.connected_at.isoformat(),
    )
