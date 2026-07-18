"""Regression tests for inference-proxy usage normalization.

madfam_inference providers emit ``input_tokens``/``output_tokens`` while the
proxy's ledger writer, event emitter, and OpenAI-compatible response body
speak ``prompt_tokens``/``completion_tokens``. The key mismatch silently
zeroed the RFC 0034 USD usage ledger — every accrual path saw 0 tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from nexus_api.routers.inference_proxy import _normalize_usage, _stream_chunks


class _FakeStreamUsage:
    def __init__(self, input_tokens: int, output_tokens: int, model: str, provider: str) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.provider = provider


class _FakeRouter:
    """Emits two chunks then reports usage via the on_usage callback,
    mirroring madfam_inference.ModelRouter.stream()."""

    def __init__(self, *, emit_usage: bool = True) -> None:
        self._emit_usage = emit_usage

    async def stream(self, request, on_usage=None) -> AsyncIterator[str]:
        yield "Hel"
        yield "lo"
        if self._emit_usage and on_usage is not None:
            on_usage(_FakeStreamUsage(7, 3, "claude-x", "anthropic"))


class _FakeReq:
    class policy:
        model_override = None


@pytest.mark.asyncio
class TestStreamMetering:
    async def test_stream_records_usage_after_completion(self) -> None:
        user = {"sub": "svc:worker", "org_id": "dhanam"}
        with patch(
            "nexus_api.routers.inference_proxy._record_stream_usage",
            new=AsyncMock(),
        ) as rec:
            chunks = [
                c
                async for c in _stream_chunks(_FakeRouter(), _FakeReq(), "cmpl-1", user)
            ]

        body = "".join(chunks)
        assert "Hel" in body and "lo" in body
        assert "[DONE]" in body
        rec.assert_awaited_once()
        # Captured usage passed through to the ledger writer.
        captured = rec.await_args.args[1]
        assert captured["usage"] == {"input_tokens": 7, "output_tokens": 3}
        assert captured["provider"] == "anthropic"
        assert captured["model"] == "claude-x"

    async def test_stream_without_usage_does_not_record(self) -> None:
        """A provider that never reports usage must not write a zero-token
        ledger row — that would be indistinguishable from a real zero."""
        user = {"sub": "svc:worker", "org_id": "dhanam"}
        with patch(
            "nexus_api.routers.inference_proxy._record_stream_usage",
            new=AsyncMock(),
        ) as rec:
            _ = [
                c
                async for c in _stream_chunks(
                    _FakeRouter(emit_usage=False), _FakeReq(), "cmpl-2", user
                )
            ]
        rec.assert_not_awaited()


class TestNormalizeUsage:
    def test_provider_style_keys_are_mapped(self) -> None:
        usage = _normalize_usage({"input_tokens": 120, "output_tokens": 45})
        assert usage == {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
        }

    def test_openai_style_keys_pass_through(self) -> None:
        usage = _normalize_usage(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        assert usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_provider_keys_win_when_both_styles_present(self) -> None:
        usage = _normalize_usage(
            {"input_tokens": 7, "output_tokens": 3, "prompt_tokens": 99}
        )
        assert usage["prompt_tokens"] == 7
        assert usage["completion_tokens"] == 3

    def test_total_is_computed_when_absent(self) -> None:
        assert _normalize_usage({"input_tokens": 2, "output_tokens": 8})["total_tokens"] == 10

    def test_none_and_empty_are_safe(self) -> None:
        zero = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        assert _normalize_usage(None) == zero
        assert _normalize_usage({}) == zero
