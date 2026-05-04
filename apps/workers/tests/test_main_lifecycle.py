"""Tests for selva_workers.__main__ — worker process entry point.

Coverage targets the task lifecycle driver in __main__.py:
- ``process_task()`` — graph-status → API-status mapping for completed,
  blocked, denied, error, timeout, and unhandled-exception paths
- ``run_graph_with_interrupts()`` — the interrupt() / approval / resume loop
- ``_publish_agent_status()`` — Redis pubsub for Colyseus status sync
- ``_fetch_agent_skills()`` — cached HTTP GET with org_id header
- ``_run_custom_with_streaming()`` — astream-based custom workflow runner
- ``_periodic_cleanup()`` — periodic stale-worktree GC
- ``_handle_signal()`` — SIGTERM/SIGINT shutdown latch
- ``main()`` — Redis connect, group setup, claim_stalled, consumer loop,
  XREADGROUP, exponential backoff, graceful drain
- Per-graph-type ``initial_state`` builders for crm/deployment/puppeteer/
  meeting/accounting/billing/intelligence/operations/sales/research

All Redis, HTTP, LangGraph, and learning-hook calls are mocked — no real
Redis, no real nexus-api, no real LLM. Async polling loops use the same
``await asyncio.sleep(0)`` yield pattern as test_interrupt_handler.py to
avoid busy-loop hangs under asyncio.wait_for().
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    graph_type: str = "coding",
    task_id: str = "lifecycle-1",
    description: str = "test task",
    payload: dict | None = None,
    **extra: Any,
) -> dict:
    base = {
        "task_id": task_id,
        "graph_type": graph_type,
        "description": description,
        "assigned_agent_ids": ["agent-1"],
        "payload": payload or {},
        "request_id": "req-1",
        "org_id": "org-tenant-A",
    }
    base.update(extra)
    return base


def _patch_io(
    *,
    graph_result: dict | None = None,
    graph_side_effect: BaseException | None = None,
    fetch_skills: list | None = None,
):
    """Bundle up the fire-and-forget I/O patches for process_task tests."""
    skills = fetch_skills if fetch_skills is not None else []

    run_graph_kwargs: dict[str, Any] = {"new_callable": AsyncMock}
    if graph_side_effect is not None:
        run_graph_kwargs["side_effect"] = graph_side_effect
    else:
        run_graph_kwargs["return_value"] = graph_result or {"status": "completed"}

    return [
        patch("selva_workers.__main__._update_task_status", new_callable=AsyncMock),
        patch("selva_workers.__main__._publish_agent_status", new_callable=AsyncMock),
        patch("selva_workers.__main__._emit_event", new_callable=AsyncMock),
        patch(
            "selva_workers.__main__._fetch_agent_skills",
            new_callable=AsyncMock,
            return_value=skills,
        ),
        patch("selva_workers.__main__.run_graph_with_interrupts", **run_graph_kwargs),
        patch("selva_workers.__main__.InterruptHandler"),
    ]


def _enter_all(ctx_mgrs: list) -> tuple:
    """Open every CM in order and return the entered values."""
    return tuple(cm.__enter__() for cm in ctx_mgrs)


def _exit_all(ctx_mgrs: list) -> None:
    for cm in reversed(ctx_mgrs):
        cm.__exit__(None, None, None)


def _stub_signal_handler(loop: asyncio.AbstractEventLoop):
    """Replace add_signal_handler with a no-op so main() can be unit-tested
    without touching real OS signal plumbing.

    Returns a (restore_fn) callable.
    """
    original = loop.add_signal_handler
    loop.add_signal_handler = lambda *a, **kw: None  # type: ignore[method-assign]

    def _restore() -> None:
        loop.add_signal_handler = original  # type: ignore[method-assign]

    return _restore


# ===========================================================================
# process_task: graph-status → API-status mapping
# ===========================================================================


class TestProcessTaskStatusMapping:
    """Verify that graph_status → api_status maps correctly for every branch."""

    @pytest.mark.asyncio
    async def test_completed_path_marks_task_completed(self) -> None:
        """status=completed → api_status=completed → task.completed event."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "completed", "result": {"ok": True}})
        (mock_status, _, mock_emit, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        # Two status calls: "running" then final.
        assert mock_status.await_count >= 2
        final = mock_status.await_args_list[-1]
        assert final[0][2] == "completed"
        emit_kwargs = mock_emit.await_args_list[-1].kwargs
        assert emit_kwargs["event_type"] == "task.completed"

    @pytest.mark.asyncio
    async def test_pushed_path_also_completes(self) -> None:
        """graph_status=pushed → api_status=completed (alias)."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "pushed", "result": {}})
        (mock_status, _, _, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "completed"

    @pytest.mark.asyncio
    async def test_blocked_path_marks_failed(self) -> None:
        """graph_status=blocked → api_status=failed."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "blocked"})
        (mock_status, _, mock_emit, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "failed"
        assert mock_emit.await_args_list[-1].kwargs["event_type"] == "task.failed"

    @pytest.mark.asyncio
    async def test_denied_path_marks_failed(self) -> None:
        """graph_status=denied → api_status=failed."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "denied"})
        (mock_status, _, _, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "failed"

    @pytest.mark.asyncio
    async def test_error_path_marks_failed(self) -> None:
        """graph_status=error → api_status=failed."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "error", "result": {"err": "x"}})
        (mock_status, _, _, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "failed"

    @pytest.mark.asyncio
    async def test_unknown_status_falls_through_to_completed(self) -> None:
        """graph_status outside the known set defaults to completed."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_result={"status": "weird-unknown-status"})
        (mock_status, _, _, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "completed"


# ===========================================================================
# process_task: timeout & exception handling
# ===========================================================================


class TestProcessTaskFailurePaths:
    @pytest.mark.asyncio
    async def test_timeout_marks_failed_with_timeout_message(self) -> None:
        """asyncio.wait_for TimeoutError → status=failed with 'Timed out' error."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_side_effect=TimeoutError("timed out"))
        (mock_status, _, mock_emit, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            with patch("selva_workers.__main__.get_task_timeout", return_value=5):
                await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        final = mock_status.await_args_list[-1]
        assert final[0][2] == "failed"
        err_msg = final.kwargs.get("error_message", "")
        assert "Timed out" in err_msg
        emit_types = [c.kwargs.get("event_type") for c in mock_emit.await_args_list]
        assert "task.timeout" in emit_types

    @pytest.mark.asyncio
    async def test_unhandled_exception_marks_failed(self) -> None:
        """Generic graph exception → status=failed with exception details."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(graph_side_effect=RuntimeError("boom from graph"))
        (mock_status, _, mock_emit, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()
            await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        final = mock_status.await_args_list[-1]
        assert final[0][2] == "failed"
        err_msg = final.kwargs.get("error_message", "")
        assert "boom from graph" in err_msg
        emit_types = [c.kwargs.get("event_type") for c in mock_emit.await_args_list]
        assert "task.failed" in emit_types


# ===========================================================================
# process_task: unknown graph type & custom workflow paths
# ===========================================================================


class TestProcessTaskGraphSelection:
    @pytest.mark.asyncio
    async def test_unknown_graph_type_logs_and_returns(self) -> None:
        """An unknown graph_type → log error and return without status update."""
        from selva_workers.__main__ import process_task

        with (
            patch(
                "selva_workers.__main__._update_task_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch("selva_workers.__main__._publish_agent_status", new_callable=AsyncMock),
            patch("selva_workers.__main__._emit_event", new_callable=AsyncMock),
            patch(
                "selva_workers.__main__._fetch_agent_skills",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await process_task(_task(graph_type="this-graph-does-not-exist"))

        mock_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_workflow_missing_yaml_returns_early(self) -> None:
        """custom graph_type without workflow_yaml → log error + return."""
        from selva_workers.__main__ import process_task

        with (
            patch(
                "selva_workers.__main__._update_task_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch("selva_workers.__main__._publish_agent_status", new_callable=AsyncMock),
            patch("selva_workers.__main__._emit_event", new_callable=AsyncMock),
            patch(
                "selva_workers.__main__._fetch_agent_skills",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await process_task(_task(graph_type="custom", task_id="custom-no-yaml"))

        mock_status.assert_not_called()


# ===========================================================================
# process_task: per-graph-type initial state coverage (lines 362-445)
# ===========================================================================


class TestProcessTaskGraphInitialState:
    """Drive process_task once per non-coding graph type to walk the
    initial_state-builder branches in lines 356-445.

    We capture the initial state via run_graph_with_interrupts mock so we
    can assert the right keys are populated for each graph type.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("graph_type", "payload", "expected_keys"),
        [
            ("research", {}, {"query", "sources"}),
            (
                "crm",
                {
                    "contact_email": "x@y.com",
                    "contact_name": "X",
                    "product_interest": "P",
                    "lead_score": 80,
                    "lead_id": "L1",
                },
                {"recipient", "crm_action", "lead_id", "utm_source"},
            ),
            (
                "deployment",
                {"service": "api", "environment": "prod", "image_tag": "v1"},
                {"service", "environment", "image_tag"},
            ),
            (
                "puppeteer",
                {"max_parallel": 5},
                {"subtasks", "subtask_results", "max_parallel", "selected_agents"},
            ),
            (
                "meeting",
                {"recording_url": "rec.mp3"},
                {"transcript", "summary", "action_items", "recording_url"},
            ),
            (
                "accounting",
                {"period": "2026-04", "rfc": "ABCD910101000"},
                {"period", "rfc", "regime", "transactions"},
            ),
            (
                "billing",
                {"emisor_rfc": "E", "receptor_rfc": "R", "conceptos": []},
                {"emisor_rfc", "receptor_rfc", "conceptos", "cfdi_xml"},
            ),
            ("intelligence", {}, {"dof_results", "exchange_rate", "briefing_text"}),
            (
                "operations",
                {"sku": "S1", "tracking_numbers": ["t1"]},
                {"sku", "pedimento_number", "tracking_numbers"},
            ),
            (
                "sales",
                {"lead_id": "L1", "customer_email": "c@d.com"},
                {"lead_id", "lead_data", "cotizacion", "customer_email"},
            ),
        ],
    )
    async def test_initial_state_built_for_graph_type(
        self,
        graph_type: str,
        payload: dict,
        expected_keys: set,
    ) -> None:
        from selva_workers.__main__ import process_task

        captured_state: dict = {}

        async def _capture(compiled, initial_state, *args, **kwargs):  # noqa: ANN001
            captured_state.update(initial_state)
            return {"status": "completed", "result": {}}

        cms = [
            patch("selva_workers.__main__._update_task_status", new_callable=AsyncMock),
            patch("selva_workers.__main__._publish_agent_status", new_callable=AsyncMock),
            patch("selva_workers.__main__._emit_event", new_callable=AsyncMock),
            patch(
                "selva_workers.__main__._fetch_agent_skills",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "selva_workers.__main__.run_graph_with_interrupts",
                side_effect=_capture,
            ),
            patch("selva_workers.__main__.InterruptHandler"),
        ]
        entered = _enter_all(cms)
        entered[-1].return_value = AsyncMock()
        try:
            await process_task(_task(graph_type=graph_type, payload=payload))
        finally:
            _exit_all(cms)

        for key in expected_keys:
            assert key in captured_state, f"{key} missing from initial state for {graph_type}"


# ===========================================================================
# process_task: skill-prompt build error path (lines 319-320)
# ===========================================================================


class TestProcessTaskSkillPromptError:
    @pytest.mark.asyncio
    async def test_registry_failure_does_not_break_task(self) -> None:
        """Skill registry raising should be swallowed and task still runs."""
        from selva_workers.__main__ import process_task

        cms = _patch_io(
            graph_result={"status": "completed"},
            fetch_skills=["skill-x"],
        )
        (mock_status, _, _, _, _, mock_handler_cls) = _enter_all(cms)
        try:
            mock_handler_cls.return_value = AsyncMock()

            with patch(
                "selva_skills.get_skill_registry",
                side_effect=RuntimeError("registry exploded"),
            ):
                await process_task(_task(graph_type="research"))
        finally:
            _exit_all(cms)

        assert mock_status.await_args_list[-1][0][2] == "completed"


# ===========================================================================
# _publish_agent_status — Redis publish wiring
# ===========================================================================


class TestPublishAgentStatus:
    @pytest.mark.asyncio
    async def test_no_op_for_unknown_agent(self) -> None:
        from selva_workers.__main__ import _publish_agent_status

        with patch("selva_workers.__main__.get_redis_pool") as mock_pool:
            await _publish_agent_status("unknown", "working")

        mock_pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_publishes_payload_with_status(self) -> None:
        from selva_workers.__main__ import (
            AGENT_STATUS_CHANNEL,
            _publish_agent_status,
        )

        pool = MagicMock()
        pool.execute_with_retry = AsyncMock()

        with patch("selva_workers.__main__.get_redis_pool", return_value=pool):
            await _publish_agent_status("agent-1", "working")

        pool.execute_with_retry.assert_awaited_once()
        args = pool.execute_with_retry.await_args.args
        # ("publish", channel, json_payload)
        assert args[0] == "publish"
        assert args[1] == AGENT_STATUS_CHANNEL

    @pytest.mark.asyncio
    async def test_includes_current_node_id_when_provided(self) -> None:
        from selva_workers.__main__ import _publish_agent_status

        pool = MagicMock()
        pool.execute_with_retry = AsyncMock()

        with patch("selva_workers.__main__.get_redis_pool", return_value=pool):
            await _publish_agent_status("agent-1", "working", current_node_id="plan")

        import json as _json

        payload = _json.loads(pool.execute_with_retry.await_args.args[2])
        assert payload["current_node_id"] == "plan"

    @pytest.mark.asyncio
    async def test_swallows_redis_exception(self) -> None:
        """Redis publish failure must not raise — it's fire-and-forget."""
        from selva_workers.__main__ import _publish_agent_status

        pool = MagicMock()
        pool.execute_with_retry = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("selva_workers.__main__.get_redis_pool", return_value=pool):
            await _publish_agent_status("agent-1", "working")  # must not raise


# ===========================================================================
# _fetch_agent_skills — HTTP cache wiring
# ===========================================================================


class TestFetchAgentSkills:
    @pytest.mark.asyncio
    async def test_no_op_for_unknown_agent(self) -> None:
        from selva_workers.__main__ import _fetch_agent_skills

        result = await _fetch_agent_skills("http://api", "unknown")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_skills_from_api(self) -> None:
        from selva_workers.__main__ import _fetch_agent_skills, _skill_cache

        _skill_cache.clear()

        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={"effective_skills": ["s1", "s2"], "role": "coder"}
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("selva_workers.__main__.httpx.AsyncClient", return_value=client):
            result = await _fetch_agent_skills(
                "http://api", "agent-fetch-1", org_id="org-1"
            )

        assert result == ["s1", "s2"]
        # Second call should hit the cache (no second HTTP).
        with patch("selva_workers.__main__.httpx.AsyncClient") as mock_client:
            cached = await _fetch_agent_skills("http://api", "agent-fetch-1")
        assert cached == ["s1", "s2"]
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_failure(self) -> None:
        from selva_workers.__main__ import _fetch_agent_skills, _skill_cache

        _skill_cache.clear()

        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("network kaboom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("selva_workers.__main__.httpx.AsyncClient", return_value=client):
            result = await _fetch_agent_skills("http://api", "agent-fetch-2")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_200(self) -> None:
        from selva_workers.__main__ import _fetch_agent_skills, _skill_cache

        _skill_cache.clear()

        resp = MagicMock()
        resp.status_code = 404
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("selva_workers.__main__.httpx.AsyncClient", return_value=client):
            result = await _fetch_agent_skills("http://api", "agent-fetch-3")

        assert result == []


# ===========================================================================
# run_graph_with_interrupts — the interrupt() loop
# ===========================================================================


class TestRunGraphWithInterrupts:
    @pytest.mark.asyncio
    async def test_no_pending_nodes_returns_immediately(self) -> None:
        from selva_workers.__main__ import run_graph_with_interrupts

        snapshot = MagicMock()
        snapshot.next = ()

        compiled = MagicMock()
        compiled.invoke = MagicMock(return_value={"status": "completed"})
        compiled.get_state = MagicMock(return_value=snapshot)

        handler = MagicMock()
        result = await run_graph_with_interrupts(
            compiled, {"x": 1}, "task-A", "agent-A", handler
        )
        assert result == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_resumes_after_approval(self) -> None:
        """Pending interrupt → create approval → resume → finish."""
        from selva_workers.__main__ import run_graph_with_interrupts

        interrupt_obj = MagicMock()
        interrupt_obj.value = {
            "action_category": "git_push",
            "reasoning": "needs review",
        }
        task_obj = MagicMock()
        task_obj.interrupts = [interrupt_obj]

        snap_pending = MagicMock()
        snap_pending.next = ("push_gate",)
        snap_pending.tasks = [task_obj]

        snap_done = MagicMock()
        snap_done.next = ()

        compiled = MagicMock()
        compiled.invoke = MagicMock(
            side_effect=[
                {"status": "running"},  # initial invoke
                {"status": "pushed"},  # post-resume invoke
            ]
        )
        compiled.get_state = MagicMock(side_effect=[snap_pending, snap_done])

        handler = MagicMock()
        handler.create_approval_request = AsyncMock(return_value="req-100")
        approval = MagicMock()
        approval.result = "approved"
        approval.feedback = "ship it"
        handler.wait_for_approval = AsyncMock(return_value=approval)

        with patch(
            "selva_workers.__main__._publish_agent_status", new_callable=AsyncMock
        ):
            result = await run_graph_with_interrupts(
                compiled, {"task_id": "T"}, "T", "agent-1", handler
            )

        assert result == {"status": "pushed"}
        handler.create_approval_request.assert_awaited_once()
        assert compiled.invoke.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_non_dict_interrupt_payload(self) -> None:
        """When interrupt payload is not a dict, defaults are used."""
        from selva_workers.__main__ import run_graph_with_interrupts

        interrupt_obj = MagicMock()
        interrupt_obj.value = "raw-string-payload"
        task_obj = MagicMock()
        task_obj.interrupts = [interrupt_obj]

        snap_pending = MagicMock()
        snap_pending.next = ("gate",)
        snap_pending.tasks = [task_obj]
        snap_done = MagicMock()
        snap_done.next = ()

        compiled = MagicMock()
        compiled.invoke = MagicMock(side_effect=[{}, {"status": "completed"}])
        compiled.get_state = MagicMock(side_effect=[snap_pending, snap_done])

        handler = MagicMock()
        handler.create_approval_request = AsyncMock(return_value="req-1")
        approval = MagicMock()
        approval.result = "denied"
        approval.feedback = "no"
        handler.wait_for_approval = AsyncMock(return_value=approval)

        with patch(
            "selva_workers.__main__._publish_agent_status", new_callable=AsyncMock
        ):
            result = await run_graph_with_interrupts(
                compiled, {}, "T", "agent-1", handler
            )

        assert result == {"status": "completed"}


# ===========================================================================
# _periodic_cleanup — background hourly GC
# ===========================================================================


class TestPeriodicCleanup:
    @pytest.mark.asyncio
    async def test_exits_when_shutdown_set(self) -> None:
        """Loop should exit on shutdown — verify via short-circuited sleep."""
        import selva_workers.__main__ as mod

        original = mod._shutdown
        mod._shutdown = asyncio.Event()
        mod._shutdown.set()  # already set: should exit on first loop check

        with patch("asyncio.sleep", new_callable=AsyncMock):
            try:
                await asyncio.wait_for(
                    mod._periodic_cleanup("/tmp/nope", 24), timeout=1.0
                )
            finally:
                mod._shutdown = original

    @pytest.mark.asyncio
    async def test_swallows_cleanup_exception(self) -> None:
        """A failing cleanup pass should not break the loop."""
        import selva_workers.__main__ as mod

        original = mod._shutdown
        mod._shutdown = asyncio.Event()

        sleep_calls = {"n": 0}

        async def fake_sleep(_: float) -> None:
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 1:
                mod._shutdown.set()

        with (
            patch("selva_workers.__main__.asyncio.sleep", side_effect=fake_sleep),
            patch(
                "selva_workers.__main__._cleanup_stale_worktrees",
                side_effect=RuntimeError("boom"),
            ),
        ):
            try:
                await asyncio.wait_for(
                    mod._periodic_cleanup("/tmp/nope", 24), timeout=1.0
                )
            finally:
                mod._shutdown = original


# ===========================================================================
# _handle_signal — shutdown latch
# ===========================================================================


class TestHandleSignal:
    def test_sigterm_sets_shutdown_event(self) -> None:
        import selva_workers.__main__ as mod

        original = mod._shutdown
        mod._shutdown = asyncio.Event()
        try:
            assert not mod._shutdown.is_set()
            mod._handle_signal(signal.SIGTERM)
            assert mod._shutdown.is_set()
        finally:
            mod._shutdown = original


# ===========================================================================
# _run_custom_with_streaming
# ===========================================================================


class TestRunCustomWithStreaming:
    @pytest.mark.asyncio
    async def test_streams_node_updates_with_no_interrupts(self) -> None:
        from selva_workers.__main__ import _run_custom_with_streaming

        events = [
            {"plan": {"status": "running", "step": 1}},
            {"implement": {"status": "running", "step": 2}},
            {"finish": {"status": "completed"}},
        ]

        async def fake_astream(*_args, **_kwargs):
            for ev in events:
                yield ev

        snapshot = MagicMock()
        snapshot.next = ()  # no interrupts

        compiled = MagicMock()
        compiled.astream = fake_astream
        compiled.get_state = MagicMock(return_value=snapshot)

        handler = MagicMock()

        with patch(
            "selva_workers.__main__._publish_agent_status", new_callable=AsyncMock
        ) as mock_publish:
            result = await _run_custom_with_streaming(
                compiled, {"task_id": "T"}, "T", "agent-1", handler
            )

        assert result["status"] == "completed"
        # publish_agent_status called once per node event
        assert mock_publish.await_count == len(events)


# ===========================================================================
# _cleanup_stale_worktrees — edge cases not in test_worker_concurrency
# ===========================================================================


class TestCleanupStaleWorktreesEdges:
    @pytest.mark.asyncio
    async def test_skips_files_under_worktrees(self, tmp_path) -> None:
        """Non-directory entries under _worktrees should be skipped."""
        from selva_workers.__main__ import _cleanup_stale_worktrees

        repo = tmp_path / "repo"
        wt_root = repo / "_worktrees"
        wt_root.mkdir(parents=True)
        # Create a stray file (not a directory) under _worktrees
        (wt_root / "stray.txt").write_text("not a worktree")

        removed = await _cleanup_stale_worktrees(str(tmp_path), stale_hours=24)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_skips_non_directory_worktree_root(self, tmp_path) -> None:
        """If <repo>/_worktrees exists as a file, it should be skipped."""
        from selva_workers.__main__ import _cleanup_stale_worktrees

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "_worktrees").write_text("oops")

        removed = await _cleanup_stale_worktrees(str(tmp_path), stale_hours=24)
        assert removed == 0


# ===========================================================================
# main() — entry point smoke tests
# ===========================================================================


class TestMainEntryPoint:
    @pytest.mark.asyncio
    async def test_exits_when_redis_ping_fails(self) -> None:
        """If pool.ping() returns False, main() should sys.exit(1)."""
        import selva_workers.__main__ as mod

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=False)

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch("selva_workers.__main__.TaskStreamConsumer"),
            ):
                with pytest.raises(SystemExit) as exc:
                    await mod.main()
                assert exc.value.code == 1
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_main_loop_drains_on_shutdown(self) -> None:
        """main() should set up consumer, exit on shutdown, drain tasks."""
        import selva_workers.__main__ as mod

        original_shutdown = mod._shutdown
        mod._shutdown = asyncio.Event()
        mod._shutdown.set()  # exit consumer loop immediately

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=True)
        pool.close = AsyncMock()

        consumer = MagicMock()
        consumer.ensure_group = AsyncMock()
        consumer.claim_stalled = AsyncMock(return_value=[])
        consumer.read = AsyncMock(return_value=[])
        consumer.ack = AsyncMock()

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch(
                    "selva_workers.__main__.TaskStreamConsumer",
                    return_value=consumer,
                ),
                patch("selva_workers.inference.validate_providers"),
            ):
                await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            restore()
            mod._shutdown = original_shutdown

        pool.ping.assert_awaited()
        consumer.ensure_group.assert_awaited()
        consumer.claim_stalled.assert_awaited()
        pool.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_main_processes_stalled_messages(self) -> None:
        """Stalled messages from claim_stalled should be processed + acked."""
        import selva_workers.__main__ as mod

        original_shutdown = mod._shutdown
        mod._shutdown = asyncio.Event()
        mod._shutdown.set()

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=True)
        pool.close = AsyncMock()

        stalled_task = {"task_id": "stalled-1", "graph_type": "research"}
        consumer = MagicMock()
        consumer.ensure_group = AsyncMock()
        consumer.claim_stalled = AsyncMock(return_value=[("msg-stalled-1", stalled_task)])
        consumer.read = AsyncMock(return_value=[])
        consumer.ack = AsyncMock()

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch(
                    "selva_workers.__main__.TaskStreamConsumer",
                    return_value=consumer,
                ),
                patch(
                    "selva_workers.__main__.process_task",
                    new_callable=AsyncMock,
                ) as mock_proc,
                patch("selva_workers.inference.validate_providers"),
            ):
                await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            restore()
            mod._shutdown = original_shutdown

        mock_proc.assert_awaited_once_with(stalled_task)
        consumer.ack.assert_awaited_with("msg-stalled-1")

    @pytest.mark.asyncio
    async def test_main_swallows_stalled_processing_failure(self) -> None:
        """If processing a stalled message raises, main() must continue."""
        import selva_workers.__main__ as mod

        original_shutdown = mod._shutdown
        mod._shutdown = asyncio.Event()
        mod._shutdown.set()

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=True)
        pool.close = AsyncMock()

        consumer = MagicMock()
        consumer.ensure_group = AsyncMock()
        consumer.claim_stalled = AsyncMock(
            return_value=[("msg-bad", {"task_id": "bad"})]
        )
        consumer.read = AsyncMock(return_value=[])
        consumer.ack = AsyncMock()

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch(
                    "selva_workers.__main__.TaskStreamConsumer",
                    return_value=consumer,
                ),
                patch(
                    "selva_workers.__main__.process_task",
                    side_effect=RuntimeError("stalled boom"),
                ),
                patch("selva_workers.inference.validate_providers"),
            ):
                await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            restore()
            mod._shutdown = original_shutdown

        # Pool still closed cleanly via finally block.
        pool.close.assert_awaited()


