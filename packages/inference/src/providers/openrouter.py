from __future__ import annotations

from .openai import OpenAIProvider

OPENROUTER_API_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4"


class OpenRouterProvider(OpenAIProvider):
    """Inference provider for the OpenRouter API.

    OpenRouter implements the OpenAI-compatible chat completions interface,
    so this provider inherits from OpenAIProvider and only adjusts the
    defaults (base URL, model, provider name, and extra headers).
    """

    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
        app_name: str = "AutoSwarm",
    ) -> None:
        super().__init__(
            api_key,
            model=model,
            base_url=OPENROUTER_API_URL,
            timeout=timeout,
        )
        self._app_name = app_name

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["HTTP-Referer"] = "https://autoswarm.dev"
        headers["X-Title"] = self._app_name
        return headers
