"""Experience-based learning (IER) — agents learn from prior task outcomes."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .embeddings import EmbeddingProvider
from .store import MemoryStore

logger = logging.getLogger(__name__)

# Temporal decay half-life in days
DECAY_HALF_LIFE_DAYS = 30.0


@dataclass
class ExperienceRecord:
    """A record of a completed task with its approach and outcome."""

    task_pattern: str  # Description of what was done
    approach: str  # How it was done
    outcome: str  # Result summary
    score: float = 0.0  # 0.0 to 1.0 (success rate, approval rate)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperienceStore:
    """Per-role experience store for learning task shortcuts.

    Uses a MemoryStore internally for semantic search over past experiences.
    Records are stored per role (not per agent instance) so new agents benefit.
    """

    def __init__(
        self,
        role: str,
        embedding_provider: EmbeddingProvider,
        persist_dir: str | None = None,
    ) -> None:
        self.role = role
        # Use a dedicated memory store with "role:" prefix for isolation
        self._store = MemoryStore(
            agent_id=f"experience:{role}",
            embedding_provider=embedding_provider,
            dim=embedding_provider.dim,
            persist_dir=persist_dir,
        )

    async def record(self, experience: ExperienceRecord) -> str:
        """Record a completed task experience."""
        metadata = {
            "approach": experience.approach,
            "outcome": experience.outcome,
            "score": experience.score,
            "type": "experience",
            **experience.metadata,
        }
        return await self._store.store(
            text=experience.task_pattern,
            metadata=metadata,
        )

    async def search_similar(
        self, task_description: str, top_k: int = 5, min_score: float = 0.5
    ) -> list[ExperienceRecord]:
        """Search for relevant past experiences for a new task.

        Applies temporal decay to scores: older experiences lose weight.
        """
        entries = await self._store.search(task_description, top_k=top_k * 2)

        experiences: list[tuple[float, ExperienceRecord]] = []
        now = datetime.now(UTC)

        for entry in entries:
            score = entry.metadata.get("score", 0.0)
            if score < min_score:
                continue

            # Apply temporal decay
            try:
                created = datetime.fromisoformat(entry.created_at)
                days_old = (now - created).total_seconds() / 86400
                decay = math.exp(-math.log(2) * days_old / DECAY_HALF_LIFE_DAYS)
                adjusted_score = score * decay
            except Exception:
                adjusted_score = score

            record = ExperienceRecord(
                task_pattern=entry.text,
                approach=entry.metadata.get("approach", ""),
                outcome=entry.metadata.get("outcome", ""),
                score=adjusted_score,
                created_at=entry.created_at,
                metadata=entry.metadata,
            )
            experiences.append((adjusted_score, record))

        # Sort by adjusted score descending, take top_k
        experiences.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in experiences[:top_k]]

    async def get_shortcuts(self, task_description: str, threshold: float = 0.8) -> list[str]:
        """Get high-confidence approach shortcuts for a task.

        Returns approach strings from experiences with score >= threshold.
        """
        experiences = await self.search_similar(task_description, top_k=3, min_score=threshold)
        return [e.approach for e in experiences if e.approach]

    @property
    def count(self) -> int:
        return self._store.count

    async def get_count(self) -> int:
        return await self._store.get_count()
