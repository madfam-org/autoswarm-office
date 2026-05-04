"""Tests for 4xx fallback classification in ModelRouter.

Closes the silent-failure mode where Anthropic returning 400 (e.g. due to
$0 credits) was treated as "request malformed", causing workers to
short-circuit and ship placeholder text. Now any 4xx that is NOT
401/403/404/422 falls through to the next provider in cloud_priority,
and 401/404/422 surface immediately so ops can see the real cause.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from madfam_inference.router import ModelRouter, _is_fallback_eligible
from madfam_inference.types import (
    InferenceRequest,
    InferenceResponse,
    RoutingPolicy,
    Sensitivity,
)


def _make_request(sensitivity: Sensitivity = Sensitivity.INTERNAL) -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "Hello"}],
        policy=RoutingPolicy(sensitivity=sensitivity),
    )


def _http_status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    """Build a real httpx.HTTPStatusError with the given status code."""
    request = httpx.Request("POST", "https://api.example.com/v1/messages")
    response = httpx.Response(status_code=status, text=body, request=request)
    return httpx.HTTPStatusError(
        f"{status} error",
        request=request,
        response=response,
    )


def _make_provider(name: str, *, raises: Exception | None = None) -> MagicMock:
    provider = MagicMock()
    provider.supports_vision = False
    if raises is not None:
        provider.complete = AsyncMock(side_effect=raises)
    else:
        provider.complete = AsyncMock(
            return_value=InferenceResponse(content="ok", model=name, provider=name),
        )
    return provider


# ---------------------------------------------------------------------------
# Classifier unit tests — _is_fallback_eligible
# ---------------------------------------------------------------------------


class TestIsFallbackEligible:
    def test_400_is_eligible(self) -> None:
        """400 → fallback (this is the load-bearing fix; Anthropic $0 case)."""
        exc = _http_status_error(400, '{"error": {"message": "credit balance too low"}}')
        assert _is_fallback_eligible(exc) is True

    def test_401_is_not_eligible(self) -> None:
        """401 → re-raise. Auth issues should surface for key rotation, not be
        masked by silently switching to another provider that may also lack creds."""
        exc = _http_status_error(401, "invalid api key")
        assert _is_fallback_eligible(exc) is False

    def test_403_is_not_eligible(self) -> None:
        exc = _http_status_error(403, "forbidden")
        assert _is_fallback_eligible(exc) is False

    def test_404_is_not_eligible(self) -> None:
        """404 (model not found) — same model id will fail elsewhere too."""
        exc = _http_status_error(404, "model not found")
        assert _is_fallback_eligible(exc) is False

    def test_422_is_not_eligible(self) -> None:
        """422 (validation error) — same payload will fail elsewhere."""
        exc = _http_status_error(422, "invalid request body")
        assert _is_fallback_eligible(exc) is False

    def test_429_is_eligible(self) -> None:
        """429 (rate limit) — fall back to a different provider rather than
        blocking the worker on back-off."""
        exc = _http_status_error(429, "rate limited")
        assert _is_fallback_eligible(exc) is True

    def test_other_4xx_eligible(self) -> None:
        for status in (402, 405, 408, 409, 410, 413, 414, 415):
            exc = _http_status_error(status, "")
            assert _is_fallback_eligible(exc) is True, f"{status} should be eligible"

    def test_5xx_eligible(self) -> None:
        for status in (500, 502, 503, 504):
            exc = _http_status_error(status, "")
            assert _is_fallback_eligible(exc) is True, f"{status} should be eligible"

    def test_network_error_eligible(self) -> None:
        request = httpx.Request("POST", "https://api.example.com/v1/messages")
        assert _is_fallback_eligible(httpx.ConnectError("conn refused", request=request)) is True
        assert (
            _is_fallback_eligible(httpx.ReadTimeout("read timed out", request=request)) is True
        )

    def test_runtime_error_with_credit_balance_message_eligible(self) -> None:
        """Some adapters wrap provider errors in plain RuntimeError. The
        $0-credits message must be recognised so we don't silently ship
        placeholders. (Bare RuntimeError IS eligible by default — only
        explicit 'unauthorized'/'invalid api key' patterns flip it off.)
        """
        exc = RuntimeError("anthropic returned: credit balance is too low")
        assert _is_fallback_eligible(exc) is True

    def test_runtime_error_with_400_status_eligible(self) -> None:
        exc = RuntimeError("provider failed with status=400")
        assert _is_fallback_eligible(exc) is True

    def test_plain_runtime_error_eligible(self) -> None:
        """Bare 'something broke' messages stay eligible — preserves
        the broad-catch fallback semantics existing tests depend on.
        (Only 401/403/404/422 HTTP errors and explicit auth-token messages
        get the hard-failure treatment.)
        """
        exc = RuntimeError("something exploded")
        assert _is_fallback_eligible(exc) is True

    def test_runtime_error_with_unauthorized_message_not_eligible(self) -> None:
        """When an adapter wraps a 401 in RuntimeError, we still surface
        it as a hard failure — auth issues should never be silently masked
        by a different provider."""
        exc = RuntimeError("anthropic returned 401 unauthorized")
        assert _is_fallback_eligible(exc) is False


# ---------------------------------------------------------------------------
# Integration — 400 from primary provider falls back to next in cloud_priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_400_from_primary_falls_back_to_next_provider() -> None:
    """The headline case: Anthropic returns 400 (e.g. $0 credits). Router
    must fall through to OpenAI rather than returning placeholder text."""
    primary = _make_provider(
        "anthropic",
        raises=_http_status_error(400, '{"error": "credit balance too low"}'),
    )
    fallback = _make_provider("openai")
    router = ModelRouter(providers={"anthropic": primary, "openai": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_401_from_primary_does_not_fall_back() -> None:
    """401 surfaces immediately so ops sees the auth issue — not masked by
    silently switching providers."""
    primary = _make_provider("anthropic", raises=_http_status_error(401, "bad key"))
    fallback = _make_provider("openai")
    router = ModelRouter(providers={"anthropic": primary, "openai": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(httpx.HTTPStatusError):
            await router.complete(_make_request())

    # Fallback was never tried.
    fallback.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_429_falls_back_to_next_provider() -> None:
    """429 → fall through. Workers stay productive on a different vendor."""
    primary = _make_provider("anthropic", raises=_http_status_error(429, "rate limited"))
    fallback = _make_provider("openai")
    router = ModelRouter(providers={"anthropic": primary, "openai": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_credit_balance_runtime_error_falls_back() -> None:
    """RuntimeError-wrapped 'credit balance' message (legacy adapters) also
    triggers fallback."""
    primary = _make_provider(
        "anthropic",
        raises=RuntimeError("anthropic responded: credit balance is too low"),
    )
    fallback = _make_provider("deepinfra")
    router = ModelRouter(providers={"anthropic": primary, "deepinfra": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.provider == "deepinfra"
