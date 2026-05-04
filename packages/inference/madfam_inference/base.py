from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .types import InferenceRequest, InferenceResponse


class InferenceProvider(ABC):
    """Base class for all inference providers.

    Each provider wraps a specific LLM API (Anthropic, OpenAI, Ollama, etc.)
    and exposes a uniform interface for completion, streaming, and model listing.
    """

    name: str

    @property
    def supports_vision(self) -> bool:
        """Whether this provider can process image content in messages.

        Override in subclasses that support vision/multimodal models.
        """
        return False

    @abstractmethod
    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Send a completion request and return the full response."""
        ...

    @abstractmethod
    def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Stream completion tokens as they arrive.

        Implementations are async generators (``async def`` + ``yield``).
        The abstract is plain ``def`` returning ``AsyncIterator[str]``
        because async generators ARE iterators (not coroutines that
        return iterators) — using ``async def`` here would type the
        callable as ``Coroutine[..., AsyncIterator[str]]`` and break
        ``async for`` at every call site.
        """
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return a list of model identifiers available from this provider."""
        ...
