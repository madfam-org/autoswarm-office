"""Web tools: search, fetch, scrape."""

from __future__ import annotations

from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult
from .http_tools import _build_safe_request_kwargs

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_FETCH_LENGTH = 50_000


def _coerce_max_length(value: Any, default: int = 10_000, *, upper: int = MAX_FETCH_LENGTH) -> int:
    """Normalize max_length input from tool schemas and callers."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return 1
    return min(parsed, upper)


async def _safe_fetch(url: str, max_length: int) -> tuple[str, int, str]:
    """Fetch URL with SSRF-safe request kwargs and return (text, status_code, original_url)."""
    import httpx

    request_kwargs, original_url = _build_safe_request_kwargs(
        "GET",
        url,
        {"User-Agent": "Selva-Tools/1.0"},
    )

    transport = httpx.AsyncHTTPTransport(retries=0)
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT_SECONDS,
        transport=transport,
        trust_env=False,
    ) as client:
        resp = await client.request(**request_kwargs)

    resp.raise_for_status()
    return resp.text[:max_length], resp.status_code, original_url


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web using a query (requires TAVILY_API_KEY or falls back to stub)"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import os

        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)
        api_key = os.environ.get("TAVILY_API_KEY")

        if not api_key:
            return ToolResult(
                output=f"Web search for '{query}' — no TAVILY_API_KEY configured",
                data={"results": [], "query": query},
            )

        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": max_results,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                output = "\n".join(f"- {r.get('title', '')}: {r.get('url', '')}" for r in results)
                return ToolResult(output=output, data={"results": results})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch the content of a URL"
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_length": {
                    "type": "integer",
                    "description": "Max response length in chars",
                    "default": 10000,
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        url = kwargs.get("url", "")
        max_length = _coerce_max_length(kwargs.get("max_length", 10_000))
        try:
            text, status_code, resolved_url = await _safe_fetch(url, max_length)
            return ToolResult(
                output=text,
                data={"status_code": status_code, "url": resolved_url},
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(success=False, error=str(exc))
        except ValueError as exc:
            return ToolResult(success=False, error=f"URL validation failed: {exc}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class WebScrapeTool(BaseTool):
    name = "web_scrape"
    description = "Fetch a URL and extract text content (strips HTML tags)"
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "max_length": {"type": "integer", "default": 10000},
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import html
        import re

        import httpx

        url = kwargs.get("url", "")
        max_length = _coerce_max_length(kwargs.get("max_length", 10_000))
        try:
            text, status_code, _resolved_url = await _safe_fetch(url, max_length * 2)
            # Simple HTML tag stripping
            text = re.sub(r"<[^>]+>", "", text)
            text = html.unescape(text)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()[:max_length]
            return ToolResult(output=text, data={"status_code": status_code})
        except httpx.HTTPStatusError as exc:
            return ToolResult(success=False, error=str(exc))
        except ValueError as exc:
            return ToolResult(success=False, error=f"URL validation failed: {exc}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
