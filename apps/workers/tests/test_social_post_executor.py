"""Tests for ``selva_workers.jobs.social_post_executor``.

Covers the contract documented in the executor's module docstring:

- ``_claim_due_rows`` SQL shape (FOR UPDATE SKIP LOCKED, action_type
  filter, status='pending', scheduled_for <= NOW(), HITL filter).
- ``_dispatch_row`` routes platform → tool name correctly.
- Rate-limit error → reschedule (no retry_count bump).
- Transient failure → exponential backoff + retry_count++.
- Dead letter when retry_count + 1 >= max_retries.
- HITL pending row gets skipped at the SQL filter (verified by SQL
  text containing the right WHERE clause).
- Malformed payload → permanent failure (no retry churn).
- Unknown platform → permanent failure.
- Executor never crashes on tool exception.
- ``_emit_dispatch_event`` falls back to log-line when emitter raises.
- Periodic loop respects shutdown signal.

The DB layer is mocked via a tiny ``FakeConnection`` /
``FakeCursor`` because the worker test suite is not wired to a real
Postgres — `pytest-postgresql` would be a heavier setup than this
single-file PR justifies.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_workers.jobs import social_post_executor as executor

# ---------------------------------------------------------------------------
# Fake psycopg async connection — minimal slice the executor uses.
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Implements the slice of ``psycopg.AsyncCursor`` the executor uses."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._rows = rows or []
        self.executed: list[tuple[str, dict[str, Any]]] = []
        # Mimic ``cursor.description`` — list of objects with a ``.name``
        # attr. Set externally per-test before fetchall is called.
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
    """Implements the slice of ``psycopg.AsyncConnection`` the executor uses.

    Each call to ``cursor()`` returns a fresh ``_FakeCursor``. Tests can
    inspect ``self.cursors`` for a chronological list of every cursor
    that was opened, with their executed SQL.
    """

    def __init__(self, claim_rows: list[dict[str, Any]] | None = None) -> None:
        self.claim_rows = claim_rows or []
        self.cursors: list[_FakeCursor] = []
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        # The executor calls _claim_due_rows first (returns rows) then
        # one mark_* per row (returns no rows). We dispatch by the
        # number of cursors handed out so the first cursor has the
        # claim payload and the rest are no-op.
        if not self.cursors:
            cur = _FakeCursor(rows=self._encode_claim_rows())
            cur.description = [
                MagicMock(name="d_id", spec=["name"]),
                MagicMock(name="d_action_type", spec=["name"]),
                MagicMock(name="d_payload", spec=["name"]),
                MagicMock(name="d_retry_count", spec=["name"]),
                MagicMock(name="d_max_retries", spec=["name"]),
                MagicMock(name="d_playbook_id", spec=["name"]),
                MagicMock(name="d_hitl_status", spec=["name"]),
                MagicMock(name="d_persona_id", spec=["name"]),
                MagicMock(name="d_org_id", spec=["name"]),
            ]
            for desc, name in zip(
                cur.description,
                [
                    "id",
                    "action_type",
                    "payload",
                    "retry_count",
                    "max_retries",
                    "playbook_id",
                    "hitl_status",
                    "persona_id",
                    "org_id",
                ],
                strict=False,
            ):
                desc.name = name
        else:
            cur = _FakeCursor(rows=[])
        self.cursors.append(cur)
        return cur

    def _encode_claim_rows(self) -> list[tuple[Any, ...]]:
        out: list[tuple[Any, ...]] = []
        for r in self.claim_rows:
            out.append(
                (
                    r.get("id"),
                    r.get("action_type", "social_post"),
                    json.dumps(r.get("payload", {})),
                    r.get("retry_count", 0),
                    r.get("max_retries", 3),
                    r.get("playbook_id"),
                    r.get("hitl_status"),
                    r.get("persona_id"),
                    r.get("org_id", "default"),
                )
            )
        return out

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# Fake tool — implements ``execute()`` returning a configurable ToolResult.
# ---------------------------------------------------------------------------


class _FakeToolResult:
    """Mimics ``selva_tools.base.ToolResult`` enough for the executor."""

    def __init__(self, success: bool = True, error: str | None = None) -> None:
        self.success = success
        self.error = error
        self.output = ""
        self.data: dict[str, Any] = {}


class _FakeTool:
    def __init__(self, result: _FakeToolResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> _FakeToolResult:
        self.calls.append(kwargs)
        return self._result


def _patched_registry(tool_results: dict[str, _FakeToolResult]):
    """Build a patch that swaps ``selva_tools.get_tool_registry`` for a
    fake whose ``.get(name)`` returns one of the supplied tools.

    Returns the (patch_context, fake_tools_by_name) tuple.
    """
    fake_tools = {name: _FakeTool(result) for name, result in tool_results.items()}

    fake_registry = MagicMock()
    fake_registry.get.side_effect = lambda name: fake_tools.get(name)

    return (
        patch(
            "selva_tools.get_tool_registry",
            return_value=fake_registry,
        ),
        fake_tools,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip env vars that affect _get_database_url so each test starts
    from a known state."""
    for var in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _silence_event_emitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out the event emitter so tests never make a real HTTP call.

    The executor imports ``emit_event`` at function-call time; we patch
    the function inside its module so the import resolves to our stub.
    """
    stub = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "selva_workers.event_emitter.emit_event",
        stub,
    )


# ---------------------------------------------------------------------------
# SQL shape — verifies the drain query is what the audit asked for.
# ---------------------------------------------------------------------------


class TestDrainQueryShape:
    """The SQL is module-level so the audit can grep for the contract.

    We assert on substring presence rather than the full text so adding
    a comment or whitespace tweak doesn't break the test — but the
    semantic guarantees (FOR UPDATE SKIP LOCKED, HITL filter, ordering,
    LIMIT) MUST stay.
    """

    def test_uses_for_update_skip_locked(self) -> None:
        assert "FOR UPDATE SKIP LOCKED" in executor._CLAIM_DUE_ROWS_SQL

    def test_filters_action_type_social_post(self) -> None:
        assert "action_type = %(action_type)s" in executor._CLAIM_DUE_ROWS_SQL

    def test_filters_pending_only(self) -> None:
        assert "status = 'pending'" in executor._CLAIM_DUE_ROWS_SQL

    def test_filters_scheduled_for_due(self) -> None:
        assert "scheduled_for <= NOW()" in executor._CLAIM_DUE_ROWS_SQL

    def test_skips_pending_hitl_rows(self) -> None:
        # The audit explicitly required "if the row's playbook requires
        # approval and approval status isn't approved, skip the row".
        sql = executor._CLAIM_DUE_ROWS_SQL
        assert "playbook_id IS NULL" in sql
        assert "hitl_status = 'approved'" in sql

    def test_orders_by_scheduled_for(self) -> None:
        assert "ORDER BY scheduled_for" in executor._CLAIM_DUE_ROWS_SQL

    def test_limits_batch_size(self) -> None:
        assert "LIMIT %(limit)s" in executor._CLAIM_DUE_ROWS_SQL

    def test_transitions_to_in_flight(self) -> None:
        # The CTE pattern flips the row to in_flight in the same
        # statement that selects it — that's the lock claim.
        assert "status = 'in_flight'" in executor._CLAIM_DUE_ROWS_SQL


# ---------------------------------------------------------------------------
# _build_tool_kwargs — platform → tool kwargs translation
# ---------------------------------------------------------------------------


class TestBuildToolKwargs:
    def test_mastodon_required_fields(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "mastodon",
            {"instance": "fosstodon.org", "status": "hello"},
            persona_id="madfam",
        )
        assert kwargs == {
            "instance": "fosstodon.org",
            "status": "hello",
            "persona_id": "madfam",
        }

    def test_mastodon_forwards_optional_fields(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "mastodon",
            {
                "instance": "fosstodon.org",
                "status": "hello",
                "visibility": "public",
                "content_warning": "spoilers",
                "sensitive": True,
            },
            persona_id="madfam",
        )
        assert kwargs is not None
        assert kwargs["visibility"] == "public"
        assert kwargs["content_warning"] == "spoilers"
        assert kwargs["sensitive"] is True

    def test_mastodon_missing_status_returns_none(self) -> None:
        # _build_tool_kwargs returns None for malformed payloads — the
        # caller maps that to a permanent failure (no retry churn).
        assert (
            executor._build_tool_kwargs(
                "mastodon",
                {"instance": "fosstodon.org"},
                persona_id="madfam",
            )
            is None
        )

    def test_mastodon_missing_instance_returns_none(self) -> None:
        assert (
            executor._build_tool_kwargs(
                "mastodon", {"status": "hello"}, persona_id="madfam"
            )
            is None
        )

    def test_bluesky_required_text(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "bluesky", {"text": "hi"}, persona_id="madfam"
        )
        assert kwargs == {"text": "hi", "persona_id": "madfam"}

    def test_bluesky_status_alias_for_text(self) -> None:
        # Tolerate ``status`` as an alias for ``text`` so the same row
        # shape works on mastodon AND bluesky.
        kwargs = executor._build_tool_kwargs(
            "bluesky", {"status": "hi"}, persona_id="madfam"
        )
        assert kwargs is not None
        assert kwargs["text"] == "hi"

    def test_reddit_required_fields(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "reddit",
            {"subreddit": "saas", "title": "t", "body": "b"},
            persona_id="madfam",
        )
        assert kwargs is not None
        assert kwargs["subreddit"] == "saas"

    def test_reddit_missing_body_returns_none(self) -> None:
        assert (
            executor._build_tool_kwargs(
                "reddit",
                {"subreddit": "saas", "title": "t"},
                persona_id="madfam",
            )
            is None
        )

    def test_email_required_fields(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "email",
            {"recipient": "u@example.com", "subject": "s", "body": "b"},
            persona_id=None,
        )
        assert kwargs is not None
        assert kwargs["recipient"] == "u@example.com"

    def test_persona_id_default(self) -> None:
        kwargs = executor._build_tool_kwargs(
            "bluesky", {"text": "hi"}, persona_id=None
        )
        assert kwargs is not None
        assert kwargs["persona_id"] == "default"


# ---------------------------------------------------------------------------
# _is_rate_limit_error — heuristic for the social tools' rate-limit shape
# ---------------------------------------------------------------------------


class TestIsRateLimitError:
    @pytest.mark.parametrize(
        "msg",
        [
            "Mastodon rate-limit hit for fosstodon.org: another post was made recently",
            "Bluesky rate-limit hit for persona madfam (resets in ~1234s)",
            "Reddit rate-limit hit for r/saas",
            "RATE LIMIT exceeded",  # spaced + uppercase variant
        ],
    )
    def test_recognises_rate_limit_messages(self, msg: str) -> None:
        assert executor._is_rate_limit_error(msg) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "ToolNotConfiguredError: REDDIT_CLIENT_ID missing",
            "Mastodon submit failed: HTTPError: 502 Bad Gateway",
            "instance is required",
        ],
    )
    def test_rejects_non_rate_limit_messages(self, msg: str) -> None:
        assert executor._is_rate_limit_error(msg) is False


# ---------------------------------------------------------------------------
# _dispatch_row — full per-row dispatch behavior
# ---------------------------------------------------------------------------


class TestDispatchRow:
    @pytest.mark.asyncio
    async def test_unknown_platform_is_permanent_failure(self) -> None:
        # No registry patch — _dispatch_row should bail before touching it.
        outcome = await executor._dispatch_row(
            {
                "id": "row-1",
                "payload": {"platform": "tiktok", "content": "x"},
                "persona_id": "madfam",
            }
        )
        assert outcome.success is False
        assert outcome.permanent is True
        assert "tiktok" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_missing_platform_is_permanent_failure(self) -> None:
        outcome = await executor._dispatch_row(
            {"id": "row-1", "payload": {"content": "x"}, "persona_id": "madfam"}
        )
        assert outcome.success is False
        assert outcome.permanent is True

    @pytest.mark.asyncio
    async def test_missing_required_field_is_permanent_failure(self) -> None:
        # mastodon requires status — leave it out
        ctx, _ = _patched_registry(
            {"mastodon_post": _FakeToolResult(success=True)}
        )
        with ctx:
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {"platform": "mastodon", "instance": "x.org"},
                    "persona_id": "madfam",
                }
            )
        assert outcome.permanent is True

    @pytest.mark.asyncio
    async def test_tool_success_returns_success_outcome(self) -> None:
        ctx, fake_tools = _patched_registry(
            {"mastodon_post": _FakeToolResult(success=True)}
        )
        with ctx:
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {
                        "platform": "mastodon",
                        "instance": "fosstodon.org",
                        "status": "hello",
                    },
                    "persona_id": "madfam",
                }
            )
        assert outcome.success is True
        assert fake_tools["mastodon_post"].calls == [
            {
                "instance": "fosstodon.org",
                "status": "hello",
                "persona_id": "madfam",
            }
        ]

    @pytest.mark.asyncio
    async def test_tool_rate_limit_marks_rate_limited(self) -> None:
        ctx, _ = _patched_registry(
            {
                "mastodon_post": _FakeToolResult(
                    success=False,
                    error="Mastodon rate-limit hit for fosstodon.org: ...",
                )
            }
        )
        with ctx:
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {
                        "platform": "mastodon",
                        "instance": "fosstodon.org",
                        "status": "hi",
                    },
                    "persona_id": "madfam",
                }
            )
        assert outcome.success is False
        assert outcome.rate_limited is True
        assert outcome.permanent is False

    @pytest.mark.asyncio
    async def test_tool_other_failure_is_transient(self) -> None:
        ctx, _ = _patched_registry(
            {
                "mastodon_post": _FakeToolResult(
                    success=False, error="Mastodon submit failed: 502"
                )
            }
        )
        with ctx:
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {
                        "platform": "mastodon",
                        "instance": "x.org",
                        "status": "hi",
                    },
                    "persona_id": "madfam",
                }
            )
        assert outcome.success is False
        assert outcome.rate_limited is False
        assert outcome.permanent is False

    @pytest.mark.asyncio
    async def test_tool_raising_exception_is_caught(self) -> None:
        # A rogue tool that raises must NOT take down the executor —
        # the drain has 49 other rows to process and a single bad
        # tool can't be allowed to block them.
        class _RogueTool:
            audience = None

            async def execute(self, **_kwargs: Any) -> Any:
                raise RuntimeError("ToolNotConfiguredError-equivalent")

        fake_registry = MagicMock()
        fake_registry.get.return_value = _RogueTool()

        with patch(
            "selva_tools.get_tool_registry", return_value=fake_registry
        ):
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {
                        "platform": "mastodon",
                        "instance": "x.org",
                        "status": "hi",
                    },
                    "persona_id": "madfam",
                }
            )

        assert outcome.success is False
        assert outcome.permanent is False  # Transient — try again later.
        assert "RuntimeError" in (outcome.error or "")


# ---------------------------------------------------------------------------
# _record_outcome — terminal status writes
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    @pytest.mark.asyncio
    async def test_success_marks_completed(self) -> None:
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "mastodon"},
                "retry_count": 0,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(success=True),
            summary,
        )
        assert summary["completed"] == 1
        # The cursor recorded a mark_completed UPDATE.
        assert any(
            "status = 'completed'" in cur.executed[0][0]
            for cur in conn.cursors
            if cur.executed
        )

    @pytest.mark.asyncio
    async def test_rate_limit_reschedules_30min_no_retry_bump(self) -> None:
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        before = datetime.now(UTC)
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "mastodon"},
                "retry_count": 0,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(
                success=False, error="rate-limit hit", rate_limited=True
            ),
            summary,
        )
        assert summary["rescheduled"] == 1
        # Find the UPDATE that wrote scheduled_for; assert it's ~30min ahead.
        reschedule_call = None
        for cur in conn.cursors:
            for sql, params in cur.executed:
                if "scheduled_for = %(scheduled_for)s" in sql and "retry_count" not in sql:
                    reschedule_call = params
                    break
        assert reschedule_call is not None, "expected a reschedule UPDATE"
        new_when = reschedule_call["scheduled_for"]
        delta = new_when - before
        # Allow a small slack — clock skew between recording the
        # ``before`` timestamp and the executor's ``datetime.now()``.
        assert (
            timedelta(seconds=29 * 60) <= delta <= timedelta(seconds=31 * 60)
        ), f"expected ~30min reschedule, got {delta}"

    @pytest.mark.asyncio
    async def test_transient_failure_increments_retry_count(self) -> None:
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "mastodon"},
                "retry_count": 1,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(success=False, error="502 bad gateway"),
            summary,
        )
        assert summary["retried"] == 1
        # The retry write should set retry_count to 2.
        retry_call = None
        for cur in conn.cursors:
            for sql, params in cur.executed:
                if "retry_count = %(retry_count)s" in sql:
                    retry_call = params
                    break
        assert retry_call is not None
        assert retry_call["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_dead_letter_when_retries_exhausted(self) -> None:
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        # retry_count + 1 = max_retries → this attempt is the last.
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "mastodon"},
                "retry_count": 2,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(success=False, error="terminal"),
            summary,
        )
        assert summary["failed"] == 1
        assert any(
            "status = 'failed'" in cur.executed[0][0]
            for cur in conn.cursors
            if cur.executed
        )

    @pytest.mark.asyncio
    async def test_permanent_outcome_skips_retry(self) -> None:
        # Even with retry_count=0 and max_retries=3, a permanent
        # outcome (malformed payload) should jump to failed.
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "tiktok"},
                "retry_count": 0,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(
                success=False, error="unknown platform", permanent=True
            ),
            summary,
        )
        assert summary["failed"] == 1
        assert summary["retried"] == 0

    @pytest.mark.asyncio
    async def test_last_error_truncated(self) -> None:
        conn = _FakeConnection()
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        long_error = "x" * 5000
        await executor._record_outcome(
            conn,
            {
                "id": "row-1",
                "payload": {"platform": "mastodon"},
                "retry_count": 2,
                "max_retries": 3,
                "persona_id": "madfam",
                "org_id": "default",
            },
            executor._DispatchOutcome(success=False, error=long_error),
            summary,
        )
        # Last_error written somewhere — find it in the failed UPDATE.
        for cur in conn.cursors:
            for _sql, params in cur.executed:
                if "last_error" in params:
                    assert (
                        len(params["last_error"])
                        <= executor.LAST_ERROR_TRUNCATE_CHARS
                    )
                    return
        pytest.fail("no UPDATE captured last_error")


# ---------------------------------------------------------------------------
# _emit_dispatch_event — observability fallthrough
# ---------------------------------------------------------------------------


class TestEmitDispatchEvent:
    @pytest.mark.asyncio
    async def test_falls_through_to_log_when_emitter_raises(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the emit_event import (inside _emit_dispatch_event) to
        # raise — the executor must still log the event so log-shipping
        # picks it up.
        monkeypatch.setattr(
            "selva_workers.event_emitter.emit_event",
            AsyncMock(side_effect=RuntimeError("nexus-api unreachable")),
        )

        with caplog.at_level("INFO"):
            await executor._emit_dispatch_event(
                row={"id": "row-1", "org_id": "default"},
                platform="mastodon",
                persona_id="madfam",
                success=True,
            )

        assert any(
            "scheduled_action_dispatched" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_includes_extra_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO"):
            await executor._emit_dispatch_event(
                row={"id": "row-1", "org_id": "default"},
                platform="bluesky",
                persona_id="madfam",
                success=False,
                extra={"rate_limited": True},
            )
        # extras land in the JSON payload of the log line.
        joined = " ".join(rec.message for rec in caplog.records)
        assert "rate_limited" in joined


# ---------------------------------------------------------------------------
# _claim_due_rows — JSON payload normalization + concurrency contract
# ---------------------------------------------------------------------------


class TestClaimDueRows:
    @pytest.mark.asyncio
    async def test_decodes_json_string_payload(self) -> None:
        conn = _FakeConnection(
            claim_rows=[
                {
                    "id": "row-1",
                    "payload": {"platform": "mastodon", "status": "hi"},
                    "retry_count": 0,
                    "max_retries": 3,
                    "playbook_id": None,
                    "hitl_status": None,
                    "persona_id": "madfam",
                    "org_id": "default",
                }
            ]
        )
        rows = await executor._claim_due_rows(conn)
        assert len(rows) == 1
        # _FakeConnection JSON-encodes the payload column on its way out;
        # _claim_due_rows must decode it back to a dict.
        assert isinstance(rows[0]["payload"], dict)
        assert rows[0]["payload"]["platform"] == "mastodon"

    @pytest.mark.asyncio
    async def test_malformed_payload_returns_empty_dict(self) -> None:
        # If the JSONB column ever returns garbage (shouldn't happen
        # post-migration but defense in depth) the executor must not
        # crash — the row gets a sentinel payload that _dispatch_row
        # then maps to a permanent failure.
        class _GarbageCursor(_FakeCursor):
            async def fetchall(self) -> list[tuple[Any, ...]]:
                return [
                    ("row-1", "social_post", "{not-valid-json", 0, 3, None, None, None, "default")
                ]

        conn = _FakeConnection()

        # ``_FakeConnection.cursor`` is sync (matches the executor's
        # ``async with conn.cursor()`` usage where ``cursor()`` returns
        # an async context manager directly, not a coroutine).
        def _broken_cursor(*_a: Any, **_k: Any) -> _GarbageCursor:
            cur = _GarbageCursor()
            cur.description = []
            for name in [
                "id",
                "action_type",
                "payload",
                "retry_count",
                "max_retries",
                "playbook_id",
                "hitl_status",
                "persona_id",
                "org_id",
            ]:
                desc = MagicMock(spec=["name"])
                desc.name = name
                cur.description.append(desc)
            conn.cursors.append(cur)
            return cur

        with patch.object(conn, "cursor", _broken_cursor):
            rows = await executor._claim_due_rows(conn)
        assert len(rows) == 1
        # Falls back to empty dict so platform-resolution returns a
        # permanent failure (vs crashing the whole drain).
        assert rows[0]["payload"] == {"_malformed": "{not-valid-json"} or rows[0][
            "payload"
        ] == {}

    @pytest.mark.asyncio
    async def test_passes_action_type_and_limit_params(self) -> None:
        conn = _FakeConnection()
        await executor._claim_due_rows(conn, batch_size=42)
        sql, params = conn.cursors[0].executed[0]
        assert params["action_type"] == "social_post"
        assert params["limit"] == 42


# ---------------------------------------------------------------------------
# Full drain integration — _drain_once with a HITL-skipped row
# ---------------------------------------------------------------------------


class TestDrainOnce:
    @pytest.mark.asyncio
    async def test_pending_hitl_row_filtered_at_sql_level(self) -> None:
        """The drain query's WHERE clause excludes rows with a
        non-approved playbook gate. We assert this by feeding the
        fake connection ZERO rows (mimicking the SQL filter having
        already kicked them out) and verifying the executor doesn't
        try to dispatch anything."""
        conn = _FakeConnection(claim_rows=[])
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        # No tool patch — if _drain_once tried to dispatch we'd see
        # an ImportError-equivalent or AttributeError.
        await executor._drain_once(conn, summary)
        assert summary["claimed"] == 0
        assert summary["completed"] == 0

    @pytest.mark.asyncio
    async def test_drain_once_dispatches_each_row(self) -> None:
        conn = _FakeConnection(
            claim_rows=[
                {
                    "id": "row-1",
                    "payload": {
                        "platform": "mastodon",
                        "instance": "x.org",
                        "status": "hi",
                    },
                    "retry_count": 0,
                    "max_retries": 3,
                    "playbook_id": None,
                    "hitl_status": None,
                    "persona_id": "madfam",
                    "org_id": "default",
                },
                {
                    "id": "row-2",
                    "payload": {
                        "platform": "bluesky",
                        "text": "hi",
                    },
                    "retry_count": 0,
                    "max_retries": 3,
                    "playbook_id": None,
                    "hitl_status": None,
                    "persona_id": "madfam",
                    "org_id": "default",
                },
            ]
        )
        summary = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "rescheduled": 0,
            "retried": 0,
            "skipped_hitl": 0,
            "errors": [],
        }
        ctx, fake_tools = _patched_registry(
            {
                "mastodon_post": _FakeToolResult(success=True),
                "bluesky_post": _FakeToolResult(success=True),
            }
        )
        with ctx:
            await executor._drain_once(conn, summary)
        assert summary["claimed"] == 2
        assert summary["completed"] == 2
        assert len(fake_tools["mastodon_post"].calls) == 1
        assert len(fake_tools["bluesky_post"].calls) == 1


# ---------------------------------------------------------------------------
# run() entrypoint — DB URL resolution + connection failure
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_no_database_url_returns_empty_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _isolate_env already strips DATABASE_URL; also stub get_settings
        # so it can't pick a default.
        from selva_workers.config import Settings

        def _stub_settings() -> Settings:
            return Settings(database_url=None)

        monkeypatch.setattr(
            "selva_workers.config.get_settings", _stub_settings
        )

        result = await executor.run()
        assert result["claimed"] == 0
        assert result["completed"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_to_psycopg_url_strips_asyncpg_driver(self) -> None:
        assert (
            executor._to_psycopg_url("postgresql+asyncpg://u:p@h/db")
            == "postgresql://u:p@h/db"
        )
        # Non-asyncpg URLs pass through untouched.
        assert (
            executor._to_psycopg_url("postgresql://u:p@h/db")
            == "postgresql://u:p@h/db"
        )


# ---------------------------------------------------------------------------
# Periodic loop — shutdown signal + tick failure resilience
# ---------------------------------------------------------------------------


class TestPeriodicLoop:
    @pytest.mark.asyncio
    async def test_shutdown_event_breaks_loop_quickly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loop's ``asyncio.wait_for(shutdown.wait(), timeout=60)``
        wakes up early when shutdown is set — so a SIGTERM doesn't
        have to wait the full minute."""
        # Make run() a no-op so the loop just waits.
        monkeypatch.setattr(
            executor,
            "run",
            AsyncMock(return_value={"claimed": 0}),
        )
        shutdown = asyncio.Event()

        # Schedule shutdown for very soon after loop start.
        async def _signal() -> None:
            await asyncio.sleep(0.05)
            shutdown.set()

        await asyncio.gather(
            executor.periodic_loop(shutdown),
            _signal(),
        )
        # If we reach here without timing out the loop respected the signal.

    @pytest.mark.asyncio
    async def test_tick_failure_does_not_kill_loop(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A single bad tick (DB blip) must not stop the loop — we'd
        rather skip a minute than drop the schedule."""
        call_count = {"n": 0}

        async def _flaky_run() -> dict[str, Any]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient DB error")
            return {"claimed": 0}

        monkeypatch.setattr(executor, "run", _flaky_run)
        # Shrink the interval so the test doesn't take 60s.
        monkeypatch.setattr(executor, "DRAIN_INTERVAL_SECONDS", 0.05)

        shutdown = asyncio.Event()

        async def _signal() -> None:
            # Let the loop tick at least 3 times (first raises, next two run).
            await asyncio.sleep(0.25)
            shutdown.set()

        with caplog.at_level("ERROR"):
            await asyncio.gather(
                executor.periodic_loop(shutdown),
                _signal(),
            )

        # We should see at least one "tick failed" exception log AND at
        # least one successful tick (call_count >= 2).
        assert call_count["n"] >= 2
        assert any(
            "Scheduled action periodic loop tick failed" in rec.message
            for rec in caplog.records
        )
