"""Memory manager — orchestrates per-agent memory stores and auto-injection."""

from __future__ import annotations

import logging
from typing import Any

from .embeddings import EmbeddingProvider, get_embedding_provider
from .store import MemoryStore

logger = logging.getLogger(__name__)

# Default persistence directory
DEFAULT_PERSIST_DIR = "/tmp/selva-memory"  # noqa: S108


class MemoryManager:
    """Central manager for per-agent memory stores.

    Provides:
    - Lazy-loading of per-agent MemoryStore instances
    - Context retrieval for LLM prompt injection
    - Cleanup and persistence orchestration
    """

    _instance: MemoryManager | None = None

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        persist_dir: str = DEFAULT_PERSIST_DIR,
        dim: int | None = None,
    ) -> None:
        self._embedder = embedding_provider or get_embedding_provider()
        self._dim = dim or self._embedder.dim
        self._persist_dir = persist_dir
        self._stores: dict[str, MemoryStore] = {}

    @classmethod
    def get_instance(cls, **kwargs: Any) -> MemoryManager:
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def get_store(self, agent_id: str) -> MemoryStore:
        """Get or create a memory store for the given agent."""
        if agent_id not in self._stores:
            self._stores[agent_id] = MemoryStore(
                agent_id=agent_id,
                embedding_provider=self._embedder,
                dim=self._dim,
                persist_dir=self._persist_dir,
            )
        return self._stores[agent_id]

    async def get_relevant_context(self, agent_id: str, query: str, top_k: int = 5) -> str:
        """Retrieve relevant memories for injection into the LLM prompt.

        Returns a formatted string of relevant memory entries.
        """
        store = self.get_store(agent_id)
        if store.count == 0:
            return ""

        entries = await store.search(query, top_k=top_k)
        if not entries:
            return ""

        lines = ["## Relevant Memories"]
        for entry in entries:
            score = entry.metadata.get("_similarity_score", 0)
            lines.append(f"- [{score:.2f}] {entry.text}")

        return "\n".join(lines)

    async def store_memory(
        self, agent_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        """Store a new memory for an agent."""
        store = self.get_store(agent_id)
        return await store.store(text, metadata)


def get_memory_manager(**kwargs: Any) -> MemoryManager:
    """Get the singleton memory manager."""
    return MemoryManager.get_instance(**kwargs)
