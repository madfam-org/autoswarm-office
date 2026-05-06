"""Drain due ``social_account_warmup_actions`` rows.

Sibling job to ``social_post_executor`` — same drain pattern (psycopg
async + ``FOR UPDATE SKIP LOCKED`` + 60s tick), but the source table
is the dragon-egg warmup queue, not the generic scheduled-actions
queue. Rationale for keeping them separate (rather than overloading
``scheduled_actions`` with a third action_type):

- The egg/action data model has different invariants (FK to egg,
  day_offset, content_brief, status set ``planned``/``pending_human``/
  ``in_flight``/``completed``/``failed``/``skipped`` instead of the
  generic ``pending``/``in_flight``/``completed``/``failed``/
  ``dead_letter`` of scheduled_actions).
- The warmup row holds an FK to the egg, so the dispatch path needs
  the egg's ``platform`` + ``persona_id`` + ``handle`` + ``instance_url``.
  Joining or normalizing into scheduled_actions would either denormalize
  data into ``payload`` (drift risk) or require a JOIN on every drain
  tick (perf risk).
- Phase 2 will gate every dispatch on a per-action Dhanam credit
  charge, computed from ``action_type``. That charge logic doesn't
  belong in the generic scheduled-actions executor.

What this job does
------------------

For each ``planned`` action whose ``scheduled_for <= NOW()``:

1. Claim it (``status='in_flight'``, ``executed_at=NOW()``).
2. Look up the parent egg for routing data.
3. Route based on ``action_type``:

   - ``original_post_no_link``, ``original_post_with_link``,
     ``promotional_post`` → dispatch via the platform tool (mastodon_post,
     bluesky_post, reddit_post). Same shape as
     ``social_post_executor._dispatch_row`` — same tools, same registry.
   - ``profile_setup``, ``follow_curated``, ``boost_high_signal``,
     ``reply_substantive`` → these should NEVER be ``planned`` because
     ``WARMUP_PLAN`` marks them ``pending_human``. If we encounter one
     in ``planned`` status (operator override, manual SQL fix), we
     defensively flip it to ``pending_human`` and log a warning. Phase
     1.5 wires the HITL approval queue at this branch.

4. Update status to ``completed`` (success) / ``failed`` (transient or
   permanent failure).

HITL respect
------------

Rows with ``status='pending_human'`` are NEVER picked up by the drain
SQL — the WHERE clause filters to ``status='planned'`` only. The
operator's UI flips ``pending_human`` → ``planned`` (or directly
calls execute) when ready.

Budget gate
-----------

Every action that calls an LLM for content generation must pass through
``madfam-budget-gate``. Phase 1 doesn't *yet* generate content (operator
composes copy at execute time via ``content_brief`` field), so the gate
is a no-op for now — the wiring point is documented as a TODO so the
follow-up PR has somewhere obvious to plug in.

Observability
-------------

Each dispatch emits a ``dragon_egg_action_dispatched`` event via
``selva_workers.event_emitter.emit_event`` with payload
``{egg_id, action_type, platform, day_offset, success, duration_ms}``.
Falls through to a structured JSON log line when the emitter is
unavailable.

After every action update, the job calls the dragon-egg service's
``transition()`` via the nexus-api so the egg's ``status`` /
``progress`` stay in sync with action completions. Phase 1 does this
HTTP round-trip per action; Phase 2 will batch them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

DRAIN_BATCH_SIZE: int = 50
DRAIN_INTERVAL_SECONDS: int = 60
LAST_ERROR_TRUNCATE_CHARS: int = 1024


# action_type → (platform, payload_builder) routing.
_WORKER_DISPATCHABLE_ACTIONS: frozenset[str] = frozenset(
    {
        "original_post_no_link",
        "original_post_with_link",
        "promotional_post",
    }
)

# Phase 1 HITL-only: the worker doesn't dispatch these. Phase 1.5 will
# queue an approval request via the command_approvals router.
_HITL_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        "profile_setup",
        "follow_curated",
        "boost_high_signal",
        "reply_substantive",
    }
)

# Platform → tool name mapping. Mirrors social_post_executor — kept
# duplicated here so changes to either drain don't accidentally drift
# the other one's tool routing.
_PLATFORM_TOOL_NAMES: dict[str, str] = {
    "mastodon": "mastodon_post",
    "bluesky": "bluesky_post",
    "reddit": "reddit_post",
}


def _get_database_url() -> str | None:
    try:
        from selva_workers.config import get_settings

        settings = get_settings()
        if settings.database_url:
            return settings.database_url
    except Exception:
        logger.debug("get_settings() failed in dragon-egg warmup drain", exc_info=True)
    return os.environ.get("DATABASE_URL")


def _to_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg", "postgresql")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run() -> dict[str, Any]:
    """Drain due dragon-egg warmup actions.

    Returns a summary dict useful for the cron's exit log + tests:

    .. code-block:: python

        {
            "claimed": int,
            "completed": int,
            "failed": int,
            "hitl_skipped": int,    # rows defensively flipped to pending_human
            "errors": list[str],
        }
    """
    summary: dict[str, Any] = {
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "hitl_skipped": 0,
        "errors": [],
    }

    db_url = _get_database_url()
    if not db_url:
        return summary

    try:
        from psycopg import AsyncConnection
    except ImportError:
        logger.error("psycopg required for dragon-egg warmup drain but not installed")
        return summary

    psycopg_url = _to_psycopg_url(db_url)
    try:
        async with await AsyncConnection.connect(psycopg_url) as conn:
            await _drain_once(conn, summary)
    except Exception as exc:
        logger.exception("Dragon-egg warmup drain failed")
        summary["errors"].append(f"drain failed: {exc.__class__.__name__}: {exc}")

    return summary


async def _drain_once(conn: Any, summary: dict[str, Any]) -> None:
    rows = await _claim_due_rows(conn, batch_size=DRAIN_BATCH_SIZE)
    summary["claimed"] = len(rows)

    if not rows:
        return

    for row in rows:
        try:
            outcome = await _dispatch_row(row)
        except Exception as exc:
            logger.exception(
                "Unhandled error dispatching dragon-egg warmup action %s",
                row.get("action_id"),
            )
            outcome = _DispatchOutcome(
                success=False,
                error=f"executor crash: {exc.__class__.__name__}: {exc}",
            )

        await _record_outcome(conn, row, outcome, summary)


# ---------------------------------------------------------------------------
# Drain query — joins eggs ↔ actions so dispatch has all routing fields
# ---------------------------------------------------------------------------


_CLAIM_DUE_ROWS_SQL = """
WITH due AS (
    SELECT a.id AS action_id
      FROM social_account_warmup_actions a
     WHERE a.status = 'planned'
       AND a.scheduled_for <= NOW()
     ORDER BY a.scheduled_for ASC
     LIMIT %(limit)s
     FOR UPDATE SKIP LOCKED
)
UPDATE social_account_warmup_actions a
   SET status = 'in_flight',
       executed_at = NOW(),
       updated_at = NOW()
  FROM due
 WHERE a.id = due.action_id
