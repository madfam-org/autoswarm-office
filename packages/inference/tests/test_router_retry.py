"""Tests for ModelRouter retry and fallback logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from madfam_inference.org_config import OrgConfig
from madfam_inference.router import ModelRouter
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


def _make_provider(name: str, *, fail: bool = False, fail_count: int = 0) -> MagicMock:
    """Create a mock provider with configurable failure behavior.

    Args:
        name: Provider identifier used in responses and error messages.
        fail: If True the provider always raises RuntimeError.
        fail_count: Number of initial calls that raise before succeeding.
            Ignored when *fail* is True.
    """
    provider = MagicMock()
    provider.supports_vision = False

    if fail:
        provider.complete = AsyncMock(side_effect=RuntimeError(f"{name} failed"))
    elif fail_count > 0:
        call_count = {"n": 0}

        async def _complete(req: InferenceRequest) -> InferenceResponse:
            call_count["n"] += 1
            if call_count["n"] <= fail_count:
                raise RuntimeError(f"{name} transient error")
            return InferenceResponse(content="ok", model=name, provider=name)

        provider.complete = _complete
    else:
        provider.complete = AsyncMock(
            return_value=InferenceResponse(content="ok", model=name, provider=name),
        )

    return provider


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_transient_failure() -> None:
    """Primary provider fails once, succeeds on retry."""
    provider = _make_provider("anthropic", fail_count=1)
    router = ModelRouter(providers={"anthropic": provider})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.model == "anthropic"


@pytest.mark.asyncio
async def test_no_retry_on_immediate_success() -> None:
    """Provider succeeds on first call -- no retry or sleep needed."""
    provider = _make_provider("anthropic")
    router = ModelRouter(providers={"anthropic": provider})

    result = await router.complete(_make_request())

    assert result.content == "ok"
    # complete should have been called exactly once
    provider.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_sleeps_between_attempts() -> None:
    """The 1-second delay between retry attempts is respected."""
    provider = _make_provider("anthropic", fail_count=1)
    router = ModelRouter(providers={"anthropic": provider})

    sleep_mock = AsyncMock()
    with patch("madfam_inference.router.asyncio.sleep", sleep_mock):
        await router.complete(_make_request())

    sleep_mock.assert_awaited_once_with(1.0)


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_falls_through_to_fallback() -> None:
    """Primary provider always fails -- falls through to next provider."""
    primary = _make_provider("anthropic", fail=True)
    fallback = _make_provider("openai")
    router = ModelRouter(providers={"anthropic": primary, "openai": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.model == "openai"


@pytest.mark.asyncio
async def test_fallback_skips_failed_providers() -> None:
    """First fallback also fails -- second fallback succeeds."""
    primary = _make_provider("anthropic", fail=True)
    first_fallback = _make_provider("openai", fail=True)
    second_fallback = _make_provider("groq")
    router = ModelRouter(
        providers={
            "anthropic": primary,
            "openai": first_fallback,
            "groq": second_fallback,
        },
    )

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(_make_request())

    assert result.content == "ok"
    assert result.model == "groq"


@pytest.mark.asyncio
async def test_fallback_respects_org_priority_override() -> None:
    """DeepInfra-only org config must not fall through to registered Anthropic."""
    primary = _make_provider("deepinfra", fail=True)
    excluded = _make_provider("anthropic")
    router = ModelRouter(
        providers={"deepinfra": primary, "anthropic": excluded},
        org_config=OrgConfig(
            cloud_priority=["deepinfra"],
            cheapest_priority=["deepinfra"],
        ),
    )

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="All providers failed"):
            await router.complete(_make_request())

    excluded.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_fallback_for_restricted_sensitivity() -> None:
    """Restricted requests cannot fall back -- they are local-only."""
    local = _make_provider("ollama", fail=True)
    cloud = _make_provider("openai")
    router = ModelRouter(providers={"ollama": local, "openai": cloud})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="All providers failed"):
            await router.complete(_make_request(sensitivity=Sensitivity.RESTRICTED))


# ---------------------------------------------------------------------------
# All-fail tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_when_all_fail() -> None:
    """All providers fail -- RuntimeError raised with descriptive message."""
    primary = _make_provider("anthropic", fail=True)
    fallback = _make_provider("openai", fail=True)
    router = ModelRouter(providers={"anthropic": primary, "openai": fallback})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="All providers failed"):
            await router.complete(_make_request())


@pytest.mark.asyncio
async def test_error_message_contains_last_error() -> None:
    """The RuntimeError includes the last exception's message."""
    primary = _make_provider("anthropic", fail=True)
    router = ModelRouter(providers={"anthropic": primary})

    with patch("madfam_inference.router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="anthropic failed"):
            await router.complete(_make_request())
