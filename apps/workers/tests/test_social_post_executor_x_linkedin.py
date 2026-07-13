"""Executor-side routing tests for the X + LinkedIn channels.

Complements ``test_social_post_executor.py`` — asserts the new channels are
registered in ``_PLATFORM_TOOL_NAMES`` and translated correctly by
``_build_tool_kwargs`` (including the ``twitter`` → ``x_post`` alias), and
that a scheduled row for a dark channel dispatches to the (fail-closed) tool
rather than being dropped or faked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from selva_workers.jobs import social_post_executor as executor


class TestPlatformToolNames:
    def test_x_and_linkedin_registered(self) -> None:
        assert executor._PLATFORM_TOOL_NAMES["x"] == "x_post"
        assert executor._PLATFORM_TOOL_NAMES["linkedin"] == "linkedin_post"

    def test_twitter_alias_routes_to_x_post(self) -> None:
        assert executor._PLATFORM_TOOL_NAMES["twitter"] == "x_post"


class TestBuildToolKwargsXLinkedIn:
    def test_x_required_text(self) -> None:
        kwargs = executor._build_tool_kwargs("x", {"text": "hi"}, persona_id="madfam")
        assert kwargs == {"text": "hi", "persona_id": "madfam"}

    def test_twitter_alias_uses_text(self) -> None:
        kwargs = executor._build_tool_kwargs("twitter", {"text": "hi"}, persona_id="madfam")
        assert kwargs is not None
        assert kwargs["text"] == "hi"

    def test_x_status_alias_for_text(self) -> None:
        kwargs = executor._build_tool_kwargs("x", {"status": "hi"}, persona_id="madfam")
        assert kwargs is not None
        assert kwargs["text"] == "hi"

    def test_x_missing_text_returns_none(self) -> None:
        assert executor._build_tool_kwargs("x", {"foo": "bar"}, persona_id="madfam") is None

    def test_linkedin_required_text(self) -> None:
        kwargs = executor._build_tool_kwargs("linkedin", {"text": "hi"}, persona_id="madfam")
        assert kwargs == {"text": "hi", "persona_id": "madfam"}

    def test_linkedin_body_alias_for_text(self) -> None:
        kwargs = executor._build_tool_kwargs("linkedin", {"body": "hi"}, persona_id="madfam")
        assert kwargs is not None
        assert kwargs["text"] == "hi"

    def test_linkedin_missing_text_returns_none(self) -> None:
        assert executor._build_tool_kwargs("linkedin", {}, persona_id="madfam") is None

    def test_persona_default(self) -> None:
        kwargs = executor._build_tool_kwargs("x", {"text": "hi"}, persona_id=None)
        assert kwargs is not None
        assert kwargs["persona_id"] == "default"


class _FakeToolResult:
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


class TestDispatchRouting:
    @pytest.mark.asyncio
    async def test_x_row_dispatches_to_x_post_tool(self) -> None:
        fake = _FakeTool(_FakeToolResult(success=True))
        registry = MagicMock()
        registry.get.side_effect = lambda name: fake if name == "x_post" else None

        with patch("selva_tools.get_tool_registry", return_value=registry):
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {"platform": "x", "text": "hi"},
                    "persona_id": "madfam",
                }
            )
        assert outcome.success is True
        assert fake.calls == [{"text": "hi", "persona_id": "madfam"}]

    @pytest.mark.asyncio
    async def test_disabled_channel_failure_is_transient_not_fake_success(
        self,
    ) -> None:
        """A dark channel's tool returns success=False (disabled). The
        executor must treat it as a real failure (retry/dead-letter), never
        as success."""
        fake = _FakeTool(
            _FakeToolResult(
                success=False,
                error="linkedin_post is disabled (ships dark)",
            )
        )
        registry = MagicMock()
        registry.get.side_effect = lambda name: fake if name == "linkedin_post" else None

        with patch("selva_tools.get_tool_registry", return_value=registry):
            outcome = await executor._dispatch_row(
                {
                    "id": "row-1",
                    "payload": {"platform": "linkedin", "text": "hi"},
                    "persona_id": "madfam",
                }
            )
        assert outcome.success is False
        # Not a rate-limit, so it is a plain (transient) failure — the row
        # will retry then dead-letter with the clear "disabled" error.
        assert outcome.rate_limited is False
