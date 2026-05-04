"""
Track B7: delegate — subagent delegation tool.
Track B8: credential_files — allowlisted credential file reads.
Track B2: web_tools — multi-provider web search and enhanced extraction.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# B2 — Web Tools
# ---------------------------------------------------------------------------


class WebSearchTool(BaseTool):
    """Multi-provider web search: Tavily (primary) → DuckDuckGo (fallback)."""

    name = "web_search"
    description = "Search the web and return ranked results with titles, URLs, and snippets."

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "provider": {
                    "type": "string",
                    "enum": ["tavily", "duckduckgo", "auto"],
                    "default": "auto",
                },
                "n": {"type": "integer", "default": 5, "description": "Number of results"},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query: str = kwargs["query"]
        n: int = int(kwargs.get("n", 5))

        # Try Tavily first
        tavily_key = os.environ.get("TAVILY_API_KEY")
        if tavily_key:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={"api_key": tavily_key, "query": query, "max_results": n},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results = [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "snippet": r.get("content", "")[:300],
                        }
                        for r in data.get("results", [])
                    ]
                    lines = [
                        f"{i + 1}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                        for i, r in enumerate(results)
                    ]
                    return ToolResult(
                        output="\n\n".join(lines),
                        data={"results": results, "provider": "tavily"},
                    )
            except Exception as exc:
                logger.warning("web_search Tavily failed: %s — falling back to DuckDuckGo", exc)

        # DuckDuckGo fallback
        try:
            from duckduckgo_search import DDGS  # type: ignore

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=n):
                    results.append(
                        {
                            "title": r.get("title"),
                            "url": r.get("href"),
                            "snippet": r.get("body", "")[:300],
                        }
                    )
            lines = [
                f"{i + 1}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                for i, r in enumerate(results)
            ]
            return ToolResult(
                output="\n\n".join(lines),
                data={"results": results, "provider": "duckduckgo"},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"All web search providers failed: {exc}")


class WebExtractTool(BaseTool):
    """Extract and convert web page content to Markdown."""

    name = "web_extract"
    description = "Fetch a URL and return its content as clean Markdown text."

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch and parse"},
                "format": {
                    "type": "string",
                    "enum": ["markdown", "text", "html"],
                    "default": "markdown",
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url: str = kwargs["url"]
        fmt: str = kwargs.get("format", "markdown")

        # Try Playwright browser_extract first
        try:
            from selva_tools.browser import browser_extract

            content = await browser_extract(url)
        except Exception as exc:
            logger.warning(
                "web_extract: browser_extract failed (%s) — falling back to requests",
                exc,
            )
            try:
                import httpx

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers={"User-Agent": "AutoSwarm-WebExtract/1.0"})
                    resp.raise_for_status()
                    content = resp.text
            except Exception as req_exc:
                return ToolResult(success=False, error=f"Web extract failed: {req_exc}")

        if fmt == "markdown":
            try:
                from markdownify import markdownify  # type: ignore

                content = markdownify(content)
            except ImportError:
                pass  # Return raw content if markdownify not installed

        # Cap output
        if len(content) > 20_000:
            content = content[:20_000] + "\n\n[... content truncated ...]"

        return ToolResult(output=content, data={"url": url, "format": fmt, "chars": len(content)})


# ---------------------------------------------------------------------------
# B7 — Subagent Delegation
# ---------------------------------------------------------------------------


class DelegateTaskTool(BaseTool):
    """Spawn an isolated ACP subagent to handle a parallel workstream."""

    name = "delegate_task"
    description = (
        "Delegate a task to an isolated ACP subagent. "
        "The subagent runs the full Phase I-IV pipeline on the given task description "
        "and returns a result summary."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Full description of the task for the subagent",
                },
                "target_url": {
                    "type": "string",
                    "description": "Optional URL for the subagent to analyze",
                },
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skill names to attach to the subagent context",
                },
                "timeout": {
                    "type": "number",
                    "default": 300,
                    "description": "Max seconds to wait for subagent completion",
                },
            },
            "required": ["task_description"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        task_description: str = kwargs["task_description"]
        target_url: str = kwargs.get("target_url", "")
        skills: list[str] = kwargs.get("skills") or []
        timeout: float = float(kwargs.get("timeout", 300))

        try:
            from nexus_api.tasks.acp_tasks import run_acp_workflow_task
        except ImportError:
            return ToolResult(
                success=False,
                error="ACP task queue not available — running outside nexus-api context.",
            )

        try:
            import asyncio

            task = run_acp_workflow_task.delay(
                target_url or "internal://delegate",
                metadata={
                    "task_description": task_description,
                    "skills": skills,
                    "subagent": True,
                },
            )
            # Poll for result
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                if task.ready():
                    break
                await asyncio.sleep(2.0)

            if not task.ready():
                return ToolResult(
                    output=(
                        f"Subagent task dispatched (id={task.id})"
                        f" but did not complete within {timeout}s."
                    ),
                    data={"task_id": task.id, "status": "pending"},
                )
            result = task.result or {}
            return ToolResult(
                output=result.get("prd", "Subagent completed."),
                data={"task_id": task.id, "status": "complete", "result": result},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Delegation failed: {exc}")


# ---------------------------------------------------------------------------
# B8 — Credential File Passthrough
# ---------------------------------------------------------------------------

_CRED_DIR = Path.home() / ".autoswarm" / "credentials"
_ALLOWED_EXTENSIONS = {".yaml", ".yml", ".json", ".env"}


class ReadCredentialFileTool(BaseTool):
    """Read an allowlisted credential file from ~/.autoswarm/credentials/."""

    name = "read_credential_file"
    description = (
        "Read a credential file from ~/.autoswarm/credentials/. "
        "Only files within that directory are accessible — no path traversal."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename within ~/.autoswarm/credentials/ (e.g. 'github.yaml')",
                },
            },
            "required": ["filename"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        filename: str = kwargs["filename"]
        # Strict path containment
        try:
            target = (_CRED_DIR / filename).resolve()
        except Exception as exc:
            return ToolResult(success=False, error=f"Invalid filename: {exc}")

        if not str(target).startswith(str(_CRED_DIR.resolve())):
            return ToolResult(success=False, error="Path traversal denied.")
        if target.suffix not in _ALLOWED_EXTENSIONS:
            return ToolResult(
                success=False,
                error=(f"File type '{target.suffix}' not allowed. Allowed: {_ALLOWED_EXTENSIONS}"),
            )
        if not target.exists():
            return ToolResult(success=False, error=f"Credential file not found: {filename}")

        try:
            content = target.read_text(encoding="utf-8")
            return ToolResult(
                output=content[:4096],
                data={"filename": filename, "path": str(target)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
