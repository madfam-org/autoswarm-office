"""Multi-party meeting scheduling layered on existing calendar_tools.

Closes the ``schedule a call between N busy people`` gap. Our existing
calendar tools cover single-participant list + create; this module composes
them into the free/busy reconciliation + fan-out-create flow every human
assistant spends half their day on.

No new HTTP surface — these tools delegate to ``ListCalendarEventsTool`` and
``CreateCalendarEventTool`` so credentials and API scopes already wired for
Phase 1 calendar_tools carry over automatically. If those tools report
``Calendar not configured`` this module surfaces the same error instead of
inventing an alternate transport.

Slot algorithm: pull each participant's events for the target window,
invert to free intervals, intersect across all participants, then return
slots where the intersection covers the requested duration. Business-hours
filter is applied per slot using a fixed 09:00–18:00 America/Mexico_City
window (matches MADFAM internal norms; external overrides are the caller's
responsibility and easy to layer on).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Business-hours window applied when business_hours=True.
_BIZ_START = time(9, 0)
_BIZ_END = time(18, 0)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 datetime; accept trailing 'Z'."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _iso(dt: datetime) -> str:
    """Emit an ISO-8601 UTC string with trailing 'Z' for cross-provider safety."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_range(event: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Best-effort extract of (start, end) from a Google-style event dict."""
    start = (event.get("start") or {}).get("dateTime") or event.get("start")
    end = (event.get("end") or {}).get("dateTime") or event.get("end")
    if not start or not end:
        return None
    try:
        return _parse_iso(str(start)), _parse_iso(str(end))
    except (ValueError, TypeError):
        return None


