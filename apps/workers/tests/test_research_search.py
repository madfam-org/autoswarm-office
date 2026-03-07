"""Tests for the research graph web search integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoswarm_workers.search.types import SearchResult


class TestWebSearchProvider:
    """WebSearchProvider returns results from Tavily."""

    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_workers.search.web.httpx.AsyncClient", return_value=mock_client):
            from autoswarm_workers.search.web import WebSearchProvider

            provider = WebSearchProvider(api_key="test-key")
            results = await provider.search("test query")

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].title == "Result 1"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_api_key(self) -> None:
        from autoswarm_workers.search.web import WebSearchProvider

        provider = WebSearchProvider(api_key="")
        results = await provider.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("API down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("autoswarm_workers.search.web.httpx.AsyncClient", return_value=mock_client):
            from autoswarm_workers.search.web import WebSearchProvider

            provider = WebSearchProvider(api_key="test-key")
            results = await provider.search("test query")
            assert results == []

    def test_result_format(self) -> None:
        result = SearchResult(
            title="Test", url="https://example.com", snippet="A snippet"
        )
        assert result.title == "Test"
        assert result.url == "https://example.com"
        assert result.snippet == "A snippet"

    def test_research_graph_search_falls_back_to_dummy(self) -> None:
        """search node uses dummy sources when no SEARCH_API_KEY."""
        from langchain_core.messages import AIMessage

        from autoswarm_workers.graphs.research import search

        with patch.dict("os.environ", {"SEARCH_API_KEY": ""}, clear=False):
            result = search({
                "messages": [AIMessage(content="query formulated")],
                "query": "test search",
            })

        assert len(result["sources"]) == 2
        assert result["sources"][0]["url"] == "https://example.com/result-1"
