"""Scheduled-action executor for ``ScheduledAction.SOCIAL_POST``.

Drains the ``scheduled_actions`` table once per minute, dispatching
due rows through the corresponding social-platform tool
(``mastodon_post``, ``bluesky_post``, ``reddit_post``, or
``send_marketing_email``).

Why this exists
---------------

The audit at ``docs/...`` flagged that ``ScheduledAction.SOCIAL_POST``
had been added to the enum and the docstring referenced
"Celery Beat reads this from the schedules table" but no executor
actually drains due rows. Without this drain, campaigns can dispatch
posts on demand but cannot honour a "3-post-per-day cadence" — the
schedule API accepts the row, then nothing fires it.

This executor follows the existing ``selva_workers.jobs`` pattern
(``provider_balance_probe.run()``) — a module-level ``async def run()``
invoked on a fixed cadence by ``__main__._scheduled_action_loop``.
We deliberately did NOT add Celery / APScheduler:

- The CLAUDE.md "AutoSwarm Office" section says workers run
  Redis-Streams + asyncio. Adding a Celery broker would double the
  infrastructure surface for one job.
- ``jobs/__init__.py`` already documents the cadence pattern as
  "fixed cadence by the worker's housekeeping loop".
- APScheduler would add a dep + a parallel scheduler runtime that
  doesn't share the worker's asyncio loop. ``asyncio.create_task`` +
  ``asyncio.sleep(60)`` is plenty for a 60s drain.

Concurrency & safety
--------------------

The drain query uses ``FOR UPDATE SKIP LOCKED`` so multiple worker
pods racing the same drain each grab a disjoint slice. Each row's
status flips to ``in_flight`` inside the same transaction that
selects it — once committed, no other pod will pick the row up until
its status returns to ``pending`` (rate-limit reschedule).

Failure handling
----------------

- **Tool-level rate limit** (mastodon/bluesky have a 30-min Redis
  rate-limit; their ``execute()`` returns ``ToolResult(success=False,
  error="...rate-limit hit...")``): the executor RESCHEDULES — sets
  ``scheduled_for = NOW() + 30min``, status stays ``pending``, retry
  counter unchanged. Rate limit is operator policy, not a fault.
- **Transient failures** (network, 5xx, ToolNotConfiguredError
  during a momentary credential issue): increments ``retry_count``,
  status flips back to ``pending`` with ``scheduled_for = NOW() +
  60s * 2^retry_count`` (exponential backoff up to 30min).
- **Dead letter**: when ``retry_count >= max_retries`` the row stays
  in ``failed`` (terminal) — kept for ops triage. A follow-up dashboard
  surface lists ``status='failed'`` rows with ``last_error`` previews.
- **Malformed payload** (missing ``platform``, unknown ``platform``,
  missing required field for the chosen platform): the row goes
  straight to ``failed`` with ``retry_count = max_retries`` so the
  bad row doesn't churn through retries. Operators fix the row by
  hand or delete it; the executor's job is to NEVER crash on a
  malformed payload (it would block every other due row in the
  drain batch).

HITL respect
------------

Rows with ``playbook_id IS NOT NULL AND hitl_status != 'approved'``
are SKIPPED at the SELECT layer (filtered in WHERE clause). They
stay ``pending`` until an approver flips ``hitl_status`` to
``approved``. The executor never bypasses HITL. The underlying
social tools also enforce their own HITL ASK-level gates per the
permission matrix; this is defense-in-depth at the queue layer.

Budget gate (forward-looking)
-----------------------------

The ``madfam-budget-gate`` package shipped a ``BudgetGate`` API that
returns ALLOW/DENY with cost projections. Once the gate is wired
into the dispatch path here, the executor will call ``gate.check()``
before invoking the tool and short-circuit to ``failed`` /
``rescheduled`` based on the gate's verdict.

  TODO(budget-gate): once ``packages/budget-gate`` exposes a
  ``BudgetGate.check()`` async method (current shape: only
  ``cost_model.py`` + ``scope.py`` — see PR #TBD), wire it before
  the tool dispatch below. Until then we rely on per-tool token
  budgeting + the org-level Dhanam credit ledger as the cost gate.

Observability
-------------

Every dispatch attempt emits a ``scheduled_action_dispatched`` event
via ``selva_workers.event_emitter.emit_event`` with
``{action_type, platform, persona_id, success, action_id,
duration_ms}``. Falls through to a structured JSON log line when
the event emitter is unavailable (e.g. nexus-api down) — the
fire-and-forget shape of ``emit_event`` already swallows errors so
observability never blocks the drain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Public so tests can monkeypatch.
DRAIN_BATCH_SIZE: int = 50
DRAIN_INTERVAL_SECONDS: int = 60
RATE_LIMIT_RESCHEDULE_SECONDS: int = 30 * 60  # 30 min — matches mastodon/bluesky tool TTLs.

# Cap exponential backoff so a long-broken provider doesn't push retries
# into the next quarter.
RETRY_BACKOFF_CAP_SECONDS: int = 30 * 60

# Truncate ``last_error`` writes — the column is TEXT (unbounded) but
# very long error strings are hostile to ops dashboards. Tools already
# sanitize their own errors before returning them; this is the queue-
# layer cap.
LAST_ERROR_TRUNCATE_CHARS: int = 1024

# Heuristic for "is this a rate-limit error?" — every social tool
# returns ``ToolResult(success=False, error="...rate-limit hit...")``
# (see mastodon_tools._check_and_set_rate_limit and bluesky_tools).
# Keep the match case-insensitive + tolerant of the exact phrase
# variants ("rate-limit", "rate limit").
_RATE_LIMIT_MARKERS: tuple[str, ...] = ("rate-limit", "rate limit")


# ---------------------------------------------------------------------------
# Platform → tool name mapping
# ---------------------------------------------------------------------------

_PLATFORM_TOOL_NAMES: dict[str, str] = {
    "mastodon": "mastodon_post",
    "bluesky": "bluesky_post",
    "reddit": "reddit_post",
    # ``email`` here means "marketing email" (drip campaigns are the use
    # case the executor was asked to power). Transactional ``send_email``
    # is a separate tool with stricter HITL — it should NOT be schedulable.
    "email": "send_marketing_email",
}


# ---------------------------------------------------------------------------
# DB helpers — psycopg async
# ---------------------------------------------------------------------------


def _get_database_url() -> str | None:
    """Resolve the DB URL the same way the checkpointer does.

    Falls through to ``DATABASE_URL`` env when ``Settings.database_url``
    is unset (e.g. in tests) so the executor is usable both inside the
    worker process and via direct ``await run()`` from a test fixture.
    """
    try:
        from selva_workers.config import get_settings

        settings = get_settings()
        if settings.database_url:
            return settings.database_url
    except Exception:
        # Settings can fail to instantiate in test environments where
        # required env vars are intentionally unset. Fall through to
        # the bare env var.
        logger.debug("get_settings() failed in scheduled action executor", exc_info=True)
    return os.environ.get("DATABASE_URL")


def _to_psycopg_url(url: str) -> str:
    """Strip the SQLAlchemy ``+asyncpg`` driver suffix.

    SQLAlchemy uses ``postgresql+asyncpg://`` but psycopg expects
    plain ``postgresql://``. Mirror the same transform the checkpointer
    does so an operator-set ``DATABASE_URL`` works for both paths.
    """
    return url.replace("postgresql+asyncpg", "postgresql")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run() -> dict[str, Any]:
    """Drain due ``scheduled_actions`` rows for ``action_type='social_post'``.

    Returns a summary dict useful for the cron's exit log + tests:

    .. code-block:: python

        {
            "claimed": int,    # rows successfully transitioned to in_flight
            "completed": int,  # rows that succeeded
            "failed": int,     # rows that exhausted retries
            "rescheduled": int,  # rows hit by rate-limit, pushed to NOW()+30min
            "retried": int,    # rows that incremented retry_count
            "skipped_hitl": int,  # rows skipped because playbook hitl_status != approved
            "errors": list[str],  # per-row error summaries (truncated)
        }
    """
    summary: dict[str, Any] = {
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "rescheduled": 0,
        "retried": 0,
        "skipped_hitl": 0,
        "errors": [],
    }

    db_url = _get_database_url()
    if not db_url:
        logger.debug(
            "DATABASE_URL unset — scheduled action executor has nothing to drain"
        )
        return summary

    # Late import so the module is importable in environments without
    # psycopg (e.g. unit tests that monkeypatch _claim_due_rows).
    try:
        from psycopg import AsyncConnection
    except ImportError:
        logger.error(
            "psycopg is required for the scheduled action executor but is not installed"
        )
        return summary

    psycopg_url = _to_psycopg_url(db_url)

    # Open a single short-lived connection per drain tick. The drain
    # is bounded (LIMIT 50) and runs once per minute — connection
    # pool overhead is not justified.
    try:
        async with await AsyncConnection.connect(psycopg_url) as conn:
            await _drain_once(conn, summary)
    except Exception as exc:
        logger.exception("Scheduled action drain failed")
        summary["errors"].append(f"drain failed: {exc.__class__.__name__}: {exc}")

    return summary


async def _drain_once(conn: Any, summary: dict[str, Any]) -> None:
    """Single drain iteration — claim rows, dispatch each.

    The claim happens in one transaction; dispatch happens outside
    the transaction so a slow tool call (Mastodon API can take seconds)
    doesn't hold ``FOR UPDATE`` locks open. Each row's terminal status
    update happens in its own short-lived transaction.
    """
    rows = await _claim_due_rows(conn, batch_size=DRAIN_BATCH_SIZE)
    summary["claimed"] = len(rows)

    if not rows:
        return

    for row in rows:
        try:
            outcome = await _dispatch_row(row)
        except Exception as exc:
            # _dispatch_row is supposed to never raise — but if it does,
            # treat the row as a transient failure rather than crashing
            # the whole drain.
            logger.exception("Unhandled error dispatching scheduled action %s", row.get("id"))
            outcome = _DispatchOutcome(
                success=False,
                error=f"executor crash: {exc.__class__.__name__}: {exc}",
                rate_limited=False,
            )

        await _record_outcome(conn, row, outcome, summary)


# ---------------------------------------------------------------------------
# Drain query — the heart of the executor
# ---------------------------------------------------------------------------


# Hot-path SQL kept as a module constant so test fixtures can validate
# its shape (rather than copy-pasting it). The CTE pattern claims +
# transitions in a single statement, returning the claimed rows for
# dispatch outside the lock window.
_CLAIM_DUE_ROWS_SQL = """
WITH due AS (
    SELECT id
      FROM scheduled_actions
     WHERE action_type = %(action_type)s
       AND status = 'pending'
       AND scheduled_for <= NOW()
       AND (
           playbook_id IS NULL
           OR hitl_status = 'approved'
       )
     ORDER BY scheduled_for ASC
     LIMIT %(limit)s
     FOR UPDATE SKIP LOCKED
)
UPDATE scheduled_actions sa
   SET status = 'in_flight',
       started_at = NOW(),
       updated_at = NOW()
  FROM due
 WHERE sa.id = due.id