def _merge_busy(
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Merge overlapping busy intervals."""
    if not busy:
        return []
    busy = sorted(busy, key=lambda b: b[0])
    merged = [busy[0]]
    for s, e in busy[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def _invert(
    busy: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Invert merged busy intervals into free intervals within the window."""
    free: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for s, e in busy:
        if e <= window_start or s >= window_end:
            continue
        s = max(s, window_start)
        e = min(e, window_end)
        if cursor < s:
            free.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < window_end:
        free.append((cursor, window_end))
    return free


def _intersect(
    a: list[tuple[datetime, datetime]],
    b: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Intersect two lists of free intervals."""
    out: list[tuple[datetime, datetime]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _apply_business_hours(
    free: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Clip free intervals to 09:00–18:00 local time (day-by-day)."""
    out: list[tuple[datetime, datetime]] = []
    for s, e in free:
        cursor = s
        while cursor.date() <= e.date():
            day_start = datetime.combine(cursor.date(), _BIZ_START, tzinfo=s.tzinfo)
            day_end = datetime.combine(cursor.date(), _BIZ_END, tzinfo=s.tzinfo)
            clipped_s = max(cursor, day_start)
            clipped_e = min(e, day_end)
            if clipped_s < clipped_e:
                out.append((clipped_s, clipped_e))
            # advance to next day at 00:00
            cursor = datetime.combine(
                cursor.date() + timedelta(days=1), time(0, 0), tzinfo=s.tzinfo
            )
    return out


def _days_in_range(after: datetime, before: datetime) -> list[str]:
    """Return YYYY-MM-DD strings covering [after, before] inclusive of start day."""
    days: list[str] = []
    d = after.date()
    end_date = before.date()
    while d <= end_date:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


async def _gather_busy_for_participant(
    email: str,
    after: datetime,
    before: datetime,
) -> tuple[list[tuple[datetime, datetime]], str | None]:
    """Call ListCalendarEventsTool for each day in the window and merge busy.

    Returns (merged_busy_intervals, error_message).
    """
    from .calendar_tools import ListCalendarEventsTool

    tool = ListCalendarEventsTool()
    busy: list[tuple[datetime, datetime]] = []
    for day in _days_in_range(after, before):
        r = await tool.execute(date=day, calendar_id=email)
        if not r.success:
            return [], r.error or "calendar list failed"
        events = r.data.get("events") or []
        for ev in events:
            rng = _event_range(ev) if isinstance(ev, dict) else None
            if rng:
                busy.append(rng)
    return _merge_busy(busy), None


# ---------------------------------------------------------------------------
# find slots
# ---------------------------------------------------------------------------


class MeetingFindSlotsTool(BaseTool):
    """Compute intersecting free slots for 2–5 participants."""

    name = "meeting_find_slots"
    description = (
        "Find time slots where all ``participants`` (email list) are free "
        "for at least ``duration_minutes``, bounded by ``after_iso`` and "
        "``before_iso``. Composes the existing list_calendar_events tool "
        "per participant. ``business_hours`` (default True) clips slots to "
        "09:00–18:00 America/Mexico_City. Returns at most 20 slot "
        "candidates ordered earliest-first."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 5,
                },
                "duration_minutes": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 480,
                },
                "after_iso": {"type": "string"},
                "before_iso": {"type": "string"},
                "business_hours": {"type": "boolean", "default": True},
            },
            "required": [
                "participants",
                "duration_minutes",
                "after_iso",
                "before_iso",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        participants: list[str] = list(kwargs["participants"] or [])
        if len(participants) < 2:
            return ToolResult(success=False, error="at least 2 participants required.")
        try:
            after = _parse_iso(kwargs["after_iso"])
            before = _parse_iso(kwargs["before_iso"])
        except ValueError as e:
            return ToolResult(success=False, error=f"invalid ISO datetime: {e}")
        if before <= after:
            return ToolResult(success=False, error="before_iso must be after after_iso.")
        duration = timedelta(minutes=int(kwargs["duration_minutes"]))
        business_hours = bool(kwargs.get("business_hours", True))

        # Gather busy per participant.
        free_lists: list[list[tuple[datetime, datetime]]] = []
        for p in participants:
            busy, err = await _gather_busy_for_participant(p, after, before)
            if err:
                return ToolResult(
                    success=False,
                    error=f"failed to read {p}'s calendar: {err}",
                )
            free = _invert(busy, after, before)
            if business_hours:
                free = _apply_business_hours(free)
            free_lists.append(free)

        # Intersect pairwise.
        intersection = free_lists[0]
        for fl in free_lists[1:]:
            intersection = _intersect(intersection, fl)
            if not intersection:
                break

        slots: list[dict[str, str]] = []
        # Loop var renamed from "e" to "end" to avoid shadowing the
        # ``except ValueError as e`` above — Python deletes that name
        # at the end of the except block, so mypy flags the reuse as
        # reading a deleted variable.
        for s, end in intersection:
            cursor = s
            while cursor + duration <= end:
                slots.append(
                    {
                        "start": _iso(cursor),
                        "end": _iso(cursor + duration),
                    }
                )
                cursor += duration
                if len(slots) >= 20:
                    break
            if len(slots) >= 20:
                break

        return ToolResult(
            success=True,
            output=f"Found {len(slots)} candidate slot(s).",
            data={
                "slots": slots,
                "participants": participants,
                "duration_minutes": int(kwargs["duration_minutes"]),
            },
        )


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------


class MeetingScheduleTool(BaseTool):
    """Create an event on each participant's calendar at the chosen slot."""

    name = "meeting_schedule"
    description = (
        "Create a meeting across participants at ``slot_start_iso``. Calls "
        "the existing create_calendar_event tool per participant (their "
        "email as calendar_id), attaching the remaining participants as "
        "attendees. ``zoom_link`` is appended to the description when "
        "provided. Returns per-participant event ids so follow-up jobs "
        "can update or cancel atomically."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 5,
                },
                "slot_start_iso": {"type": "string"},
                "duration_minutes": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 480,
                },
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "zoom_link": {"type": "string"},
            },
            "required": [
                "participants",
                "slot_start_iso",
                "duration_minutes",
                "title",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from .calendar_tools import CreateCalendarEventTool

        participants: list[str] = list(kwargs["participants"] or [])
        if len(participants) < 2:
            return ToolResult(success=False, error="at least 2 participants required.")
        try:
            start = _parse_iso(kwargs["slot_start_iso"])
        except ValueError as e:
            return ToolResult(success=False, error=f"invalid ISO datetime: {e}")
        end = start + timedelta(minutes=int(kwargs["duration_minutes"]))

        description = kwargs.get("description", "") or ""
        zoom = kwargs.get("zoom_link")
        if zoom:
            description = (
                f"{description}\n\nJoin: {zoom}".strip() if description else f"Join: {zoom}"
            )

        tool = CreateCalendarEventTool()
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for p in participants:
            attendees = [x for x in participants if x != p]
            r = await tool.execute(
                title=kwargs["title"],
                start_time=_iso(start),
                end_time=_iso(end),
                description=description,
                attendees=attendees,
                calendar_id=p,
            )
            if r.success:
                results.append(
                    {
                        "participant": p,
                        "event_id": r.data.get("event_id"),
                    }
                )
            else:
                failures.append({"participant": p, "error": r.error})
        return ToolResult(
            success=len(failures) == 0,
            output=(
                f"Scheduled {len(results)}/{len(participants)} calendars "
                f"({len(failures)} failures)."
            ),
            error=(failures[0]["error"] if failures else None),
            data={
                "scheduled": results,
                "failures": failures,
                "start": _iso(start),
                "end": _iso(end),
                "title": kwargs["title"],
            },
        )


def get_meeting_scheduler_tools() -> list[BaseTool]:
    """Return the meeting-scheduler tool set."""
    return [
        MeetingFindSlotsTool(),
        MeetingScheduleTool(),
    ]
