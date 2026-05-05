"""Tests for ``selva_workers.jobs.dragon_egg_warmup``.

Covers the contract documented in the module docstring:

- The drain SQL filters to ``status='planned'`` (HITL-status rows
  never picked up).
- Worker-dispatchable action types route to the matching platform
  tool (mastodon → mastodon_post, etc).
- HITL-only action types in ``planned`` status are defensively
  flipped to ``pending_human`` rather than dispatched.
- Unknown action types / platforms → ``failed`` (permanent — no
  retry, since the egg's metadata isn't going to change).
- Missing ``content_brief`` → ``failed`` with a clear message
  (Phase 1 doesn't auto-generate copy).
- Tool exceptions don't crash the drain.
- ``_emit_dispatch_event`` falls back to log-line when emitter
  unavailable.
- Periodic loop respects shutdown signal.

The DB layer is mocked via the same ``_FakeConnection`` /
``_FakeCursor`` pattern as ``test_social_post_executor`` — keeps the
worker test suite Postgres-free.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_workers.jobs import dragon_egg_warmup as drain

# ---------------------------------------------------------------------------
# Fake psycopg async connection
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._rows = rows or []
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.description: list[Any] | None = None

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params or {}))

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, claim_rows: list[dict[str, Any]] | None = None) -> None:
        self.claim_rows = claim_rows or []
        self.cursors: list[_FakeCursor] = []
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        if not self.cursors:
            cur = _FakeCursor(rows=self._encode_claim_rows())
            col_names = [
                "action_id",
                "egg_id",
                "action_type",
                "day_offset",
                "content_brief",
                "platform",
                "persona_id",
                "handle",
                "instance_url",
                "owner_org_id",
            ]
            cur.description = []
            for name in col_names:
                desc = MagicMock(spec=["name"])
                desc.name = name
                cur.description.append(desc)
        else:
            cur = _FakeCursor()
        self.cursors.append(cur)
        return cur

    async def commit(self) -> None:
        self.commits += 1

    def _encode_claim_rows(self) -> list[tuple[Any, ...]]:
        # Mirror the dict→tuple ordering expected from cursor.description.
        return [
            (
                row.get("action_id"),
                row.get("egg_id"),
                row.get("action_type"),
                row.get("day_offset"),
                row.get("content_brief"),
                row.get("platform"),
                row.get("persona_id"),
                row.get("handle"),
                row.get("instance_url"),
                row.get("owner_org_id"),
            )
            for row in self.claim_rows
        ]


# ---------------------------------------------------------------------------
# _claim_due_rows shape
# ---------------------------------------------------------------------------


class TestClaimDueRowsSql:
    def test_sql_filters_to_planned_only(self) -> None:
        """HITL rows (status='pending_human') must NOT be picked up by
        the drain. The lock is the SQL ``WHERE a.status = 'planned'``
        clause."""
        assert "status = 'planned'" in drain._CLAIM_DUE_ROWS_SQL

    def test_sql_uses_for_update_skip_locked(self) -> None:
        """Disjoint claim across worker pods relies on this lock."""
        assert "FOR UPDATE SKIP LOCKED" in drain._CLAIM_DUE_ROWS_SQL

    def test_sql_orders_by_scheduled_for(self) -> None:
        """Oldest-due row goes first so a backed-up queue drains FIFO."""
        assert "ORDER BY a.scheduled_for ASC" in drain._CLAIM_DUE_ROWS_SQL

    def test_sql_returns_egg_routing_fields(self) -> None:
        """Dispatch needs platform/persona_id/handle/instance_url
        from the egg row — verified by RETURNING + subquery shape."""
        for col in ("platform", "persona_id", "handle", "instance_url"):
            assert col in drain._CLAIM_DUE_ROWS_SQL


# ---------------------------------------------------------------------------
# _dispatch_row routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDispatchRouting:
    @staticmethod
    def _row(**overrides: Any) -> dict[str, Any]:
        base = {
            "action_id": "action-1",
            "egg_id": "egg-1",
            "action_type": "original_post_no_link",
            "day_offset": 3,
            "content_brief": "Hello, world.",
            "platform": "bluesky",
            "persona_id": "test_persona",
            "handle": "@x",
            "instance_url": None,
            "owner_org_id": "madfam",
        }
        base.update(overrides)
        return base

    async def test_bluesky_dispatch_calls_bluesky_post(self) -> None:
        row = self._row()

        fake_tool = MagicMock()
        fake_tool.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_tool

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert outcome.success
        fake_registry.get.assert_called_with("bluesky_post")
        fake_tool.execute.assert_awaited_once()
        kwargs = fake_tool.execute.await_args.kwargs
        assert kwargs["text"] == "Hello, world."
        assert kwargs["persona_id"] == "test_persona"

    async def test_mastodon_dispatch_strips_protocol_from_instance(self) -> None:
        row = self._row(
            platform="mastodon",
            instance_url="https://fosstodon.org/",
        )

        fake_tool = MagicMock()
        fake_tool.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_tool

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert outcome.success
        fake_registry.get.assert_called_with("mastodon_post")
        kwargs = fake_tool.execute.await_args.kwargs
        # Tool expects ``instance`` (host), not the full URL.
        assert kwargs["instance"] == "fosstodon.org"

    async def test_reddit_dispatch_parses_subreddit_title_body(self) -> None:
        row = self._row(
            platform="reddit",
            content_brief="r/madfam :: Daily compliance update\nMore detail here\n— with full body",
        )

        fake_tool = MagicMock()
        fake_tool.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_tool

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert outcome.success
        kwargs = fake_tool.execute.await_args.kwargs
        assert kwargs["subreddit"] == "r/madfam"
        assert kwargs["title"] == "Daily compliance update"
        assert "More detail here" in kwargs["body"]


@pytest.mark.asyncio
class TestHITLDefensiveRoute:
    async def test_profile_setup_in_planned_status_routes_to_hitl(self) -> None:
        """If somehow a HITL-only action is in 'planned' status (operator
        manually flipped it), the drain refuses to dispatch and instead
        flips the row back to ``pending_human``."""
        row = TestDispatchRouting._row(action_type="profile_setup")
        outcome = await drain._dispatch_row(row)
        assert not outcome.success
        assert outcome.hitl_required

    async def test_follow_curated_routes_to_hitl(self) -> None:
        row = TestDispatchRouting._row(action_type="follow_curated")
        outcome = await drain._dispatch_row(row)
        assert outcome.hitl_required


@pytest.mark.asyncio
class TestDispatchEdgeCases:
    async def test_unknown_action_type_fails(self) -> None:
        row = TestDispatchRouting._row(action_type="bogus")
        outcome = await drain._dispatch_row(row)
        assert not outcome.success
        assert "unknown action_type" in (outcome.error or "")
        assert not outcome.hitl_required

    async def test_unsupported_platform_fails(self) -> None:
        row = TestDispatchRouting._row(platform="tiktok")
        outcome = await drain._dispatch_row(row)
        assert not outcome.success
        assert "tiktok" in (outcome.error or "")

    async def test_missing_content_brief_fails(self) -> None:
        """Phase 1 doesn't auto-generate copy — a missing content_brief
        is a clear operator error, not a transient failure."""
        row = TestDispatchRouting._row(content_brief=None)

        fake_tool = MagicMock()
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_tool

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert not outcome.success
        assert "required fields" in (outcome.error or "").lower()
        # Tool should NOT have been called.
        fake_tool.execute.assert_not_called()

    async def test_tool_exception_surfaces_as_failure(self) -> None:
        row = TestDispatchRouting._row()

        fake_tool = MagicMock()
        fake_tool.execute = AsyncMock(side_effect=RuntimeError("boom"))
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_tool

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert not outcome.success
        assert "RuntimeError" in (outcome.error or "")

    async def test_unregistered_tool_fails(self) -> None:
        row = TestDispatchRouting._row()

        fake_registry = MagicMock()
        fake_registry.get.return_value = None  # tool not registered

        with patch("selva_tools.get_tool_registry", return_value=fake_registry):
            outcome = await drain._dispatch_row(row)

        assert not outcome.success
        assert "not registered" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Outcome recording — terminal status writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordOutcome:
    async def test_success_marks_completed(self) -> None:
        conn = _FakeConnection()
        # Bypass the claim cursor — call _record_outcome directly.
        # Pop the claim cursor first so the next .cursor() call is the
        # mark_* path.
        conn.cursor()
        outcome = drain._DispatchOutcome(success=True)
        summary = {"completed": 0, "failed": 0, "hitl_skipped": 0, "errors": []}
        await drain._record_outcome(
            conn,
            {"action_id": "a-1"},
            outcome,
            summary,
        )
        assert summary["completed"] == 1
        # 2nd cursor (the mark) executed _MARK_COMPLETED_SQL.
        last_cur = conn.cursors[-1]
        assert last_cur.executed[0][0] == drain._MARK_COMPLETED_SQL

    async def test_hitl_required_marks_pending_human(self) -> None:
        conn = _FakeConnection()
        conn.cursor()
        outcome = drain._DispatchOutcome(
            success=False, error="HITL only", hitl_required=True
        )
        summary = {"completed": 0, "failed": 0, "hitl_skipped": 0, "errors": []}
        await drain._record_outcome(
            conn,
            {"action_id": "a-2"},
            outcome,
            summary,
        )
        assert summary["hitl_skipped"] == 1
        last_cur = conn.cursors[-1]
        assert last_cur.executed[0][0] == drain._MARK_PENDING_HUMAN_SQL

    async def test_failure_marks_failed(self) -> None:
        conn = _FakeConnection()
        conn.cursor()
        outcome = drain._DispatchOutcome(success=False, error="generic error")
        summary = {"completed": 0, "failed": 0, "hitl_skipped": 0, "errors": []}
        await drain._record_outcome(
            conn,
            {"action_id": "a-3"},
            outcome,
            summary,
        )
        assert summary["failed"] == 1
        assert any("generic error" in e for e in summary["errors"])
        last_cur = conn.cursors[-1]
        assert last_cur.executed[0][0] == drain._MARK_FAILED_SQL


# ---------------------------------------------------------------------------
# Drain-level integration with fake conn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDrainOnce:
    async def test_no_rows_returns_empty_summary(self) -> None:
        conn = _FakeConnection(claim_rows=[])
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "hitl_skipped": 0,
            "errors": [],
        }
        await drain._drain_once(conn, summary)
        assert summary["claimed"] == 0
        assert summary["completed"] == 0


# ---------------------------------------------------------------------------
# Emit-event fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmitEvent:
    async def test_emit_event_failure_doesnt_crash(self) -> None:
        """If the emitter is down, the drain just logs and moves on."""
        with patch.dict(
            "sys.modules",
            {"selva_workers.event_emitter": None},
        ):
            # Should be a no-op (just a log line).
            await drain._emit_dispatch_event(
                {"egg_id": "x", "action_type": "y"}, success=True, duration_ms=5
            )


# ---------------------------------------------------------------------------
# Periodic loop respects shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPeriodicLoop:
    async def test_loop_exits_on_shutdown(self) -> None:
        shutdown = asyncio.Event()
        # Force run() to be a no-op.
        with patch.object(drain, "run", AsyncMock(return_value={"claimed": 0})):
            shutdown.set()  # exit immediately
            await drain.periodic_loop(shutdown)
