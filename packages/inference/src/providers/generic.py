from __future__ import annotations

from .openai import OpenAIProvider


class GenericOpenAIProvider(OpenAIProvider):
    """Inference provider for any OpenAI-compatible API endpoint.

    Thin wrapper that lets callers specify an arbitrary base URL, API key,
    and model name.  Useful for self-hosted vLLM, LiteLLM, LocalAI,
    text-generation-inference, and similar services that expose the
    OpenAI chat completions interface.

    Example:
        provider = GenericOpenAIProvider(
            base_url="http://my-vllm:8000/v1",
            api_key="token-xyz",
            model="meta-llama/Llama-3-70b-instruct",
        )
    """

    name = "generic"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str,
        timeout: float = 120.0,
        provider_name: str = "generic",
    ) -> None:
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
        )
        self.name = provider_name
