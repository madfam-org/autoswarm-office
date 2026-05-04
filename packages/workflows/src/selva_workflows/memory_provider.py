"""
Track D3: Memory Provider Plugin ABC
Mirrors Hermes' plugins/memory/memory_provider.py — swappable memory backends.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract Base
# ---------------------------------------------------------------------------


class MemoryProvider(ABC):
    """
    Abstract memory provider — allows swapping between SQLite, Redis,
    Postgres, or any custom backend.

    Mirrors Hermes' memory provider ABC which enables single-select
    memory pluggability via config.
    """

    @abstractmethod
    async def insert(self, episode: dict[str, Any]) -> None:
        """Persist an episode to the memory store."""

    @abstractmethod
    async def recall(self, query: str, top_k: int = 5) -> list[str]:
        """Semantic/FTS recall: return the top-k most relevant episodes."""

    @abstractmethod
    async def compact(self) -> int:
        """Summarize and compact old episodes. Returns number of rows compacted."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return a health/status dict for monitoring."""


# ---------------------------------------------------------------------------
# SQLite Provider (wraps existing EdgeMemoryDB)
# ---------------------------------------------------------------------------


class SQLiteMemoryProvider(MemoryProvider):
    """Default provider — wraps the existing SQLite + FTS5 EdgeMemoryDB."""

    def __init__(self) -> None:
        try:
            from selva_skills import get_skill_registry  # noqa: F401
            from selva_workflows.memory import EdgeMemoryDB  # type: ignore

            self._db = EdgeMemoryDB()
        except ImportError:
            self._db = None
            logger.warning("SQLiteMemoryProvider: EdgeMemoryDB not available.")

    async def insert(self, episode: dict[str, Any]) -> None:
        if self._db:
            self._db.insert(episode)

    async def recall(self, query: str, top_k: int = 5) -> list[str]:
        if self._db:
            rows = self._db.recall(query, top_k=top_k)
            return [str(r) for r in rows]
        return []

    async def compact(self) -> int:
        if self._db and hasattr(self._db, "compact"):
            return self._db.compact()
        return 0

    async def health(self) -> dict[str, Any]:
        return {"provider": "sqlite", "available": self._db is not None}


# ---------------------------------------------------------------------------
# Redis Provider (short-context ephemeral recall)
# ---------------------------------------------------------------------------


class RedisMemoryProvider(MemoryProvider):
    """
    Ephemeral in-memory provider backed by Redis sorted sets.
    Use for short-context recall where persistence across restarts is not needed.
    """

    _KEY = "autoswarm:memory:episodes"
    _MAX_EPISODES = 200

    def __init__(self) -> None:
        # Type as Optional so the absent-redis branch is well-typed.
        self._redis: Any = None
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            )
        except ImportError:
            logger.warning("RedisMemoryProvider: redis.asyncio not installed.")

    async def insert(self, episode: dict[str, Any]) -> None:
        if not self._redis:
            return
        import json
        import time

        await self._redis.zadd(self._KEY, {json.dumps(episode, default=str): time.time()})
        # Keep only the last _MAX_EPISODES
        await self._redis.zremrangebyrank(self._KEY, 0, -(self._MAX_EPISODES + 1))

    async def recall(self, query: str, top_k: int = 5) -> list[str]:
        if not self._redis:
            return []
        entries = await self._redis.zrevrangebyscore(self._KEY, "+inf", "-inf", start=0, num=50)
        query_lower = query.lower()
        matches = []
        for entry in entries:
            text = entry.decode(errors="replace")
            if query_lower in text.lower():
                matches.append(text)
                if len(matches) >= top_k:
                    break
        return matches

    async def compact(self) -> int:
        if not self._redis:
            return 0
        count = await self._redis.zcard(self._KEY)
        if count > self._MAX_EPISODES:
            remove = count - self._MAX_EPISODES
            await self._redis.zremrangebyrank(self._KEY, 0, remove - 1)
            return remove
        return 0

    async def health(self) -> dict[str, Any]:
        if not self._redis:
            return {"provider": "redis", "available": False}
        try:
            await self._redis.ping()
            count = await self._redis.zcard(self._KEY)
            return {"provider": "redis", "available": True, "episode_count": count}
        except Exception as exc:
            return {"provider": "redis", "available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[MemoryProvider]] = {
    "sqlite": SQLiteMemoryProvider,
    "redis": RedisMemoryProvider,
}


def get_memory_provider() -> MemoryProvider:
    """Return the configured memory provider (singleton per process)."""
    name = os.environ.get("AUTOSWARM_MEMORY_PROVIDER", "sqlite")
    cls = _PROVIDERS.get(name)
    if cls is None:
        logger.warning("Unknown memory provider '%s', falling back to sqlite.", name)
        cls = SQLiteMemoryProvider
    return cls()