# ===========================================================================
# Custom workflow compile-error path (lines 269-275)
# ===========================================================================


class TestCustomWorkflowCompileError:
    @pytest.mark.asyncio
    async def test_compile_failure_returns_early(self) -> None:
        """If WorkflowSerializer.from_yaml raises, process_task returns
        without dispatching status updates."""
        from selva_workers.__main__ import process_task

        with (
            patch(
                "selva_workers.__main__._update_task_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch("selva_workers.__main__._publish_agent_status", new_callable=AsyncMock),
            patch("selva_workers.__main__._emit_event", new_callable=AsyncMock),
            patch(
                "selva_workers.__main__._fetch_agent_skills",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "selva_workflows.WorkflowSerializer.from_yaml",
                side_effect=ValueError("bad yaml"),
            ),
        ):
            await process_task(
                _task(
                    graph_type="custom",
                    task_id="custom-bad-yaml",
                    workflow_yaml="not: valid: yaml: at all",
                )
            )

        # No status updates because the function returned before issuing any.
        mock_status.assert_not_called()


# ===========================================================================
# _run_custom_with_streaming — interrupt + resume loop (lines 726-762)
# ===========================================================================


class TestRunCustomWithStreamingInterrupts:
    @pytest.mark.asyncio
    async def test_interrupt_then_resume_completes(self) -> None:
        """astream → interrupt → approval → astream(resume) → done."""
        from selva_workers.__main__ import _run_custom_with_streaming

        # Two astream calls. First yields one event, then snapshot has next.
        # After resume, second astream yields another event, snapshot is done.
        events_first = [{"plan": {"step": 1}}]
        events_second = [{"finish": {"status": "completed"}}]

        astream_calls = {"n": 0}

        async def fake_astream(*_args, **_kwargs):
            astream_calls["n"] += 1
            evs = events_first if astream_calls["n"] == 1 else events_second
            for ev in evs:
                yield ev

        # Snapshot sequence:
        #   1) after first astream: pending interrupt
        #   2) after resume astream: done
        interrupt_obj = MagicMock()
        interrupt_obj.value = {
            "action_category": "git_push",
            "reasoning": "review needed",
        }
        task_obj = MagicMock()
        task_obj.interrupts = [interrupt_obj]

        snap_pending = MagicMock()
        snap_pending.next = ("gate",)
        snap_pending.tasks = [task_obj]

        snap_done = MagicMock()
        snap_done.next = ()

        compiled = MagicMock()
        compiled.astream = fake_astream
        compiled.get_state = MagicMock(side_effect=[snap_pending, snap_done])

        handler = MagicMock()
        handler.create_approval_request = AsyncMock(return_value="req-stream-1")
        approval = MagicMock()
        approval.result = "approved"
        approval.feedback = "ok"
        handler.wait_for_approval = AsyncMock(return_value=approval)

        with patch(
            "selva_workers.__main__._publish_agent_status", new_callable=AsyncMock
        ):
            result = await _run_custom_with_streaming(
                compiled, {"task_id": "T-stream"}, "T-stream", "agent-S", handler
            )

        # Final result reflects the post-resume event.
        assert result.get("status") == "completed"
        handler.create_approval_request.assert_awaited_once()
        # astream invoked twice (initial + resume).
        assert astream_calls["n"] == 2


# ===========================================================================
# _cleanup_stale_worktrees — OSError handling on stat (lines 794-795)
# ===========================================================================


class TestCleanupStaleWorktreesOSError:
    @pytest.mark.asyncio
    async def test_swallows_oserror_on_stat(self, tmp_path) -> None:
        """If stat() raises OSError, the worktree is skipped — not raised."""
        from selva_workers.__main__ import _cleanup_stale_worktrees

        repo = tmp_path / "repo"
        wt_root = repo / "_worktrees"
        wt = wt_root / "branch-1"
        wt.mkdir(parents=True)

        # Patch Path.stat to raise OSError. Use a side effect that targets
        # only the worktree's stat() so other path operations still work.
        from pathlib import Path as _Path

        orig_stat = _Path.stat

        def _maybe_raise(self, *args, **kwargs):  # noqa: ANN001
            # Only fail the explicit .stat() call inside the loop body
            # (no kwargs); is_dir() passes follow_symlinks=True.
            if (
                "branch-1" in str(self)
                and "_worktrees" in str(self)
                and not kwargs
                and not args
            ):
                raise OSError("simulated")
            return orig_stat(self, *args, **kwargs)

        with patch.object(_Path, "stat", _maybe_raise):
            removed = await _cleanup_stale_worktrees(str(tmp_path), stale_hours=24)

        # No removal, but no exception either.
        assert removed == 0
        assert wt.exists()


# ===========================================================================
# main() consumer loop — message dispatch + ConnectionError backoff
# ===========================================================================


class TestMainConsumerLoop:
    @pytest.mark.asyncio
    async def test_dispatches_messages_to_semaphore(self) -> None:
        """A message returned by consumer.read() should be wrapped into
        an asyncio.Task via _process_with_semaphore."""
        import selva_workers.__main__ as mod

        original_shutdown = mod._shutdown
        mod._shutdown = asyncio.Event()

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=True)
        pool.close = AsyncMock()

        # First read returns one message, then we set shutdown so the loop exits.
        msg = ("msg-1", {"task_id": "T1", "graph_type": "research"})
        read_calls = {"n": 0}

        async def _read(*_args, **_kwargs):
            read_calls["n"] += 1
            if read_calls["n"] == 1:
                return [msg]
            mod._shutdown.set()
            return []

        consumer = MagicMock()
        consumer.ensure_group = AsyncMock()
        consumer.claim_stalled = AsyncMock(return_value=[])
        consumer.read = AsyncMock(side_effect=_read)
        consumer.ack = AsyncMock()

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch(
                    "selva_workers.__main__.TaskStreamConsumer",
                    return_value=consumer,
                ),
                patch(
                    "selva_workers.__main__._process_with_semaphore",
                    new_callable=AsyncMock,
                ) as mock_proc,
                patch("selva_workers.inference.validate_providers"),
            ):
                await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            restore()
            mod._shutdown = original_shutdown

        # _process_with_semaphore was awaited at least once with our message.
        assert mock_proc.await_count >= 1
        assert mock_proc.await_args is not None
        called_args = mock_proc.await_args.args
        assert called_args[1] == "msg-1"
        assert called_args[2] == {"task_id": "T1", "graph_type": "research"}

    @pytest.mark.asyncio
    async def test_connection_error_backoff(self) -> None:
        """A ConnectionError from consumer.read() triggers asyncio.sleep
        for backoff, and the loop continues."""
        import selva_workers.__main__ as mod

        original_shutdown = mod._shutdown
        mod._shutdown = asyncio.Event()

        pool = MagicMock()
        pool.ping = AsyncMock(return_value=True)
        pool.close = AsyncMock()

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            mod._shutdown.set()  # exit on first sleep

        # First read raises ConnectionError (triggers backoff)
        consumer = MagicMock()
        consumer.ensure_group = AsyncMock()
        consumer.claim_stalled = AsyncMock(return_value=[])
        consumer.read = AsyncMock(side_effect=ConnectionError("redis cluster down"))
        consumer.ack = AsyncMock()

        loop = asyncio.get_event_loop()
        restore = _stub_signal_handler(loop)
        try:
            with (
                patch("selva_workers.__main__.get_redis_pool", return_value=pool),
                patch(
                    "selva_workers.__main__._cleanup_stale_worktrees",
                    new_callable=AsyncMock,
                ),
                patch(
                    "selva_workers.__main__.TaskStreamConsumer",
                    return_value=consumer,
                ),
                patch("selva_workers.__main__.asyncio.sleep", side_effect=fake_sleep),
                patch("selva_workers.inference.validate_providers"),
            ):
                await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            restore()
            mod._shutdown = original_shutdown

        # Backoff sleep was awaited at least once with the initial 1.0s delay.
        assert sleep_calls, "sleep() should have been called for backoff"
        assert sleep_calls[0] == 1.0
