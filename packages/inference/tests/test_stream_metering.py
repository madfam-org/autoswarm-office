"""Streaming inference is metered — the router forwards provider-reported
usage through ``on_usage`` and stamps the winning provider.

Before this, ``ModelRouter.stream()`` recorded nothing (chunks carry no
token accounting), so every streamed call was free (RFC 0034 gap).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from madfam_inference.base import InferenceProvider, UsageCallback
from madfam_inference.router import ModelRouter
from madfam_inference.types import (
    InferenceRequest,
    InferenceResponse,
    RoutingPolicy,
    Sensitivity,
    StreamUsage,
)


class _UsageProvider(InferenceProvider):
    """Provider that streams two chunks then reports usage."""

    def __init__(self, name: str, *, fail_after_first: bool = False) -> None:
        self.name = name
        self._fail_after_first = fail_after_first

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        return InferenceResponse(content="x", model="m", provider=self.name)

    async def stream(
        self, request: InferenceRequest, on_usage: UsageCallback | None = None
    ) -> AsyncIterator[str]:
        yield "hel"
        if self._fail_after_first:
            raise RuntimeError("boom after first chunk")
        yield "lo"
        if on_usage is not None:
            on_usage(StreamUsage(input_tokens=7, output_tokens=3, model="m"))

    async def list_models(self) -> list[str]:
        return ["m"]


def _req() -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "hi"}],
        policy=RoutingPolicy(sensitivity=Sensitivity.PUBLIC),
    )


@pytest.mark.asyncio
async def test_stream_forwards_usage_with_provider_stamped() -> None:
    router = ModelRouter({"anthropic": _UsageProvider("anthropic")})
    seen: list[StreamUsage] = []

    chunks = [c async for c in router.stream(_req(), on_usage=seen.append)]

    assert "".join(chunks) == "hello"
    assert len(seen) == 1
    assert seen[0].input_tokens == 7
    assert seen[0].output_tokens == 3
    # The router stamps which provider actually served the stream.
    assert seen[0].provider == "anthropic"


@pytest.mark.asyncio
async def test_stream_without_callback_still_streams() -> None:
    router = ModelRouter({"anthropic": _UsageProvider("anthropic")})
    chunks = [c async for c in router.stream(_req())]
    assert "".join(chunks) == "hello"


@pytest.mark.asyncio
async def test_fallback_stream_stamps_fallback_provider() -> None:
    # Primary (cheapest for PUBLIC) fails before any chunk → fall back.
    from madfam_inference.router import CHEAPEST_PRIORITY

    class _PreFail(_UsageProvider):
        async def stream(
            self, request: InferenceRequest, on_usage: UsageCallback | None = None
        ) -> AsyncIterator[str]:
            raise RuntimeError("primary down before first chunk")
            yield ""  # pragma: no cover

    primary = CHEAPEST_PRIORITY[0]
    fallback = CHEAPEST_PRIORITY[1]
    router = ModelRouter(
        {primary: _PreFail(primary), fallback: _UsageProvider(fallback)}
    )
    seen: list[StreamUsage] = []

    chunks = [c async for c in router.stream(_req(), on_usage=seen.append)]

    assert "".join(chunks) == "hello"
    assert len(seen) == 1
    assert seen[0].provider == fallback
