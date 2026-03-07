"""Web search provider using Tavily API."""

from __future__ import annotations

import logging

import httpx

from .types import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


class WebSearchProvider(SearchProvider):
    """Search provider backed by the Tavily API.

    Falls back to an empty result list when the API key is not set or
    the API is unreachable.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.tavily.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            logger.debug("Tavily API key not set; returning empty results")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": 5,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results: list[SearchResult] = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", "")[:500],
                    )
                )
            return results
        except Exception:
            logger.warning("Tavily search failed", exc_info=True)
            return []
