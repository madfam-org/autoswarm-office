"""Inference helper for LangGraph worker nodes."""

from __future__ import annotations

import logging
from typing import Any

from autoswarm_inference import ModelRouter, InferenceRequest, InferenceResponse
from autoswarm_inference.types import RoutingPolicy, Sensitivity

from .config import get_settings

logger = logging.getLogger(__name__)


def build_model_router() -> ModelRouter:
    """Instantiate a ModelRouter with available providers from config.

    Each provider key maps to a dict of connection parameters.  The
    ``ModelRouter`` uses these to construct ``InferenceProvider``
    instances internally.  Ollama is always included as the local
    fallback provider.
    """
    settings = get_settings()
    providers: dict[str, dict[str, str]] = {}

    if settings.anthropic_api_key:
        providers["anthropic"] = {"api_key": settings.anthropic_api_key}
    if settings.openai_api_key:
        providers["openai"] = {"api_key": settings.openai_api_key}
    if settings.openrouter_api_key:
        providers["openrouter"] = {"api_key": settings.openrouter_api_key}

    # Always include ollama as local provider.
    providers["ollama"] = {"base_url": settings.ollama_base_url}

    return ModelRouter(providers=providers)


async def call_llm(
    router: ModelRouter,
    messages: list[dict[str, str]],
    system_prompt: str = "",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
) -> str:
    """Convenience wrapper that calls the LLM and returns content.

    Falls back to a placeholder response if no provider is available or
    the inference call fails for any reason.  This ensures that worker
    graph nodes degrade gracefully when no API keys are configured.
    """
    try:
        request = InferenceRequest(
            messages=messages,
            system_prompt=system_prompt or None,
            policy=RoutingPolicy(sensitivity=sensitivity),
        )
        response: InferenceResponse = await router.complete(request)
        return response.content
    except Exception as exc:
        logger.warning("LLM call failed: %s. Using placeholder response.", exc)
        last_content = messages[-1].get("content", "") if messages else ""
        return (
            f"[LLM unavailable — placeholder response for: "
            f"{last_content[:200]}]"
        )