RETURNING sa.id, sa.action_type, sa.payload, sa.retry_count,
          sa.max_retries, sa.playbook_id, sa.hitl_status,
          sa.persona_id, sa.org_id;
"""


async def _claim_due_rows(
    conn: Any, *, batch_size: int = DRAIN_BATCH_SIZE
) -> list[dict[str, Any]]:
    """Claim up to ``batch_size`` due rows, transitioning each to
    ``in_flight`` atomically.

    The query is idempotent: re-running it picks up the next slice.
    The ``FOR UPDATE SKIP LOCKED`` clause means concurrent workers
    don't fight for the same rows — they each get a disjoint slice.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            _CLAIM_DUE_ROWS_SQL,
            {"action_type": "social_post", "limit": batch_size},
        )
        records = await cur.fetchall()
        # psycopg returns tuples by default. Convert to dicts using
        # cursor.description so the rest of the code is positional-
        # index-free (resilient to column order changes).
        cols = [d.name for d in cur.description] if cur.description else []
    await conn.commit()

    rows: list[dict[str, Any]] = []
    for record in records:
        row = dict(zip(cols, record, strict=False))
        # ``payload`` may come back as a dict (psycopg JSONB adapter
        # registered) or as a JSON-encoded string (no adapter). Normalize.
        if isinstance(row.get("payload"), str):
            try:
                row["payload"] = json.loads(row["payload"])
            except json.JSONDecodeError:
                # Malformed payload — let _dispatch_row mark it failed.
                row["payload"] = {"_malformed": row["payload"]}
        if not isinstance(row.get("payload"), dict):
            row["payload"] = {}
        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Dispatch — invoke the right tool based on payload.platform
