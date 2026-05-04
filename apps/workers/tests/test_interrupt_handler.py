"""Tests for InterruptHandler — bridge between LangGraph interrupt() and the
Nexus API approval workflow.

Coverage targets:
- create_approval_request: success, custom action_category, HTTP error
- _wait_via_redis: pub/sub message receipt, timeout, ignore-subscribe behaviour
- _wait_via_polling: status transitions, jitter, timeout
- wait_for_approval: redis-then-polling fallback, redis-success short circuit
- handle_interrupt: approved / denied / timeout / HTTP error paths
- close: aclose() invocation
- __post_init__: auth header defaulting

All Redis interactions are mocked — no real Redis required.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from selva_workers.interrupt_handler import ApprovalResponse, InterruptHandler

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_handler(
    nexus_url: str = "http://localhost:4300",
    redis_url: str = "redis://localhost:6379",
    timeout: int = 30,
    auth_headers: dict[str, str] | None = None,
    org_id: str | None = None,
) -> InterruptHandler:
    """Construct an InterruptHandler with auth header injection."""
    return InterruptHandler(
        nexus_api_url=nexus_url,
        redis_url=redis_url,
        default_timeout=timeout,
        auth_headers=auth_headers or {"Authorization": "Bearer test-token"},
        org_id=org_id,
    )


def _resp(status_code: int = 200, json_data: Any | None = None) -> MagicMock:
    """Build a synchronous MagicMock httpx.Response.

    httpx Response.json() and raise_for_status() are sync — using AsyncMock
    here would yield a coroutine never-awaited warning.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# __post_init__ — auth header defaulting
# ---------------------------------------------------------------------------


class TestPostInit:
    def test_defaults_to_get_worker_auth_headers_when_unset(self) -> None:
        """When auth_headers is empty, __post_init__ should populate from auth.py."""
        with patch(
            "selva_workers.auth.get_worker_auth_headers",
            return_value={"Authorization": "Bearer derived"},
        ) as mock_fn:
            handler = InterruptHandler(
                nexus_api_url="http://localhost",
                redis_url="redis://localhost",
                org_id="org-123",
            )
            mock_fn.assert_called_once_with(org_id="org-123")
            assert handler.auth_headers == {"Authorization": "Bearer derived"}

    def test_preserves_explicit_auth_headers(self) -> None:
        """When auth_headers is provided, __post_init__ should not overwrite."""
        custom = {"Authorization": "Bearer explicit"}
        handler = InterruptHandler(
            nexus_api_url="http://localhost",
            auth_headers=custom,
        )
        assert handler.auth_headers == custom


# ---------------------------------------------------------------------------
# create_approval_request
# ---------------------------------------------------------------------------


class TestCreateApprovalRequest:
    @pytest.mark.asyncio
    async def test_posts_to_correct_url_and_body(self) -> None:
        handler = _make_handler()
        mock_post = AsyncMock(return_value=_resp(200, {"id": "req-uuid-1"}))
        handler.client = MagicMock()
        handler.client.post = mock_post

        request_id = await handler.create_approval_request(
            agent_id="agent-1",
            action_category="git_push",
            payload={"branch": "feature/foo"},
            reasoning="Pushing to remote",
            urgency="high",
            diff="+++ a.py",
        )

        assert request_id == "req-uuid-1"
        # Verify URL / body shape
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:4300/api/v1/approvals/"
        body = call_args[1]["json"]
        assert body["agent_id"] == "agent-1"
        assert body["action_category"] == "git_push"
        # Keep action_type for backwards compatibility
        assert body["action_type"] == "git_push"
        assert body["payload"] == {"branch": "feature/foo"}
        assert body["reasoning"] == "Pushing to remote"
        assert body["urgency"] == "high"
        assert body["diff"] == "+++ a.py"

    @pytest.mark.asyncio
    async def test_default_urgency_is_medium(self) -> None:
        handler = _make_handler()
        handler.client = MagicMock()
        handler.client.post = AsyncMock(return_value=_resp(200, {"id": "req-2"}))

        await handler.create_approval_request(
            agent_id="agent-1",
            action_category="email_send",
            payload={},
            reasoning="reason",
        )

        body = handler.client.post.call_args[1]["json"]
        assert body["urgency"] == "medium"
        # diff defaults to None
        assert body["diff"] is None

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_nexus_url(self) -> None:
        handler = _make_handler(nexus_url="http://localhost:4300/")
        handler.client = MagicMock()
        handler.client.post = AsyncMock(return_value=_resp(200, {"id": "x"}))

        await handler.create_approval_request(
            agent_id="a", action_category="api_call", payload={}, reasoning="r"
        )
        url = handler.client.post.call_args[0][0]
        assert url == "http://localhost:4300/api/v1/approvals/"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self) -> None:
        handler = _make_handler()
        handler.client = MagicMock()
        handler.client.post = AsyncMock(return_value=_resp(500))

        with pytest.raises(httpx.HTTPStatusError):
            await handler.create_approval_request(
                agent_id="a", action_category="api_call", payload={}, reasoning="r"
            )


