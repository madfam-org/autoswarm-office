"""Sensitivity must be evaluated BEFORE task_type — and must win.

Before this suite, ``_select_provider`` evaluated the org-config
``model_assignments`` for the request's ``task_type`` and *returned*
before ever reaching the sensitivity branch. Any task type mapped in the
org config therefore beat ``X-Sensitivity: restricted`` and sent the
payload to whatever cloud vendor the assignment named.

The MAP (Crea Tu Mundo's clinical platform) was protected only by
accident: it sends ``summarization`` and ``family-feedback``, and neither
string is a member of the ``TaskType`` enum, so ``TaskType(...)`` raised
``ValueError`` and the code fell through to the sensitivity branch. The
day someone added ``summarization`` to the org config, clinical notes
about minors would have gone to DeepInfra with no code change anywhere.

These tests make that structural instead of accidental: the tests below
deliberately map the MAP's task types in the org config — the exact
scenario that used to break — and assert the local provider still wins.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from madfam_inference.base import InferenceProvider, UsageCallback
from madfam_inference.org_config import ModelAssignment, OrgConfig, TaskType
from madfam_inference.router import LOCAL_ONLY_SENSITIVITIES, ModelRouter
from madfam_inference.types import (
    InferenceRequest,
    InferenceResponse,
    RoutingPolicy,
    Sensitivity,
    StreamUsage,
)


class MockProvider(InferenceProvider):
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


def _providers(*names: str) -> dict[str, MockProvider]:
    return {name: MockProvider(name) for name in names}


@pytest.fixture()
def all_providers() -> dict[str, MockProvider]:
    return _providers("ollama", "anthropic", "openai", "deepinfra", "together")


def _request(
    *,
    sensitivity: Sensitivity,
    task_type: str | None = None,
) -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "test"}],
        policy=RoutingPolicy(sensitivity=sensitivity, task_type=task_type),
    )


# ---------------------------------------------------------------------------
# The regression: a cloud-mapped task type cannot escape a restricted level
# ---------------------------------------------------------------------------


class TestTaskTypeCannotBypassSensitivity:
    """A task-type assignment pointing at a cloud provider is REFUSED for
    restricted/confidential — routing falls back to the local provider."""

    def _cloud_mapped_config(self) -> OrgConfig:
        """Production-shaped config: every task type pinned to DeepInfra."""
        return OrgConfig(
            model_assignments={
                task: ModelAssignment(
                    provider="deepinfra",
                    model="meta-llama/Llama-3.3-70B-Instruct",
                )
                for task in TaskType
            },
            cloud_priority=["deepinfra"],
            cheapest_priority=["deepinfra"],
        )

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    @pytest.mark.parametrize(
        "task_type",
        ["planning", "research", "support", "review", "crm", "coding"],
    )
    async def test_mapped_task_type_still_routes_local(
        self,
        all_providers: dict[str, MockProvider],
        sensitivity: Sensitivity,
        task_type: str,
    ) -> None:
        router = ModelRouter(providers=all_providers, org_config=self._cloud_mapped_config())
        response = await router.complete(_request(sensitivity=sensitivity, task_type=task_type))
        assert response.provider == "ollama"

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    async def test_refused_assignment_does_not_override_the_model(
        self,
        all_providers: dict[str, MockProvider],
        sensitivity: Sensitivity,
    ) -> None:
        """A refused assignment must not leak its cloud model name into the
        policy — otherwise the local backend would be asked for a model it
        does not have and the call would fail confusingly."""
        router = ModelRouter(providers=all_providers, org_config=self._cloud_mapped_config())
        request = _request(sensitivity=sensitivity, task_type="planning")
        router._select_provider(request)
        assert request.policy.model_override is None

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    async def test_no_local_provider_raises_instead_of_falling_to_cloud(
        self, sensitivity: Sensitivity
    ) -> None:
        """With no local backend registered and every task type mapped to a
        cloud provider, the router must RAISE — never quietly serve the
        request from the cloud. This is the 503-fail-closed contract."""
        cloud_only = _providers("deepinfra", "anthropic", "openai")
        router = ModelRouter(providers=cloud_only, org_config=self._cloud_mapped_config())
        with pytest.raises(RuntimeError, match="No available provider"):
            await router.complete(_request(sensitivity=sensitivity, task_type="planning"))


class TestMapTaskTypes:
    """The MAP's two concrete surfaces: minutas (`summarization`) and the
    Padlet family feedback (`family-feedback`).

    Today neither is a ``TaskType`` member. These tests assert the outcome
    is correct BOTH ways — unmapped today, and mapped tomorrow — so that
    adding either to the enum can never become a silent data leak.
    """

    MAP_TASK_TYPES = ["summarization", "family-feedback"]

    @pytest.mark.parametrize("task_type", MAP_TASK_TYPES)
    async def test_unmapped_map_task_type_routes_local(
        self, all_providers: dict[str, MockProvider], task_type: str
    ) -> None:
        org_config = OrgConfig(
            model_assignments={
                TaskType.RESEARCH: ModelAssignment(provider="deepinfra", model="llama"),
            },
            cheapest_priority=["deepinfra"],
        )
        router = ModelRouter(providers=all_providers, org_config=org_config)
        response = await router.complete(
            _request(sensitivity=Sensitivity.RESTRICTED, task_type=task_type)
        )
        assert response.provider == "ollama"

    @pytest.mark.parametrize("task_type", MAP_TASK_TYPES)
    async def test_map_task_type_mapped_to_cloud_still_routes_local(
        self, all_providers: dict[str, MockProvider], task_type: str
    ) -> None:
        """Simulate the future in which ``summarization`` IS in the enum and
        IS pinned to a cloud provider. The clinical payload must still be
        served locally — the whole point of the fix."""

        class _FakeAssignment:
            provider = "deepinfra"
            model = "meta-llama/Llama-3.3-70B-Instruct"
            max_tokens = 4096
            temperature = 0.7

        class _FakeOrgConfig:
            # Keyed by the raw string so lookup succeeds without touching
            # the real enum (which does not yet contain these members).
            model_assignments = {task_type: _FakeAssignment()}
            cloud_priority = ["deepinfra"]
            cheapest_priority = ["deepinfra"]

        router = ModelRouter(providers=all_providers, org_config=_FakeOrgConfig())
        response = await router.complete(
            _request(sensitivity=Sensitivity.RESTRICTED, task_type=task_type)
        )
        assert response.provider == "ollama"


class TestAllowedProviderSet:
    """``allowed_providers_for`` is the security boundary — assert it directly."""

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    def test_local_only_for_regulated_levels(
        self, all_providers: dict[str, MockProvider], sensitivity: Sensitivity
    ) -> None:
        router = ModelRouter(providers=all_providers)
        assert router.allowed_providers_for(_request(sensitivity=sensitivity)) == ["ollama"]

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    def test_org_priority_lists_cannot_widen_the_regulated_set(
        self, all_providers: dict[str, MockProvider], sensitivity: Sensitivity
    ) -> None:
        """An operator editing cloud_priority/cheapest_priority must not be
        able to add a cloud provider to the restricted path."""
        org_config = OrgConfig(
            cloud_priority=["deepinfra", "anthropic"],
            cheapest_priority=["deepinfra", "openai"],
        )
        router = ModelRouter(providers=all_providers, org_config=org_config)
        assert router.allowed_providers_for(_request(sensitivity=sensitivity)) == ["ollama"]

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    def test_prefer_local_cannot_widen_the_regulated_set(
        self, all_providers: dict[str, MockProvider], sensitivity: Sensitivity
    ) -> None:
        request = InferenceRequest(
            messages=[{"role": "user", "content": "x"}],
            policy=RoutingPolicy(sensitivity=sensitivity, prefer_local=True),
        )
        router = ModelRouter(providers=all_providers)
        assert router.allowed_providers_for(request) == ["ollama"]

    def test_internal_uses_cloud_priority(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        allowed = router.allowed_providers_for(_request(sensitivity=Sensitivity.INTERNAL))
        assert allowed[0] == "anthropic"
        assert "ollama" not in allowed

    def test_public_uses_cheapest_priority(
        self, all_providers: dict[str, MockProvider]
    ) -> None:
        router = ModelRouter(providers=all_providers)
        allowed = router.allowed_providers_for(_request(sensitivity=Sensitivity.PUBLIC))
        assert allowed[0] == "deepinfra"


class TestRegulatedFallbackChainIsEmpty:
    """Fallback must never widen the regulated set either."""

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    def test_no_fallback_candidates(
        self, all_providers: dict[str, MockProvider], sensitivity: Sensitivity
    ) -> None:
        router = ModelRouter(providers=all_providers)
        request = _request(sensitivity=sensitivity)
        primary = router._select_provider(request)
        assert router._get_fallback_candidates(request, exclude=primary) == []

    @pytest.mark.parametrize("sensitivity", list(LOCAL_ONLY_SENSITIVITIES))
    async def test_local_failure_raises_and_never_calls_cloud(
        self, sensitivity: Sensitivity
    ) -> None:
        """When the local backend is down, no cloud provider is contacted."""
        providers = _providers("ollama", "deepinfra", "anthropic")
        providers["ollama"]._complete_mock.side_effect = RuntimeError("connection refused")

        router = ModelRouter(providers=providers)
        with pytest.raises(RuntimeError):
            await router.complete(_request(sensitivity=sensitivity))

        providers["deepinfra"]._complete_mock.assert_not_awaited()
        providers["anthropic"]._complete_mock.assert_not_awaited()