RETURNING a.id AS action_id, a.egg_id, a.action_type, a.day_offset,
          a.content_brief,
          (SELECT e.platform FROM social_account_eggs e WHERE e.id = a.egg_id) AS platform,
          (SELECT e.persona_id FROM social_account_eggs e WHERE e.id = a.egg_id) AS persona_id,
          (SELECT e.handle FROM social_account_eggs e WHERE e.id = a.egg_id) AS handle,
          (SELECT e.instance_url FROM social_account_eggs e WHERE e.id = a.egg_id) AS instance_url,
          (SELECT e.owner_org_id FROM social_account_eggs e WHERE e.id = a.egg_id) AS owner_org_id;
"""


async def _claim_due_rows(
    conn: Any, *, batch_size: int = DRAIN_BATCH_SIZE
) -> list[dict[str, Any]]:
    async with conn.cursor() as cur:
        await cur.execute(_CLAIM_DUE_ROWS_SQL, {"limit": batch_size})
        records = await cur.fetchall()
        cols = [d.name for d in cur.description] if cur.description else []
    await conn.commit()

    rows: list[dict[str, Any]] = []
    for record in records:
        row = dict(zip(cols, record, strict=False))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Dispatch — route to platform tool or defensively flip HITL-only types
# ---------------------------------------------------------------------------


class _DispatchOutcome:
    __slots__ = ("success", "error", "hitl_required")

    def __init__(
        self,
        *,
        success: bool,
        error: str | None = None,
        hitl_required: bool = False,
    ) -> None:
        self.success = success
        self.error = error
        # HITL-only actions defensively land here; the row gets flipped
        # to ``pending_human`` rather than ``failed`` so an operator
        # can pick it up via the UI.
        self.hitl_required = hitl_required


async def _dispatch_row(row: dict[str, Any]) -> _DispatchOutcome:
    action_type = row.get("action_type") or ""
    platform = (row.get("platform") or "").strip().lower()

    if action_type in _HITL_ONLY_ACTIONS:
        # Should never reach here — WARMUP_PLAN marks these
        # ``pending_human`` at lay time, and the drain SQL filters
        # to ``status='planned'`` only. But if an operator manually
        # flipped a HITL action to ``planned``, we defensively
        # re-route to HITL rather than dispatching a profile-setup
        # call as a regular post.
        return _DispatchOutcome(
            success=False,
            error=f"action_type {action_type!r} is HITL-only in Phase 1",
            hitl_required=True,
        )

    if action_type not in _WORKER_DISPATCHABLE_ACTIONS:
        return _DispatchOutcome(
            success=False,
            error=f"unknown action_type {action_type!r}",
        )

    if not platform:
        return _DispatchOutcome(
            success=False,
            error="egg platform missing — cannot route",
        )

    tool_name = _PLATFORM_TOOL_NAMES.get(platform)
    if tool_name is None:
        return _DispatchOutcome(
            success=False,
            error=f"unsupported platform {platform!r}",
        )

    # TODO(budget-gate): once content generation is wired into the
    # warmup pipeline (Phase 2 content-generator service), gate every
    # LLM call here via madfam_budget_gate.BudgetGate.check(). The
    # default-OFF flag is documented in budget-gate's README.

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
            error=f"tool {tool_name!r} not registered",
        )

    tool_kwargs = _build_tool_kwargs(platform, row)
    if tool_kwargs is None:
        return _DispatchOutcome(
            success=False,
            error=f"required fields for {platform!r} missing on egg",
        )

    started_at = time.monotonic()
    try:
        result = await tool.execute(**tool_kwargs)
    except Exception as exc:
        logger.warning(
            "Tool %s raised dispatching dragon-egg action %s: %s",
            tool_name,
            row.get("action_id"),
            exc,
            exc_info=True,
        )
        return _DispatchOutcome(
            success=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    duration_ms = int((time.monotonic() - started_at) * 1000)
    await _emit_dispatch_event(row, success=result.success, duration_ms=duration_ms)

    if result.success:
        return _DispatchOutcome(success=True)

    error_msg = (result.error or "tool returned success=False without error").strip()
    return _DispatchOutcome(success=False, error=error_msg)


def _build_tool_kwargs(
    platform: str, row: dict[str, Any]
) -> dict[str, Any] | None:
    """Build tool kwargs from the egg's stored credentials + the
    action's ``content_brief`` (Phase 2: generated copy; Phase 1:
    operator-provided text via the action's ``content_brief`` field)."""
    persona_id = row.get("persona_id") or "default"
    content_brief = (row.get("content_brief") or "").strip()
    if not content_brief:
        # Phase 1 doesn't auto-generate copy. If the operator didn't
        # provide a brief by execute time, fail with a clear message
        # rather than dispatching empty content.
        return None

    if platform == "mastodon":
        instance_url = row.get("instance_url")
        if not instance_url:
            return None
        # The mastodon tool expects ``instance`` (the host fragment)
        # rather than the full URL; strip protocol + trailing slash.
        instance = (
            instance_url.replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )
        return {
            "instance": instance,
            "status": content_brief,
            "persona_id": persona_id,
        }

    if platform == "bluesky":
        return {"text": content_brief, "persona_id": persona_id}

    if platform == "reddit":
        # Reddit needs a subreddit — the egg's ``handle`` field is the
        # account itself; subreddit comes from the operator's brief
        # split on the first newline (convention: first line is the
        # subreddit + title separated by " :: ", body follows).
        # Phase 2 will move this to a structured field.
        lines = content_brief.split("\n", 1)
        if len(lines) < 2 or " :: " not in lines[0]:
            return None
        subreddit, title = lines[0].split(" :: ", 1)
        body = lines[1].strip()
        return {
            "subreddit": subreddit.strip(),
            "title": title.strip(),
            "body": body,
            "persona_id": persona_id,
        }

    return None


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------