# ---------------------------------------------------------------------------
# _wait_via_polling
# ---------------------------------------------------------------------------


class TestWaitViaPolling:
    @pytest.mark.asyncio
    async def test_returns_approved_response(self) -> None:
        handler = _make_handler()
        approved = _resp(
            200,
            {
                "id": "req-1",
                "status": "approved",
                "feedback": "lgtm",
                "responded_at": "2026-05-03T00:00:00Z",
            },
        )
        handler.client = MagicMock()
        handler.client.get = AsyncMock(return_value=approved)

        result = await handler._wait_via_polling("req-1", timeout=5, poll_interval=0.01)

        assert isinstance(result, ApprovalResponse)
        assert result.result == "approved"
        assert result.feedback == "lgtm"
        assert result.responded_at == "2026-05-03T00:00:00Z"

    @pytest.mark.asyncio
    async def test_returns_denied_response(self) -> None:
        handler = _make_handler()
        denied = _resp(
            200,
            {
                "id": "req-1",
                "status": "denied",
                "feedback": "no thanks",
            },
        )
        handler.client = MagicMock()
        handler.client.get = AsyncMock(return_value=denied)

        result = await handler._wait_via_polling("req-1", timeout=5, poll_interval=0.01)
        assert result.result == "denied"
        assert result.feedback == "no thanks"

    @pytest.mark.asyncio
    async def test_polls_until_resolved(self) -> None:
        handler = _make_handler()
        pending = _resp(200, {"id": "req-1", "status": "pending"})
        approved = _resp(200, {"id": "req-1", "status": "approved"})
        handler.client = MagicMock()
        handler.client.get = AsyncMock(side_effect=[pending, pending, approved])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await handler._wait_via_polling("req-1", timeout=5, poll_interval=0.01)

        assert result.result == "approved"
        assert handler.client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_timeout_when_unresolved(self) -> None:
        handler = _make_handler()
        pending = _resp(200, {"id": "req-1", "status": "pending"})
        handler.client = MagicMock()
        handler.client.get = AsyncMock(return_value=pending)

        # Use micro-timeout + non-blocking sleep to exit fast
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TimeoutError, match="not resolved within"):
                await handler._wait_via_polling("req-1", timeout=0.01, poll_interval=0.05)


# ---------------------------------------------------------------------------
# _wait_via_redis
# ---------------------------------------------------------------------------


