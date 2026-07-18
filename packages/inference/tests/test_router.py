"""Tests for the ModelRouter sensitivity-based inference routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from madfam_inference.base import InferenceProvider, UsageCallback
from madfam_inference.org_config import ModelAssignment, OrgConfig, TaskType
from madfam_inference.router import CHEAPEST_PRIORITY, CLOUD_PRIORITY, ModelRouter
from madfam_inference.types import (
    InferenceRequest,
    InferenceResponse,
    RoutingPolicy,
    Sensitivity,
    StreamUsage,
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

    async def stream(
        self, request: InferenceRequest, on_usage: UsageCallback | None = None
    ) -> AsyncIterator[str]:
        yield "mock chunk"
        if on_usage is not None:
            on_usage(StreamUsage(input_tokens=10, output_tokens=20, model="mock-model"))

    async def list_models(self) -> list[str]:
        return ["mock-model"]


class PreYieldFailingStreamProvider(MockProvider):
    """Streaming provider that fails before emitting a chunk."""

    async def stream(
        self, request: InferenceRequest, on_usage: UsageCallback | None = None
    ) -> AsyncIterator[str]:
        raise RuntimeError(f"{self.name} stream failed before first chunk")
        yield ""


class MidStreamFailingProvider(MockProvider):
    """Streaming provider that emits one chunk and then fails."""

    async def stream(
        self, request: InferenceRequest, on_usage: UsageCallback | None = None
    ) -> AsyncIterator[str]:
        yield "partial chunk"
        raise RuntimeError(f"{self.name} stream failed after first chunk")


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
    """All provider types registered."""
    return _make_providers(
        "ollama",
        "anthropic",
        "openai",
        "fireworks",
        "together",
        "deepinfra",
        "openrouter",
    )


@pytest.fixture()
def cloud_only_providers() -> dict[str, MockProvider]:
    """Cloud providers only -- no Ollama."""
    return _make_providers(
        "anthropic",
        "openai",
        "fireworks",
        "together",
        "deepinfra",
        "openrouter",
    )


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

    async def test_public_selects_deepinfra_first(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "deepinfra"

    async def test_public_falls_through_when_cheapest_missing(self) -> None:
        """Without deepinfra/together/fireworks, public should fall to openrouter."""
        providers = _make_providers("anthropic", "openai", "openrouter")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "openrouter"

    async def test_public_cheapest_priority_order(self) -> None:
        """Verify the CHEAPEST_PRIORITY constant order."""
        assert CHEAPEST_PRIORITY == [
            "deepinfra",
            "groq",
            "together",
            "siliconflow",
            "fireworks",
            "mistral",
            "moonshot",
            "openrouter",
            "openai",
            "anthropic",
        ]

    async def test_public_only_anthropic_available(self) -> None:
        providers = _make_providers("anthropic")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "anthropic"

    async def test_public_together_when_deepinfra_missing(self) -> None:
        """Without deepinfra, public should fall to together."""
        providers = _make_providers("together", "fireworks", "openrouter")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        response = await router.complete(request)
        assert response.provider == "together"


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
        assert CLOUD_PRIORITY == [
            "anthropic",
            "openai",
            "groq",
            "mistral",
            "moonshot",
            "siliconflow",
            "fireworks",
            "together",
            "deepinfra",
            "openrouter",
        ]

    async def test_internal_falls_through_to_openai(self) -> None:
        providers = _make_providers("openai", "openrouter")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.INTERNAL)
        response = await router.complete(request)
        assert response.provider == "openai"

    async def test_internal_falls_through_to_fireworks(self) -> None:
        """Without anthropic/openai, should fall to fireworks."""
        providers = _make_providers("fireworks", "together", "openrouter")
        router = ModelRouter(providers=providers)
        request = _make_request(sensitivity=Sensitivity.INTERNAL)
        response = await router.complete(request)
        assert response.provider == "fireworks"


class TestRequireLocalEnforced:
    """require_local=True must exclusively use Ollama."""

    async def test_require_local_uses_ollama(self, all_providers: dict[str, MockProvider]) -> None:
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
        # Should fall through to cheapest cloud: deepinfra
        assert response.provider == "deepinfra"


class TestRouterAvailableProviders:
    """Test the available_providers property."""

    def test_lists_registered_providers(self, all_providers: dict[str, MockProvider]) -> None:
        router = ModelRouter(providers=all_providers)
        available = router.available_providers
        assert set(available) == {
            "ollama",
            "anthropic",
            "openai",
            "fireworks",
            "together",
            "deepinfra",
            "openrouter",
        }

    def test_empty_providers(self) -> None:
        router = ModelRouter(providers={})
        assert router.available_providers == []


class TestPriorityListsIncludeNewProviders:
    """Verify Groq and Mistral are in the global priority lists."""

    def test_groq_in_cloud_priority(self) -> None:
        assert "groq" in CLOUD_PRIORITY

    def test_mistral_in_cloud_priority(self) -> None:
        assert "mistral" in CLOUD_PRIORITY

    def test_groq_in_cheapest_priority(self) -> None:
        assert "groq" in CHEAPEST_PRIORITY

    def test_mistral_in_cheapest_priority(self) -> None:
        assert "mistral" in CHEAPEST_PRIORITY

    def test_groq_ranks_high_in_cheapest(self) -> None:
        assert CHEAPEST_PRIORITY.index("groq") < CHEAPEST_PRIORITY.index("openai")


class TestRouterStream:
    """Verify streaming routes correctly."""

    async def test_stream_returns_chunks(self, all_providers: dict[str, MockProvider]) -> None:
        router = ModelRouter(providers=all_providers)
        request = _make_request(sensitivity=Sensitivity.PUBLIC)
        chunks = []
        async for chunk in router.stream(request):
            chunks.append(chunk)
        assert chunks == ["mock chunk"]

    async def test_stream_falls_back_before_first_chunk(self) -> None:
        router = ModelRouter(
            providers={
                "deepinfra": PreYieldFailingStreamProvider("deepinfra"),
                "groq": MockProvider("groq"),
            },
        )
        request = _make_request(sensitivity=Sensitivity.PUBLIC)

        chunks = []
        async for chunk in router.stream(request):
            chunks.append(chunk)

        assert chunks == ["mock chunk"]

    async def test_stream_does_not_fall_back_after_first_chunk(self) -> None:
        router = ModelRouter(
            providers={
                "deepinfra": MidStreamFailingProvider("deepinfra"),
                "groq": MockProvider("groq"),
            },
        )
        request = _make_request(sensitivity=Sensitivity.PUBLIC)

        chunks = []
        with pytest.raises(RuntimeError, match="after first chunk"):
            async for chunk in router.stream(request):
                chunks.append(chunk)

        assert chunks == ["partial chunk"]


# ---------------------------------------------------------------------------
# Task-type routing tests
# ---------------------------------------------------------------------------


class TestTaskTypeRouting:
    """Task-type model assignments override default provider selection."""

    def _make_org_config(self) -> OrgConfig:
        return OrgConfig(
            model_assignments={
                TaskType.PLANNING: ModelAssignment(
                    provider="deepinfra", model="GLM-5", max_tokens=8192, temperature=0.5
                ),
                TaskType.CODING: ModelAssignment(
                    provider="together",
                    model="kimi-k2.5",
                ),
            },
        )

    async def test_task_type_selects_assigned_provider(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        org_config = self._make_org_config()
        router = ModelRouter(providers=all_providers, org_config=org_config)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "plan"}],
            policy=RoutingPolicy(task_type="planning"),
        )
        response = await router.complete(request)
        assert response.provider == "deepinfra"

    async def test_task_type_sets_model_override(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        org_config = self._make_org_config()
        router = ModelRouter(providers=all_providers, org_config=org_config)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "plan"}],
            policy=RoutingPolicy(task_type="planning"),
        )
        # After routing, the policy should have model_override set
        router._select_provider(request)
        assert request.policy.model_override == "GLM-5"
        assert request.policy.max_tokens == 8192
        assert request.policy.temperature == 0.5

    async def test_task_type_fallback_without_config(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        """Without org config, task_type is ignored and default routing applies."""
        router = ModelRouter(providers=all_providers)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "plan"}],
            policy=RoutingPolicy(
                sensitivity=Sensitivity.PUBLIC,
                task_type="planning",
            ),
        )
        response = await router.complete(request)
        # Falls through to cheapest priority (deepinfra)
        assert response.provider == "deepinfra"

    async def test_task_type_missing_provider_falls_through(self) -> None:
        """When assigned provider isn't registered, fall through to defaults."""
        org_config = OrgConfig(
            model_assignments={
                TaskType.PLANNING: ModelAssignment(provider="nonexistent", model="some-model"),
            },
        )
        providers = _make_providers("anthropic", "openai")
        router = ModelRouter(providers=providers, org_config=org_config)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "plan"}],
            policy=RoutingPolicy(
                sensitivity=Sensitivity.INTERNAL,
                task_type="planning",
            ),
        )
        response = await router.complete(request)
        # Falls through to cloud priority (anthropic first)
        assert response.provider == "anthropic"

    async def test_org_config_priority_override(self) -> None:
        """Org config can override cloud/cheapest priority lists."""
        org_config = OrgConfig(
            cloud_priority=["openai", "anthropic"],
            cheapest_priority=["together", "deepinfra"],
        )
        providers = _make_providers("anthropic", "openai", "together", "deepinfra")
        router = ModelRouter(providers=providers, org_config=org_config)

        # Internal should use org cloud_priority (openai first)
        internal_req = _make_request(sensitivity=Sensitivity.INTERNAL)
        resp = await router.complete(internal_req)
        assert resp.provider == "openai"

        # Public should use org cheapest_priority (together first)
        public_req = _make_request(sensitivity=Sensitivity.PUBLIC)
        resp = await router.complete(public_req)
        assert resp.provider == "together"

    async def test_unknown_task_type_falls_through(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        """An unrecognised task_type value falls through to default routing."""
        org_config = self._make_org_config()
        router = ModelRouter(providers=all_providers, org_config=org_config)
        request = InferenceRequest(
            messages=[{"role": "user", "content": "test"}],
            policy=RoutingPolicy(
                sensitivity=Sensitivity.PUBLIC,
                task_type="unknown_task_type",
            ),
        )
        response = await router.complete(request)
        assert response.provider == "deepinfra"
