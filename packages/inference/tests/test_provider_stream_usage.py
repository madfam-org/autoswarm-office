"""Each streaming provider extracts final token usage from its own wire
format and reports it via ``on_usage``.

We stub ``httpx.AsyncClient.stream`` with a fake streaming context that
replays canned SSE / NDJSON lines, so no network and no new test dep.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from madfam_inference.providers.anthropic import AnthropicProvider
from madfam_inference.providers.ollama import OllamaProvider
from madfam_inference.providers.openai import OpenAIProvider
from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity, StreamUsage


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


def _patch_stream(monkeypatch, provider_module, lines: list[str]) -> None:
    """Replace ``httpx.AsyncClient.stream`` used by the provider so it
    yields our canned lines. ``AsyncClient`` itself is used as an async
    context manager elsewhere in the method; we patch both entry points."""
    import httpx

    @asynccontextmanager
    async def _fake_stream(self, method, url, **kwargs):  # noqa: ANN001
        yield _FakeStreamResponse(lines)

    async def _aenter(self):  # noqa: ANN001
        return self

    async def _aexit(self, *exc):  # noqa: ANN001
        return False

    monkeypatch.setattr(httpx.AsyncClient, "stream", _fake_stream, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "__aenter__", _aenter, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "__aexit__", _aexit, raising=True)


def _req() -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "hi"}],
        policy=RoutingPolicy(sensitivity=Sensitivity.PUBLIC),
    )


async def _collect(provider) -> tuple[str, StreamUsage | None]:
    captured: list[StreamUsage] = []
    text = "".join(
        [chunk async for chunk in provider.stream(_req(), on_usage=captured.append)]
    )
    return text, (captured[-1] if captured else None)


@pytest.mark.asyncio
async def test_anthropic_stream_reports_usage(monkeypatch) -> None:
    lines = [
        'data: {"type":"message_start","message":{"model":"claude-x","usage":{"input_tokens":11}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":4}}',
    ]
    _patch_stream(monkeypatch, "anthropic", lines)
    text, usage = await _collect(AnthropicProvider(api_key="k"))
    assert text == "Hello"
    assert usage is not None
    assert usage.input_tokens == 11
    assert usage.output_tokens == 4
    assert usage.model == "claude-x"


@pytest.mark.asyncio
async def test_openai_stream_reports_usage(monkeypatch) -> None:
    lines = [
        'data: {"model":"gpt-x","choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"model":"gpt-x","choices":[{"delta":{"content":"lo"}}]}',
        'data: {"model":"gpt-x","choices":[],"usage":{"prompt_tokens":9,"completion_tokens":5}}',
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, "openai", lines)
    text, usage = await _collect(OpenAIProvider(api_key="k"))
    assert text == "Hello"
    assert usage is not None
    assert usage.input_tokens == 9
    assert usage.output_tokens == 5


@pytest.mark.asyncio
async def test_ollama_stream_reports_usage(monkeypatch) -> None:
    lines = [
        '{"message":{"content":"Hel"},"done":false}',
        '{"message":{"content":"lo"},"done":false}',
        '{"message":{"content":""},"done":true,"model":"llama","prompt_eval_count":8,"eval_count":2}',
    ]
    _patch_stream(monkeypatch, "ollama", lines)
    text, usage = await _collect(OllamaProvider())
    assert text == "Hello"
    assert usage is not None
    assert usage.input_tokens == 8
    assert usage.output_tokens == 2


@pytest.mark.asyncio
async def test_no_usage_events_means_no_callback(monkeypatch) -> None:
    """A provider that never sees a usage event must not invoke on_usage
    with zeros — the caller distinguishes 'unmetered' from 'zero tokens'."""
    lines = [
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}',
    ]
    _patch_stream(monkeypatch, "anthropic", lines)
    text, usage = await _collect(AnthropicProvider(api_key="k"))
    assert text == "hi"
    assert usage is None
