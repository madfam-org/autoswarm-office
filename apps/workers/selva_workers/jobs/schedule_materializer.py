"""Materialize ``schedules`` cron rows into ``scheduled_actions`` due rows.

Bridges the Gap-3 schedules CRUD table (user-defined recurring cron) with
the Phase 2.5 ``scheduled_actions`` queue drained by
``social_post_executor.run()``.

Runs once per minute from the worker main loop — same cadence pattern as
``social_post_executor.periodic_loop``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MATERIALIZER_INTERVAL_SECONDS = 60


def _get_database_url() -> str | None:
    try:
        from selva_workers.config import get_settings

        settings = get_settings()
        if settings.database_url:
            return settings.database_url
    except Exception:
        logger.debug("get_settings() failed in schedule materializer", exc_info=True)
    return os.environ.get("DATABASE_URL")


def _to_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg", "postgresql")


def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        token = part.strip()
        if not token:
            continue
        if token == "*":
            return set(range(min_val, max_val + 1))
        if token.startswith("*/"):
            step = int(token[2:])
            values.update(range(min_val, max_val + 1, step))
            continue
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start, end = int(start_s), int(end_s)
            values.update(range(start, end + 1))
            continue
        values.add(int(token))
    return values


def _cron_dow_values(field: str) -> set[int]:
    """Return Python weekday() values (Mon=0 … Sun=6) matching cron dow field."""
    raw = _parse_cron_field(field, 0, 7)

    def _to_python(d: int) -> int:
        if d in {0, 7}:
            return 6  # Sunday
        return d - 1

    return {_to_python(d) for d in raw}


def cron_matches(dt: datetime, cron_expr: str) -> bool:
    """Return True when ``dt`` (minute resolution) matches a 5-field cron."""
    parts = cron_expr.split()
    if len(parts) != 5:
        return False
    minute_f, hour_f, dom_f, month_f, dow_f = parts
    return (
        dt.minute in _parse_cron_field(minute_f, 0, 59)
        and dt.hour in _parse_cron_field(hour_f, 0, 23)
        and dt.day in _parse_cron_field(dom_f, 1, 31)
        and dt.month in _parse_cron_field(month_f, 1, 12)
        and dt.weekday() in _cron_dow_values(dow_f)
    )


def is_schedule_due(cron_expr: str, last_run_at: datetime | None, now: datetime) -> bool:
    """True when cron fires in the current minute and we have not run this minute."""
    minute_bucket = now.replace(second=0, microsecond=0, tzinfo=UTC)
    if not cron_matches(minute_bucket, cron_expr):
        return False
    if last_run_at is None:
        return True
    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=UTC)
    last_bucket = last_run_at.astimezone(UTC).replace(second=0, microsecond=0)
    return last_bucket < minute_bucket


_SELECT_DUE_SCHEDULES_SQL = """
SELECT id, cron_expr, action, payload, last_run_at
  FROM schedules
 WHERE enabled = true
   AND action = 'social_post'
 FOR UPDATE SKIP LOCKED;
"""

_INSERT_SCHEDULED_ACTION_SQL = """
INSERT INTO scheduled_actions (
    id, action_type, scheduled_for, status, payload,
    playbook_id, hitl_status, persona_id, org_id,
    retry_count, max_retries, created_at, updated_at
) VALUES (
    %(id)s, %(action_type)s, %(scheduled_for)s, %(status)s, %(payload)s::jsonb,
    %(playbook_id)s, %(hitl_status)s, %(persona_id)s, %(org_id)s,
    %(retry_count)s, %(max_retries)s, NOW(), NOW()
);
"""

_UPDATE_LAST_RUN_SQL = """
UPDATE schedules SET last_run_at = %(last_run_at)s WHERE id = %(id)s;
"""


async def run() -> dict[str, Any]:
    """Materialize due cron schedules into ``scheduled_actions`` rows."""
    summary: dict[str, Any] = {"examined": 0, "materialized": 0, "skipped": 0, "errors": []}

    db_url = _get_database_url()
    if not db_url:
        logger.debug("DATABASE_URL unset — schedule materializer idle")
        return summary

    try:
        from psycopg import AsyncConnection
    except ImportError:
        logger.error("psycopg required for schedule materializer")
        return summary

    now = datetime.now(UTC)
    psycopg_url = _to_psycopg_url(db_url)

    try:
        async with await AsyncConnection.connect(psycopg_url) as conn, conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(_SELECT_DUE_SCHEDULES_SQL)
                rows = await cur.fetchall()
                cols = [d.name for d in cur.description] if cur.description else []

            for record in rows:
                row = dict(zip(cols, record, strict=False))
                summary["examined"] += 1
                schedule_id = row["id"]
                cron_expr = row["cron_expr"]
                payload_raw = row.get("payload") or {}
                if isinstance(payload_raw, str):
                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        payload = {}
                else:
                    payload = dict(payload_raw)

                last_run_at = row.get("last_run_at")
                if not is_schedule_due(cron_expr, last_run_at, now):
                    summary["skipped"] += 1
                    continue

                org_id = str(payload.get("org_id") or "").strip()
                if not org_id:
                    msg = f"schedule {schedule_id} missing payload.org_id"
                    logger.warning(msg)
                    summary["errors"].append(msg)
                    summary["skipped"] += 1
                    continue

                platform = str(payload.get("platform") or "").strip().lower()
                if not platform:
                    msg = f"schedule {schedule_id} missing payload.platform"
                    logger.warning(msg)
                    summary["errors"].append(msg)
                    summary["skipped"] += 1
                    continue

                action_payload = {k: v for k, v in payload.items() if k not in {"org_id"}}
                action_payload["materialized_from_schedule"] = str(schedule_id)
                action_payload["platform"] = platform

                playbook_id = payload.get("playbook_id")
                hitl_status = payload.get("hitl_status")
                if playbook_id and hitl_status is None:
                    hitl_status = "pending"

                minute_bucket = now.replace(second=0, microsecond=0, tzinfo=UTC)
                async with conn.cursor() as cur:
                    await cur.execute(
                        _INSERT_SCHEDULED_ACTION_SQL,
                        {
                            "id": uuid.uuid4(),
                            "action_type": "social_post",
                            "scheduled_for": minute_bucket,
                            "status": "pending",
                            "payload": json.dumps(action_payload),
                            "playbook_id": playbook_id,
                            "hitl_status": hitl_status,
                            "persona_id": payload.get("persona_id"),
                            "org_id": org_id,
                            "retry_count": 0,
                            "max_retries": int(payload.get("max_retries") or 3),
                        },
                    )
                    await cur.execute(
                        _UPDATE_LAST_RUN_SQL,
                        {"id": schedule_id, "last_run_at": minute_bucket},
                    )
                summary["materialized"] += 1
                logger.info(
                    "Materialized schedule %s → scheduled_action org=%s platform=%s",
                    schedule_id,
                    org_id,
                    platform,
                )
    except Exception as exc:
        logger.exception("Schedule materializer tick failed")
        summary["errors"].append(f"{exc.__class__.__name__}: {exc}")

    return summary


async def periodic_loop(shutdown: asyncio.Event) -> None:
    """Run materializer every minute until shutdown."""
    while not shutdown.is_set():
        try:
            summary = await run()
            if summary.get("materialized"):
                logger.info(
                    "schedule materializer: examined=%d materialized=%d skipped=%d",
                    summary["examined"],
                    summary["materialized"],
                    summary["skipped"],
                )
        except Exception:
            logger.exception("Schedule materializer periodic loop tick failed")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=MATERIALIZER_INTERVAL_SECONDS)
        except TimeoutError:
            continue