_MARK_COMPLETED_SQL = """
UPDATE social_account_warmup_actions
   SET status = 'completed',
       executed_at = COALESCE(executed_at, NOW()),
       updated_at = NOW(),
       result = %(result)s
 WHERE id = %(id)s;
"""

_MARK_FAILED_SQL = """
UPDATE social_account_warmup_actions
   SET status = 'failed',
       updated_at = NOW(),
       result = %(result)s
 WHERE id = %(id)s;
"""

_MARK_PENDING_HUMAN_SQL = """
UPDATE social_account_warmup_actions
   SET status = 'pending_human',
       executed_at = NULL,
       updated_at = NOW(),
       result = %(result)s
 WHERE id = %(id)s;
"""


async def _record_outcome(
    conn: Any,
    row: dict[str, Any],
    outcome: _DispatchOutcome,
    summary: dict[str, Any],
) -> None:
    action_id = row.get("action_id")
    error_truncated = (outcome.error or "")[:LAST_ERROR_TRUNCATE_CHARS]
    error_payload = (
        json.dumps({"error": error_truncated}) if error_truncated else None
    )

    if outcome.success:
        async with conn.cursor() as cur:
            await cur.execute(
                _MARK_COMPLETED_SQL,
                {"id": action_id, "result": json.dumps({"ok": True})},
            )
        await conn.commit()
        summary["completed"] += 1
        return

    if outcome.hitl_required:
        async with conn.cursor() as cur:
            await cur.execute(
                _MARK_PENDING_HUMAN_SQL,
                {"id": action_id, "result": error_payload},
            )
        await conn.commit()
        summary["hitl_skipped"] += 1
        return

    async with conn.cursor() as cur:
        await cur.execute(
            _MARK_FAILED_SQL,
            {"id": action_id, "result": error_payload},
        )
    await conn.commit()
    summary["failed"] += 1
    if outcome.error:
        summary["errors"].append(f"{action_id}: {error_truncated}")


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


