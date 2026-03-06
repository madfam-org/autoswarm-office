"""Tests for the ModelRouter sensitivity-based inference routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from packages.inference.src.base import InferenceProvider
from packages.inference.src.router import CHEAPEST_PRIORITY, CLOUD_PRIORITY, LOCAL_PROVIDER, ModelRouter
from packages.inference.src.types import (
    InferenceRequest,
    InferenceResponse,
    RoutingPolicy,
    Sensitivity,
)


# ---------------------------------------------------------------------------
# Mock provider factory
# ---------------------------------------------------------------------------

class MockProvider(InferenceProvider):
    """A lightweight mock InferenceProvider for testing routing decisions."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name
        self._complete_mock = AsyncMock(
            return_value=InferenceResponse(
                content="mock response",
                model="mock-model",
                provider=provider_name,
                usage={"prompt_tokens": 10, "completion_tokens": 20},
            )
        )

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        return await self._complete_mock(request)

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        yield "mock chunk"

    async def list_models(self) -> list[str]:
        return ["mock-model"]


def _make_providers(*names: str) -> dict[str, MockProvider]:
    """Create a dict of MockProvider instances keyed by name."""
    return {name: MockProvider(name) for name in names}


def _make_request(
    sensitivity: Sensitivity = Sensitivity.PUBLIC,
    require_local: bool = False,
    prefer_local: bool = False,
) -> InferenceRequest:
    """Build an InferenceRequest with the given routing policy."""
    return InferenceRequest(
        messages=[{"role": "user", "content": "test"}],
        policy=RoutingPolicy(
            sensitivity=sensitivity,
            require_local=require_local,
            prefer_local=prefer_local,
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def all_providers() -> dict[str, MockProvider]:
    """All four provider types registered."""
    return _make_providers("ollama", "anthropic", "openai", "openrouter")


@pytest.fixture()
def cloud_only_providers() -> dict[str, MockProvider]:
    """Cloud providers only -- no Ollama."""
    return _make_providers("anthropic", "openai", "openrouter")


@pytest.fixture()
def ollama_only() -> dict[str, MockProvider]:
    """Only the local Ollama provider."""
    return _make_providers("ollama")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRouteRestrictedToOllama:
    """Restricted / confidential sensitivity must route to Ollama."""

    @pytest.mark.parametrize(
        "sensitivity",
        [Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL],
    )
    async def test_restricted_selects_ollama(
        self, all_providers: dict[str, MockProvider], sensitivity: Sensitivity
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=sensitivity)
        response = await router.complete(request)
        assert response.provider == "ollama"

    async def test_restricted_without_ollama_raises(
        self, cloud_only_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=cloud_only_providers)
        request = _make_request(sensitivity=Sensitivity.RESTRICTED)
        with pytest.raises(RuntimeError, match="No available provider"):
            await router.complete(request)

    async def test_confidential_without_ollama_raises(
        self, cloud_only_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=cloud_only_providers)
        request = _make_request(sensitivity=Sensitivity.CONFIDENTIAL)
        with pytest.raises(RuntimeError, match="No available provider"):
            await router.complete(request)


class TestRoutePublicPrefersCheap:
    """Public sensitivity should route to the cheapest available provider."""

    async def test_public_selects_openrouter_first(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "openrouter"

    async def test_public_falls_through_when_cheapest_missing(self) -> None:
        """Without openrouter, public should fall to next cheapest: openai."""
        providers = _make_providers("anthropic", "openai")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "openai"

    async def test_public_cheapest_priority_order(self) -> None:
        """Verify the CHEAPEST_PRIORITY constant is openrouter > openai > anthropic."""
        assert CHEAPEST_PRIORITY == ["openrouter", "openai", "anthropic"]

    async def test_public_only_anthropic_available(self) -> None:
        providers = _make_providers("anthropic")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "anthropic"


class TestRouteInternalPrefersCloud:
    """Internal sensitivity should route using CLOUD_PRIORITY order."""

    async def test_internal_selects_anthropic_first(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.INTERNAL)
        response = await router.complete(request)
        assert response.provider == "anthropic"

    async def test_internal_cloud_priority_order(self) -> None:
        assert CLOUD_PRIORITY == ["anthropic", "openai", "openrouter"]

    async def test_internal_falls_through_to_openai(self) -> None:
        providers = _make_providers("openai", "openrouter")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.INTERNAL)
        response = await router.complete(request)
        assert response.provider == "openai"


class TestRequireLocalEnforced:
    """require_local=True must exclusively use Ollama."""

    async def test_require_local_uses_ollama(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(require_local=True)
        response = await router.complete(request)
        assert response.provider == "ollama"

    async def test_require_local_without_ollama_raises(
        self, cloud_only_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=cloud_only_providers)
        request = _make_request(require_local=True)
        with pytest.raises(RuntimeError, match="require_local is True but no Ollama"):
            await router.complete(request)

    async def test_require_local_overrides_sensitivity(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        """Even with PUBLIC sensitivity, require_local forces Ollama."""
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC, require_local=True)
        response = await router.complete(request)
        assert response.provider == "ollama"


class TestPreferLocal:
    """prefer_local=True should try Ollama first but fall through."""

    async def test_prefer_local_uses_ollama_when_available(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC, prefer_local=True)
        response = await router.complete(request)
        assert response.provider == "ollama"

    async def test_prefer_local_falls_through_without_ollama(
        self, cloud_only_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=cloud_only_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC, prefer_local=True)
        response = await router.complete(request)
        # Should fall through to cheapest cloud: openrouter
        assert response.provider == "openrouter"


class TestRouterAvailableProviders:
    """Test the available_providers property."""

    def test_lists_registered_providers(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        available = router.available_providers
        assert set(available) == {"ollama", "anthropic", "openai", "openrouter"}

    def test_empty_providers(self) -> None:
        router = ModelRouter(providers={})
        assert router.available_providers == []


class TestRouterStream:
    """Verify streaming routes correctly."""

    async def test_stream_returns_chunks(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        chunks = []
        async for chunk in router.stream(request):
            chunks.append(chunk)
        assert chunks == ["mock chunk"]
