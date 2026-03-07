"""Search result types and provider ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    """Abstract base class for search backends."""

    @abstractmethod
    async def search(self, query: str) -> list[SearchResult]:
        """Execute a search query and return results."""