class TestWaitViaRedis:
    @pytest.mark.asyncio
    async def test_returns_approval_from_pubsub(self) -> None:
        handler = _make_handler()

        msg_payload = {
            "request_id": "req-1",
            "result": "approved",
            "feedback": "ok",
        }
        message = {"type": "message", "data": json.dumps(msg_payload)}

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.close = AsyncMock()
        # First call returns the message
        pubsub.get_message = AsyncMock(return_value=message)

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)

        pool = MagicMock()
        pool.client = AsyncMock(return_value=redis_client)

        with patch(
            "selva_workers.interrupt_handler.get_redis_pool",
            return_value=pool,
        ):
            result = await handler._wait_via_redis("req-1", timeout=5)

        assert result.result == "approved"
        assert result.feedback == "ok"
        pubsub.subscribe.assert_awaited_once_with("autoswarm:approval:req-1")
        pubsub.unsubscribe.assert_awaited_once()
        pubsub.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_non_message_pubsub_events(self) -> None:
        handler = _make_handler()
        msg_payload = {
            "request_id": "req-1",
            "result": "denied",
            "feedback": "nope",
        }
        first = None  # simulates "no message yet" - ignored by while-loop
        second = {"type": "message", "data": json.dumps(msg_payload)}

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.close = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=[first, second])

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)
        pool = MagicMock()
        pool.client = AsyncMock(return_value=redis_client)

        with patch(
            "selva_workers.interrupt_handler.get_redis_pool",
            return_value=pool,
        ):
            result = await handler._wait_via_redis("req-1", timeout=5)

        assert result.result == "denied"
        assert pubsub.get_message.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_timeout_when_no_message_arrives(self) -> None:
        handler = _make_handler()

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.close = AsyncMock()

        # Always return None, but YIELD to the event loop on each call.
        # AsyncMock(return_value=None) returns instantly without yielding,
        # so the implementation's `while True` busy-loops and asyncio.wait_for
        # never fires its timeout. A small sleep gives the timer a chance to
        # check the deadline.
        async def _yield_then_none(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(0.005)
            return None

        pubsub.get_message = AsyncMock(side_effect=_yield_then_none)

        redis_client = MagicMock()
        redis_client.pubsub = MagicMock(return_value=pubsub)
        pool = MagicMock()
        pool.client = AsyncMock(return_value=redis_client)

        with patch(
            "selva_workers.interrupt_handler.get_redis_pool",
            return_value=pool,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await handler._wait_via_redis("req-1", timeout=0.05)

        pubsub.unsubscribe.assert_awaited_once()
        pubsub.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# wait_for_approval (redis preferred, polling fallback)
# ---------------------------------------------------------------------------


class TestWaitForApproval:
    @pytest.mark.asyncio
    async def test_uses_default_timeout_when_none(self) -> None:
        handler = _make_handler(timeout=42)
        captured: dict[str, int] = {}

        async def fake_redis(req: str, timeout: int) -> ApprovalResponse:
            captured["timeout"] = timeout
            return ApprovalResponse(request_id=req, result="approved")

        with patch.object(handler, "_wait_via_redis", side_effect=fake_redis):
            result = await handler.wait_for_approval("req-1")

        assert result.result == "approved"
        assert captured["timeout"] == 42

    @pytest.mark.asyncio
    async def test_redis_success_short_circuits(self) -> None:
        handler = _make_handler()
        with (
            patch.object(
                handler,
                "_wait_via_redis",
                return_value=ApprovalResponse(request_id="r", result="approved"),
            ) as redis_mock,
            patch.object(handler, "_wait_via_polling"),
        ):
            redis_mock.return_value = ApprovalResponse(request_id="r", result="approved")
            redis_mock.side_effect = None
            # Re-wrap as AsyncMock since we need awaitable
            handler._wait_via_redis = AsyncMock(  # type: ignore[method-assign]
                return_value=ApprovalResponse(request_id="r", result="approved")
            )
            polling_stub = AsyncMock()
            handler._wait_via_polling = polling_stub  # type: ignore[method-assign]

            result = await handler.wait_for_approval("req-1", timeout=5)

            # Assert inside the with block — the patch.object teardown
            # restores the original bound method, which has no
            # `.assert_not_called` attribute.
            assert result.result == "approved"
            polling_stub.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_polling_on_redis_error(self) -> None:
        handler = _make_handler()

        with (
            patch.object(
                handler,
                "_wait_via_redis",
                side_effect=ConnectionError("redis down"),
            ),
            patch.object(
                handler,
                "_wait_via_polling",
                return_value=ApprovalResponse(request_id="r", result="approved"),
            ) as polling_mock,
        ):
            result = await handler.wait_for_approval("req-1", timeout=5, poll_interval=0.1)

        assert result.result == "approved"
        polling_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_propagates_timeout_from_redis_path(self) -> None:
        """When the redis path itself times out, do NOT fall back to polling."""
        handler = _make_handler()

        with (
            patch.object(
                handler,
                "_wait_via_redis",
                side_effect=TimeoutError("redis wait timeout"),
            ),
            patch.object(handler, "_wait_via_polling") as polling_mock,
        ):
            with pytest.raises(TimeoutError):
                await handler.wait_for_approval("req-1", timeout=5)

            polling_mock.assert_not_called()


# ---------------------------------------------------------------------------
# handle_interrupt (full flow)
# ---------------------------------------------------------------------------


class TestHandleInterrupt:
    @pytest.mark.asyncio
    async def test_approved_path_updates_state(self) -> None:
        handler = _make_handler()
        approved_resp = ApprovalResponse(
            request_id="req-1", result="approved", feedback="ship it"
        )

        with (
            patch.object(handler, "create_approval_request", return_value="req-1"),
            patch.object(handler, "wait_for_approval", return_value=approved_resp),
        ):
            handler.create_approval_request = AsyncMock(return_value="req-1")  # type: ignore[method-assign]
            handler.wait_for_approval = AsyncMock(return_value=approved_resp)  # type: ignore[method-assign]

            state = {
                "agent_id": "a-1",
                "task_id": "t-1",
                "messages": [],
            }
            new_state = await handler.handle_interrupt(state)

        assert new_state["status"] == "approved"
        assert new_state["requires_approval"] is False
        assert new_state["approval_request_id"] == "req-1"

    @pytest.mark.asyncio
    async def test_denied_path_includes_feedback(self) -> None:
        handler = _make_handler()
        denied_resp = ApprovalResponse(
            request_id="req-1", result="denied", feedback="security concern"
        )

        handler.create_approval_request = AsyncMock(return_value="req-1")  # type: ignore[method-assign]
        handler.wait_for_approval = AsyncMock(return_value=denied_resp)  # type: ignore[method-assign]

        state = {
            "agent_id": "a-1",
            "task_id": "t-1",
            "messages": [],
        }
        new_state = await handler.handle_interrupt(state)

        assert new_state["status"] == "denied"
        assert new_state["requires_approval"] is False
        assert new_state["result"] == {"denied_feedback": "security concern"}

    @pytest.mark.asyncio
    async def test_extracts_action_from_last_message(self) -> None:
        """When messages have additional_kwargs, action_category should be pulled."""
        handler = _make_handler()
        captured: dict[str, Any] = {}

        async def capture(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "req-1"

        handler.create_approval_request = capture  # type: ignore[method-assign]
        handler.wait_for_approval = AsyncMock(  # type: ignore[method-assign]
            return_value=ApprovalResponse(request_id="req-1", result="approved")
        )

        last_msg = MagicMock()
        last_msg.additional_kwargs = {
            "action_category": "git_push",
            "branch": "feature/foo",
        }
        state = {
            "agent_id": "a-1",
            "task_id": "t-1",
            "messages": [last_msg],
        }
        await handler.handle_interrupt(state)

        assert captured["action_category"] == "git_push"
        assert "branch" in captured["payload"]

    @pytest.mark.asyncio
    async def test_timeout_path_returns_timeout_status(self) -> None:
        handler = _make_handler()
        handler.create_approval_request = AsyncMock(return_value="req-1")  # type: ignore[method-assign]
        handler.wait_for_approval = AsyncMock(side_effect=TimeoutError("nope"))  # type: ignore[method-assign]

        state = {"agent_id": "a-1", "task_id": "t-1", "messages": []}
        new_state = await handler.handle_interrupt(state)

        assert new_state["status"] == "timeout"
        assert new_state["requires_approval"] is False

    @pytest.mark.asyncio
    async def test_http_error_path_returns_error_status(self) -> None:
        handler = _make_handler()
        handler.create_approval_request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.HTTPError("nexus down")
        )

        state = {"agent_id": "a-1", "task_id": "t-1", "messages": []}
        new_state = await handler.handle_interrupt(state)

        assert new_state["status"] == "error"
        assert "nexus down" in new_state["result"]["error"]
        assert new_state["requires_approval"] is False

    @pytest.mark.asyncio
    async def test_handles_missing_agent_id(self) -> None:
        """If state lacks agent_id, falls back to 'unknown'."""
        handler = _make_handler()
        captured: dict[str, Any] = {}

        async def capture(agent_id: str, **_: Any) -> str:
            captured["agent_id"] = agent_id
            return "req-1"

        handler.create_approval_request = capture  # type: ignore[method-assign]
        handler.wait_for_approval = AsyncMock(  # type: ignore[method-assign]
            return_value=ApprovalResponse(request_id="req-1", result="approved")
        )

        new_state = await handler.handle_interrupt({})
        assert captured["agent_id"] == "unknown"
        assert new_state["status"] == "approved"


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_aclose_on_client(self) -> None:
        handler = _make_handler()
        handler.client = MagicMock()
        handler.client.aclose = AsyncMock()

        await handler.close()

        handler.client.aclose.assert_awaited_once()