# ---------------------------------------------------------------------------


class _DispatchOutcome:
    """Tagged result of a single row dispatch.

    Plain class (not @dataclass) so it stays lightweight and
    test-friendly without importing dataclasses into a hot path.
    """

    __slots__ = ("success", "error", "rate_limited", "permanent")

    def __init__(
        self,
        *,
        success: bool,
        error: str | None = None,
        rate_limited: bool = False,
        permanent: bool = False,
    ) -> None:
        self.success = success
        self.error = error
        # ``rate_limited`` reschedules WITHOUT incrementing retry_count.
        self.rate_limited = rate_limited
        # ``permanent`` jumps straight to ``failed`` (no retry). Used for
        # malformed payloads — retrying a bad row is wasted work.
        self.permanent = permanent


async def _dispatch_row(row: dict[str, Any]) -> _DispatchOutcome:
    """Dispatch a single row through the appropriate social tool.

    Never raises — every error path returns a ``_DispatchOutcome``
    so a single bad row can't kill the drain.
    """
    payload = row.get("payload") or {}
    platform = (payload.get("platform") or "").strip().lower()

    if not platform:
        return _DispatchOutcome(
            success=False,
            error="payload.platform missing — cannot route to a tool",
            permanent=True,
        )

    tool_name = _PLATFORM_TOOL_NAMES.get(platform)
    if tool_name is None:
        return _DispatchOutcome(
            success=False,
            error=(
                f"unknown payload.platform '{platform}' — supported: "
                f"{sorted(_PLATFORM_TOOL_NAMES)}"
            ),
            permanent=True,
        )

    # Late import — selva_tools registry auto-discovers builtins on
    # first call, which is heavy. Keep it out of module import time.
    try:
        from selva_tools import get_tool_registry
    except Exception as exc:
        return _DispatchOutcome(
            success=False,
            error=f"tool registry import failed: {exc.__class__.__name__}: {exc}",
        )

    registry = get_tool_registry()
    tool = registry.get(tool_name)
    if tool is None:
        return _DispatchOutcome(
            success=False,
            error=f"tool '{tool_name}' not registered",
            permanent=True,
        )

    # TODO(budget-gate): once packages/budget-gate ships a
    # ``BudgetGate.check()`` async API, gate the dispatch here:
    #
    #     from madfam_budget_gate import BudgetGate
    #     verdict = await BudgetGate.check(
    #         org_id=row["org_id"],
    #         action="social_post",
    #         estimated_cost_usd=...,
    #     )
    #     if verdict.deny:
    #         return _DispatchOutcome(success=False, error=verdict.reason)
    #
    # Until that PR lands the per-tool token budget + Dhanam credit
    # ledger remain the cost gate.

    # Build kwargs for the tool. Only forward keys that match the
    # tool's parameter schema — never blind-spread the whole payload
    # because that would let a malformed/malicious row hand the tool
    # arguments outside its allow-list.
    tool_kwargs = _build_tool_kwargs(platform, payload, persona_id=row.get("persona_id"))
    if tool_kwargs is None:
        return _DispatchOutcome(
            success=False,
            error=f"required fields for '{platform}' missing in payload",
            permanent=True,
        )

    try:
        result = await tool.execute(**tool_kwargs)
    except Exception as exc:
        # Examples: ToolNotConfiguredError (creds missing), httpx
        # network exceptions, third-party SDK assertion failures.
        # Treat as transient — a credential restored five minutes
        # later should let the row succeed.
        logger.warning(
            "Tool '%s' raised dispatching scheduled action: %s",
            tool_name,
            exc,
            exc_info=True,
        )
        return _DispatchOutcome(
            success=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    if result.success:
        return _DispatchOutcome(success=True)

    error_msg = (result.error or "tool returned success=False without an error message").strip()
    if _is_rate_limit_error(error_msg):
        return _DispatchOutcome(
            success=False,
            error=error_msg,
            rate_limited=True,
        )

    return _DispatchOutcome(success=False, error=error_msg)


def _is_rate_limit_error(error_msg: str) -> bool:
    lowered = error_msg.lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def _build_tool_kwargs(
    platform: str, payload: dict[str, Any], *, persona_id: Any
) -> dict[str, Any] | None:
    """Build the kwargs dict for the platform's tool from the payload.

    Returns ``None`` when a required field is missing — caller maps
    that to a permanent failure. Optional fields are forwarded only
    when present so the tool's own defaults take effect otherwise.
    """
    persona = (persona_id or payload.get("persona_id") or "default")

    if platform == "mastodon":
        instance = payload.get("instance")
        status = payload.get("status")
        if not instance or not status:
            return None
        kwargs: dict[str, Any] = {
            "instance": instance,
            "status": status,
            "persona_id": persona,
        }
        for optional in ("visibility", "content_warning", "sensitive"):
            if optional in payload:
                kwargs[optional] = payload[optional]
        return kwargs

    if platform == "bluesky":
        text = payload.get("text") or payload.get("status")
        if not text:
            return None
        return {"text": text, "persona_id": persona}

    if platform == "reddit":
        subreddit = payload.get("subreddit")
        title = payload.get("title")
        body = payload.get("body")
        if not subreddit or not title or not body:
            return None
        return {
            "subreddit": subreddit,
            "title": title,
            "body": body,
            "persona_id": persona,
        }

    if platform == "email":
        # send_marketing_email's required fields per
        # marketing_tools.SendMarketingEmailTool.parameters_schema().
        # Forward through the whole sub-payload; the tool validates
        # individual fields server-side and refuses on misses.
        recipient = payload.get("recipient") or payload.get("to")
        subject = payload.get("subject")
        body = payload.get("body") or payload.get("html")
        if not recipient or not subject or not body:
            return None
        kwargs = {"recipient": recipient, "subject": subject, "body": body}
        for optional in ("agent_role", "campaign_id", "template_id", "list_unsubscribe"):
            if optional in payload:
                kwargs[optional] = payload[optional]
        return kwargs

    return None


# ---------------------------------------------------------------------------
# Outcome recording — terminal status writes + observability
# ---------------------------------------------------------------------------


async def _record_outcome(
    conn: Any,
    row: dict[str, Any],
    outcome: _DispatchOutcome,
    summary: dict[str, Any],
) -> None:
    """Update the row's terminal status and emit a dispatch event.

    Each branch ends in exactly one of: completed / pending (rescheduled
    / retried) / failed (dead letter). Status ``in_flight`` should never
    leak past this function.
    """
    row_id = row.get("id")
    payload = row.get("payload") or {}
    platform = (payload.get("platform") or "").strip().lower() or None
    persona_id = row.get("persona_id") or payload.get("persona_id")
    retry_count = int(row.get("retry_count") or 0)
    max_retries = int(row.get("max_retries") or 0)

    if outcome.success:
        await _mark_completed(conn, row_id)
        summary["completed"] += 1
        await _emit_dispatch_event(
            row=row, platform=platform, persona_id=persona_id, success=True
        )
        return

    error_truncated = (outcome.error or "")[:LAST_ERROR_TRUNCATE_CHARS]

    if outcome.rate_limited:
        # Rate-limit reschedule does NOT bump retry_count — the operator's
        # rate-limit policy is not a fault of the row itself.
        await _mark_rescheduled(
            conn,
            row_id,
            new_scheduled_for=datetime.now(UTC) + timedelta(seconds=RATE_LIMIT_RESCHEDULE_SECONDS),
            last_error=error_truncated,
        )
        summary["rescheduled"] += 1
        await _emit_dispatch_event(
            row=row,
            platform=platform,
            persona_id=persona_id,
            success=False,
            extra={"rate_limited": True},
        )
        return

    if outcome.permanent or retry_count + 1 >= max_retries:
        # Dead letter. ``retry_count + 1 >= max_retries`` mirrors the
        # ">= MAX_RETRIES after this attempt" semantics — the row got
        # ``max_retries`` chances total, this attempt was the last.
        await _mark_failed(conn, row_id, last_error=error_truncated)
        summary["failed"] += 1
        if outcome.error:
            summary["errors"].append(f"{row_id}: {error_truncated}")
        await _emit_dispatch_event(
            row=row,
            platform=platform,
            persona_id=persona_id,
            success=False,
            extra={"dead_letter": True},
        )
        return

    # Transient retry — exponential backoff capped at 30min.
    backoff_seconds = min(
        60 * (2 ** retry_count),
        RETRY_BACKOFF_CAP_SECONDS,
    )
    await _mark_retried(
        conn,
        row_id,
        new_scheduled_for=datetime.now(UTC) + timedelta(seconds=backoff_seconds),
        new_retry_count=retry_count + 1,
        last_error=error_truncated,
    )
    summary["retried"] += 1
    await _emit_dispatch_event(
        row=row,
        platform=platform,
        persona_id=persona_id,
        success=False,
        extra={"retry_count": retry_count + 1},
    )


_MARK_COMPLETED_SQL = """
UPDATE scheduled_actions
   SET status = 'completed',
       completed_at = NOW(),
       updated_at = NOW(),
       last_error = NULL
 WHERE id = %(id)s;
"""

_MARK_RESCHEDULED_SQL = """
UPDATE scheduled_actions
   SET status = 'pending',
       scheduled_for = %(scheduled_for)s,
       last_error = %(last_error)s,
       updated_at = NOW(),
       started_at = NULL
 WHERE id = %(id)s;
"""

_MARK_RETRIED_SQL = """
UPDATE scheduled_actions
   SET status = 'pending',
       scheduled_for = %(scheduled_for)s,
       retry_count = %(retry_count)s,
       last_error = %(last_error)s,
       updated_at = NOW(),
       started_at = NULL
 WHERE id = %(id)s;
"""

_MARK_FAILED_SQL = """
UPDATE scheduled_actions
   SET status = 'failed',
       last_error = %(last_error)s,
       completed_at = NOW(),
       updated_at = NOW()
 WHERE id = %(id)s;
"""


async def _mark_completed(conn: Any, row_id: Any) -> None:
    async with conn.cursor() as cur:
        await cur.execute(_MARK_COMPLETED_SQL, {"id": _coerce_id(row_id)})
    await conn.commit()


async def _mark_rescheduled(
    conn: Any, row_id: Any, *, new_scheduled_for: datetime, last_error: str
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            _MARK_RESCHEDULED_SQL,
            {
                "id": _coerce_id(row_id),
                "scheduled_for": new_scheduled_for,
                "last_error": last_error,
            },
        )
    await conn.commit()


async def _mark_retried(
    conn: Any,
    row_id: Any,
    *,
    new_scheduled_for: datetime,
    new_retry_count: int,
    last_error: str,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            _MARK_RETRIED_SQL,
            {
                "id": _coerce_id(row_id),
                "scheduled_for": new_scheduled_for,
                "retry_count": new_retry_count,
                "last_error": last_error,
            },
        )
    await conn.commit()


async def _mark_failed(conn: Any, row_id: Any, *, last_error: str) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            _MARK_FAILED_SQL,
            {"id": _coerce_id(row_id), "last_error": last_error},
        )
    await conn.commit()