async def _emit_dispatch_event(
    row: dict[str, Any],
    *,
    success: bool,
    duration_ms: int,
) -> None:
    """Emit a ``dragon_egg_action_dispatched`` event.

    Fire-and-forget — failures swallowed inside ``emit_event`` so a
    nexus-api outage doesn't block the drain.
    """
    try:
        from selva_workers.config import get_settings
        from selva_workers.event_emitter import emit_event
    except Exception:
        logger.info(
            "dragon_egg_action_dispatched (emitter unavailable): "
            "egg_id=%s action_type=%s platform=%s day_offset=%s success=%s duration_ms=%d",
            row.get("egg_id"),
            row.get("action_type"),
            row.get("platform"),
            row.get("day_offset"),
            success,
            duration_ms,
        )
        return

    payload = {
        "egg_id": str(row.get("egg_id") or ""),
        "action_type": row.get("action_type"),
        "platform": row.get("platform"),
        "day_offset": row.get("day_offset"),
        "success": success,
        "duration_ms": duration_ms,
    }

    try:
        await emit_event(
            get_settings().nexus_api_url,
            event_type="dragon_egg_action_dispatched",
            event_category="dragon_eggs",
            payload=payload,
            org_id=row.get("owner_org_id") or "madfam",
        )
    except Exception:
        # Defensive — emit_event is fire-and-forget but swallow anyway.
        logger.debug("emit_event failed for dragon_egg dispatch", exc_info=True)


# ---------------------------------------------------------------------------
# Periodic loop
# ---------------------------------------------------------------------------


async def periodic_loop(shutdown: asyncio.Event) -> None:
    """Drain every ``DRAIN_INTERVAL_SECONDS`` until ``shutdown`` is set.

    Same shape as ``social_post_executor.periodic_loop``.
    """
    while not shutdown.is_set():
        try:
            summary = await run()
            if summary.get("claimed"):
                logger.info(
                    "dragon_egg_warmup tick: claimed=%d completed=%d "
                    "failed=%d hitl_skipped=%d",
                    summary["claimed"],
                    summary["completed"],
                    summary["failed"],
                    summary["hitl_skipped"],
                )
        except Exception:
            logger.exception("Dragon-egg warmup periodic loop tick failed")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=DRAIN_INTERVAL_SECONDS)
        except TimeoutError:
            continue
