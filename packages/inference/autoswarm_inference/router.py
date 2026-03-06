from __future__ import annotations

from collections.abc import AsyncIterator

from .base import InferenceProvider
from .types import InferenceRequest, InferenceResponse, Sensitivity


# Provider names expected by the router.  The keys in the providers dict
# passed to ModelRouter should use these identifiers.
LOCAL_PROVIDER = "ollama"
CLOUD_PRIORITY = ["anthropic", "openai", "openrouter"]
CHEAPEST_PRIORITY = ["openrouter", "openai", "anthropic"]


class ModelRouter:
    """Routes inference requests to providers based on sensitivity policy.

    Routing rules:
    - require_local=True  -> only use Ollama (local).
    - restricted / confidential sensitivity -> prefer Ollama, fail if unavailable.
    - internal -> first available cloud provider (anthropic > openai > openrouter).
    - public   -> cheapest available (openrouter > openai > anthropic).
    - prefer_local=True adds Ollama as the first candidate regardless of sensitivity.

    If the primary candidate is unavailable the router falls through to the
    next candidate in the list.
    """

    def __init__(self, providers: dict[str, InferenceProvider]) -> None:
        self._providers = providers

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    def _select_provider(self, request: InferenceRequest) -> InferenceProvider:
        """Determine which provider to use for the given request."""
        policy = request.policy

        # Hard constraint: local only
        if policy.require_local:
            provider = self._providers.get(LOCAL_PROVIDER)
            if provider is None:
                raise RuntimeError(
                    "require_local is True but no Ollama provider is registered."
                )
            return provider

        candidates: list[str] = []

        if policy.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            # Sensitive data must stay local
            candidates = [LOCAL_PROVIDER]
        elif policy.sensitivity == Sensitivity.INTERNAL:
            candidates = list(CLOUD_PRIORITY)
        else:
            # PUBLIC -> cheapest first
            candidates = list(CHEAPEST_PRIORITY)

        # If prefer_local, prepend Ollama so it's tried first
        if policy.prefer_local and LOCAL_PROVIDER not in candidates:
            candidates.insert(0, LOCAL_PROVIDER)
        elif policy.prefer_local and LOCAL_PROVIDER in candidates:
            candidates.remove(LOCAL_PROVIDER)
            candidates.insert(0, LOCAL_PROVIDER)

        for name in candidates:
            provider = self._providers.get(name)
            if provider is not None:
                return provider

        raise RuntimeError(
            f"No available provider for sensitivity={policy.sensitivity.value}. "
            f"Tried: {candidates}. Registered: {self.available_providers}"
        )

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Route the request to the appropriate provider and return the response."""
        provider = self._select_provider(request)
        return await provider.complete(request)

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Route the request to the appropriate provider and stream the response."""
        provider = self._select_provider(request)
        async for chunk in provider.stream(request):
            yield chunk
