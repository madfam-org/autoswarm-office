"""Calendar tools: create and list events via calendar adapters."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.calendar_tools")

# Mexican federal holidays per Articulo 74 LFT
# Note: Some holidays are observed on the nearest Monday (movable).
# This mapping uses the canonical dates; the tool handles movable holidays.
MEXICAN_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "Anio Nuevo",
    (2, 5): "Dia de la Constitucion",  # First Monday of February
    (3, 21): "Natalicio de Benito Juarez",  # Third Monday of March
    (5, 1): "Dia del Trabajo",
    (9, 16): "Dia de la Independencia",
    (11, 20): "Dia de la Revolucion",  # Third Monday of November
    (12, 25): "Navidad",
}


class CreateCalendarEventTool(BaseTool):
    name = "create_calendar_event"
    description = (
        "Create a calendar event with title, start/end times, description, and attendees. "
        "Uses the selva_calendar Google adapter when available."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in ISO 8601 format (e.g. 2026-04-15T09:00:00Z)",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in ISO 8601 format",
                },
                "description": {
                    "type": "string",
                    "description": "Event description",
                    "default": "",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                    "default": [],
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (defaults to primary)",
                    "default": "primary",
                },
            },
            "required": ["title", "start_time", "end_time"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        # NOTE: ``GoogleCalendarAdapter`` does not currently expose a
        # ``create_event`` method (the adapter is read-only — list_events +
        # check_busy). The previous implementation called the missing method
        # and silently swallowed the AttributeError into a generic error
        # response, making the tool look like it was a config issue. Surface
        # the truth instead so callers know to track adapter write support.
        return ToolResult(
            success=False,
            error=(
                "create_calendar_event is not implemented: the Google adapter "
                "is read-only. Track addition of write support before re-enabling."
            ),
            data={
                "title": kwargs.get("title", ""),
                "start_time": kwargs.get("start_time", ""),
                "end_time": kwargs.get("end_time", ""),
            },
        )


class ListCalendarEventsTool(BaseTool):
    name = "list_calendar_events"
    description = (
        "List calendar events for a given date. "
        "Uses the selva_calendar Google adapter when available."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (defaults to primary)",
                    "default": "primary",
                },
            },
            "required": ["date"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        date_str = kwargs.get("date", "")
        calendar_id = kwargs.get("calendar_id", "primary")

        access_token = (
            kwargs.get("access_token")
            or os.environ.get("GOOGLE_CALENDAR_ACCESS_TOKEN")
            or ""
        )
        if not access_token:
            return ToolResult(
                success=False,
                error=(
                    "Calendar not configured: pass ``access_token`` or set "
                    "GOOGLE_CALENDAR_ACCESS_TOKEN env var."
                ),
            )

        try:
            from selva_calendar.google import GoogleCalendarAdapter

            try:
                day = date.fromisoformat(date_str)
            except ValueError:
                return ToolResult(
                    success=False,
                    error=f"Invalid date format: '{date_str}'. Use YYYY-MM-DD.",
                )

            time_min = datetime.combine(day, datetime.min.time())
            time_max = datetime.combine(day, datetime.max.time())

            adapter = GoogleCalendarAdapter(access_token=access_token)
            try:
                events = await adapter.list_events(
                    time_min=time_min,
                    time_max=time_max,
                    calendar_id=calendar_id,
                )
            finally:
                await adapter.close()

            summary = "\n".join(
                f"- {e.title} ({e.start.isoformat()})" for e in events
            )
            return ToolResult(
                output=summary or f"No events on {date_str}",
                data={
                    "date": date_str,
                    "events": [e.model_dump(mode="json") for e in events],
                    "count": len(events),
                },
            )
        except ImportError:
            logger.warning("selva_calendar not available")
            return ToolResult(
                success=False,
                error="Calendar not configured. Install selva_calendar package.",
            )
        except Exception as exc:
            logger.error("list_calendar_events failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


def _is_mexican_holiday(d: date) -> tuple[bool, str]:
    """Check if a date is a Mexican federal holiday.

    Returns (is_holiday, holiday_name).
    """
    canonical = MEXICAN_HOLIDAYS.get((d.month, d.day))
    if canonical:
        return True, canonical
    return False, ""


def _is_business_day(d: date) -> bool:
    """Check if a date is a Mexican business day (not weekend, not holiday)."""
    if d.weekday() >= 5:
        return False
    is_hol, _ = _is_mexican_holiday(d)
    return not is_hol


def _next_business_day(d: date) -> date:
    """Find the next Mexican business day after the given date."""
    candidate = d + timedelta(days=1)
    while not _is_business_day(candidate):
        candidate += timedelta(days=1)
    return candidate


class MexicanBusinessCalendarTool(BaseTool):
    name = "mexican_business_calendar"
    description = "Check Mexican business days, holidays (Art. 74 LFT), and CFDI deadlines"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "is_business_day",
                        "next_business_day",
                        "holidays_in_month",
                        "cfdi_deadline",
                    ],
                    "description": "Action to perform",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (defaults to today)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs.get("action", "")
        date_str: str = kwargs.get("date", "")

        # Parse date or use today
        if date_str:
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                return ToolResult(
                    success=False,
                    error=f"Invalid date format: '{date_str}'. Use YYYY-MM-DD.",
                )
        else:
            d = date.today()

        if action == "is_business_day":
            is_weekend = d.weekday() >= 5
            is_hol, hol_name = _is_mexican_holiday(d)
            is_biz = not is_weekend and not is_hol
            data: dict[str, Any] = {
                "is_business_day": is_biz,
                "date": d.isoformat(),
                "is_weekend": is_weekend,
                "is_holiday": is_hol,
            }
            if hol_name:
                data["holiday_name"] = hol_name
            return ToolResult(success=True, data=data)

        elif action == "next_business_day":
            nbd = _next_business_day(d)
            return ToolResult(
                success=True,
                data={"next_business_day": nbd.isoformat(), "from_date": d.isoformat()},
            )

        elif action == "holidays_in_month":
            holidays: list[dict[str, Any]] = [
                {"day": day, "name": name}
                for (m, day), name in sorted(MEXICAN_HOLIDAYS.items())
                if m == d.month
            ]
            return ToolResult(
                success=True,
                data={"month": d.month, "year": d.year, "holidays": holidays},
            )

        elif action == "cfdi_deadline":
            # ISR provisional declaration deadline: 17th of each month
            deadline = date(d.year, d.month, 17)
            # If the 17th falls on a weekend, move to the next business day
            if not _is_business_day(deadline):
                while not _is_business_day(deadline):
                    deadline += timedelta(days=1)
            return ToolResult(
                success=True,
                data={
                    "cfdi_deadline": deadline.isoformat(),
                    "type": "ISR provisional",
                    "month": d.month,
                    "year": d.year,
                },
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")
