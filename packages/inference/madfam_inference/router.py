from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from .base import InferenceProvider
from .caching import PromptCacheManager
from .types import InferenceRequest, InferenceResponse, Sensitivity

logger = logging.getLogger(__name__)
_cache_manager = PromptCacheManager()


# Provider names expected by the router.  The keys in the providers dict
# passed to ModelRouter should use these identifiers.
LOCAL_PROVIDER = "ollama"
CLOUD_PRIORITY = [
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
CHEAPEST_PRIORITY = [
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


class ModelRouter:
    """Routes inference requests to providers based on sensitivity policy.

    Routing rules (applied in order):
    1. ``task_type`` — if the org config has a model assignment for the
       request's task type, jump directly to that provider and override
       the model name.
    2. ``require_local=True``  -> only use Ollama (local).
    3. ``restricted`` / ``confidential`` sensitivity -> Ollama only.
    4. ``internal`` -> first available cloud provider (CLOUD_PRIORITY).
    5. ``public``   -> cheapest available (CHEAPEST_PRIORITY).
    6. ``prefer_local=True`` prepends Ollama to the candidate list.

    If the primary candidate is unavailable the router falls through to
    the next candidate in the list.
    """

    def __init__(
        self,
        providers: dict[str, InferenceProvider],
        org_config: object | None = None,
    ) -> None:
        self._providers = providers
        self._org_config = org_config

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    def _select_provider(self, request: InferenceRequest) -> InferenceProvider:
        """Determine which provider to use for the given request."""
        policy = request.policy

        # ── Task-type routing (highest priority after require_local) ──
        if policy.task_type and self._org_config is not None:
            from .org_config import TaskType

            try:
                task_enum = TaskType(policy.task_type)
                assignments = getattr(self._org_config, "model_assignments", {})
                if task_enum in assignments:
                    assignment = assignments[task_enum]
                    provider = self._providers.get(assignment.provider)
                    if provider is not None:
                        policy.model_override = assignment.model
                        if assignment.max_tokens:
                            policy.max_tokens = assignment.max_tokens
                        if assignment.temperature is not None:
                            policy.temperature = assignment.temperature
                        logger.debug(
                            "Task-type routing: %s → %s/%s",
                            policy.task_type,
                            assignment.provider,
                            assignment.model,
                        )
                        return provider
                    logger.debug(
                        "Task-type assignment for %s points to %s, "
                        "but provider is not registered — falling through",
                        policy.task_type,
                        assignment.provider,
                    )
            except ValueError:
                pass  # Unknown task type — fall through to default routing

        # Hard constraint: local only
        if policy.require_local:
            provider = self._providers.get(LOCAL_PROVIDER)
            if provider is None:
                raise RuntimeError("require_local is True but no Ollama provider is registered.")
            return provider

        # Determine priority lists — org config can override defaults
        cloud_priority = CLOUD_PRIORITY
        cheapest_priority = CHEAPEST_PRIORITY
        if self._org_config is not None:
            org_cloud = getattr(self._org_config, "cloud_priority", None)
            org_cheap = getattr(self._org_config, "cheapest_priority", None)
            if org_cloud:
                cloud_priority = org_cloud
            if org_cheap:
                cheapest_priority = org_cheap

        candidates: list[str] = []

        if policy.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            # Sensitive data must stay local
            candidates = [LOCAL_PROVIDER]
        elif policy.sensitivity == Sensitivity.INTERNAL:
            candidates = list(cloud_priority)
        else:
            # PUBLIC -> cheapest first
            candidates = list(cheapest_priority)

        # If prefer_local, prepend Ollama so it's tried first
        if policy.prefer_local and LOCAL_PROVIDER not in candidates:
            candidates.insert(0, LOCAL_PROVIDER)
        elif policy.prefer_local and LOCAL_PROVIDER in candidates:
            candidates.remove(LOCAL_PROVIDER)
            candidates.insert(0, LOCAL_PROVIDER)

        # For multimodal requests, prefer vision-capable providers
        if request.has_media():
            vision_candidates = [
                n
                for n in candidates
                if self._providers.get(n) and self._providers[n].supports_vision
            ]
            if vision_candidates:
                candidates = vision_candidates

        for name in candidates:
            provider = self._providers.get(name)
            if provider is not None:
                return provider

        raise RuntimeError(
            f"No available provider for sensitivity={policy.sensitivity.value}. "
            f"Tried: {candidates}. Registered: {self.available_providers}"
        )

    def _get_fallback_candidates(
        self,
        request: InferenceRequest,
        exclude: InferenceProvider,
    ) -> list[str]:
        """Return provider names suitable for fallback, excluding the primary."""
        policy = request.policy
        if policy.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            return []  # Cannot fall back from local-only constraint

        if policy.sensitivity == Sensitivity.INTERNAL:
            candidates = list(CLOUD_PRIORITY)
        else:
            candidates = list(CHEAPEST_PRIORITY)
        return [
            n
            for n in candidates
            if self._providers.get(n) is not None and self._providers[n] is not exclude
        ]

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Route the request to the appropriate provider and return the response.

        Retries once on the primary provider (with 1s delay), then falls
        through to alternative providers before raising.
        """
        provider = self._select_provider(request)

        # Gap 7: Apply Anthropic prefix-cache breakpoints if applicable. The
        # cache manager may return a structured content-block list for the
        # system prompt; only the Anthropic provider consumes that form, and
        # plumbing the structured form through pydantic ``InferenceRequest``
        # would require schema work beyond this hot-path. For now we keep the
        # raw string on the request and let the Anthropic provider re-derive
        # cache breakpoints from the system prompt via ``_cache_manager``
        # directly. This also means the cache logic is idempotent if the
        # router is called twice on the same request.
        provider_name = type(provider).__name__.lower().replace("provider", "")
        new_messages, _system_with_cache = _cache_manager.apply_cache_breakpoints(
            request.messages,
            system_prompt=request.system_prompt or "",
            provider=provider_name,
        )
        request.messages = new_messages

        # Try primary provider with 1 retry.
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                return await provider.complete(request)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Provider %s failed (attempt %d/2): %s",
                    type(provider).__name__,
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    await asyncio.sleep(1.0)

        # Fallback: try remaining candidates.
        for name in self._get_fallback_candidates(request, exclude=provider):
            try:
                logger.info("Falling back to provider: %s", name)
                return await self._providers[name].complete(request)
            except Exception as exc:
                logger.warning("Fallback provider %s also failed: %s", name, exc)

        raise RuntimeError(f"All providers failed for request. Last error: {last_exc}")

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Route the request to the appropriate provider and stream the response."""
        provider = self._select_provider(request)
        async for chunk in provider.stream(request):
            yield chunk
