from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .types import InferenceRequest, InferenceResponse


class InferenceProvider(ABC):
    """Base class for all inference providers.

    Each provider wraps a specific LLM API (Anthropic, OpenAI, Ollama, etc.)
    and exposes a uniform interface for completion, streaming, and model listing.
    """

    name: str

    @abstractmethod
    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Send a completion request and return the full response."""
        ...

    @abstractmethod
    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Stream completion tokens as they arrive."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return a list of model identifiers available from this provider."""
        ...