def _coerce_id(row_id: Any) -> Any:
    """Pass UUIDs through as-is; otherwise stringify.

    psycopg accepts both ``uuid.UUID`` instances and stringified UUIDs
    against a UUID column. Tests using sqlite or mocks may pass
    plain strings, which is also fine.
    """
    if isinstance(row_id, uuid.UUID):
        return row_id
    return str(row_id) if row_id is not None else None


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


async def _emit_dispatch_event(
    *,
    row: dict[str, Any],
    platform: str | None,
    persona_id: Any,
    success: bool,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a ``scheduled_action_dispatched`` event.

    Tries the worker's existing event emitter (POSTs to nexus-api +
    Redis PUBLISH). On any failure, falls through to a structured JSON
    log line so the metric is recoverable from logs alone.
    """
    payload: dict[str, Any] = {
        "action_id": str(row.get("id")) if row.get("id") is not None else None,
        "action_type": "social_post",
        "platform": platform,
        "persona_id": persona_id or "default",
        "success": success,
    }
    if extra:
        payload.update(extra)

    try:
        from selva_workers.config import get_settings
        from selva_workers.event_emitter import emit_event

        settings = get_settings()
        org_id = row.get("org_id") or "default"
        await emit_event(
            settings.nexus_api_url,
            event_type="scheduled_action_dispatched",
            event_category="scheduled_action",
            payload=payload,
            org_id=org_id,
        )
    except Exception:
        # emit_event is fire-and-forget — failures here mean the
        # emitter itself raised at construction (very rare). Drop to
        # the log-only path; the JSON line is grep-able by ops.
        logger.info("scheduled_action_dispatched %s", json.dumps(payload, default=str))
        return

    # Belt-and-braces — emit the same line to logs even on success
    # so log-shipping pipelines that don't index the events table
    # still surface the metric.
    logger.info("scheduled_action_dispatched %s", json.dumps(payload, default=str))


# ---------------------------------------------------------------------------
# Periodic loop wired into the worker's main() lifecycle
# ---------------------------------------------------------------------------


async def periodic_loop(shutdown: asyncio.Event) -> None:
    """Drain every ``DRAIN_INTERVAL_SECONDS`` until ``shutdown`` is set.

    Wired from ``selva_workers.__main__.main()`` alongside
    ``_periodic_cleanup``. Each iteration is wrapped in a broad
    ``except`` so a single bad tick (DB blip, transient psycopg error)
    doesn't kill the loop — we'd rather skip a minute than drop the
    schedule entirely.
    """
    while not shutdown.is_set():
        try:
            summary = await run()
            if summary.get("claimed"):
                logger.info(
                    "scheduled_action drain tick: claimed=%d completed=%d "
                    "rescheduled=%d retried=%d failed=%d skipped_hitl=%d",
                    summary["claimed"],
                    summary["completed"],
                    summary["rescheduled"],
                    summary["retried"],
                    summary["failed"],
                    summary["skipped_hitl"],
                )
        except Exception:
            logger.exception("Scheduled action periodic loop tick failed")

        # Use wait_for so shutdown signals don't have to wait the full
        # 60s. We swallow the timeout — that's the normal path.
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=DRAIN_INTERVAL_SECONDS)
        except TimeoutError:
            continue
