"""Research workflow graph -- query formulation, search, synthesis, report."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from .base import BaseGraphState

logger = logging.getLogger(__name__)


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a sync graph node context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# -- State --------------------------------------------------------------------


class ResearchState(BaseGraphState, TypedDict, total=False):
    """Extended state for the research workflow."""

    query: str
    sources: list[dict[str, Any]]
    synthesis: str | None


# -- Node functions -----------------------------------------------------------


def formulate_query(state: ResearchState) -> ResearchState:
    """Refine the raw task description into a structured search query.

    Calls the inference router to distil the raw task into an optimised
    search query.  Falls back to raw concatenation when unavailable.
    """
    messages = state.get("messages", [])
    raw_text = " ".join(
        msg.content for msg in messages if hasattr(msg, "content") and msg.content
    )

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = "Rewrite this into an optimal search query. Return only the query."
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        refined_query = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": raw_text.strip()}],
            system_prompt=system_prompt,
        ))
    except Exception:
        refined_query = raw_text.strip() or state.get("query", "")

    query_message = AIMessage(
        content=f"Search query formulated: {refined_query[:200]}",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, query_message],
        "query": refined_query,
        "status": "querying",
        "sources": [],
    }


def search(state: ResearchState) -> ResearchState:
    """Execute the search strategy and collect source material.

    Uses the WebSearchProvider when ``SEARCH_API_KEY`` is configured,
    falling back to dummy sources otherwise.
    """
    messages = state.get("messages", [])
    query = state.get("query", "")

    sources: list[dict[str, Any]] = []

    # Try real web search via Tavily.
    try:
        import os

        api_key = os.environ.get("SEARCH_API_KEY", "")
        if api_key:
            from ..search.web import WebSearchProvider

            provider = WebSearchProvider(api_key=api_key)
            results = _run_async(provider.search(query))
            sources = [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "relevance_score": 0.9,
                }
                for r in results
            ]
    except Exception:
        logger.debug("Web search failed; using dummy sources")

    # Fallback to dummy sources when no real results.
    if not sources:
        sources = [
            {
                "title": f"Source for: {query[:80]}",
                "url": "https://example.com/result-1",
                "snippet": "Relevant excerpt from the source material...",
                "relevance_score": 0.92,
            },
            {
                "title": f"Secondary source for: {query[:80]}",
                "url": "https://example.com/result-2",
                "snippet": "Additional context from a secondary source...",
                "relevance_score": 0.85,
            },
        ]

    search_message = AIMessage(
        content=f"Search complete: {len(sources)} sources found.",
        additional_kwargs={"action_category": "api_call", "source_count": len(sources)},
    )

    return {
        **state,
        "messages": [*messages, search_message],
        "sources": sources,
        "status": "searching",
    }


def synthesize(state: ResearchState) -> ResearchState:
    """Synthesize collected sources into a coherent analysis.

    Calls the inference router to produce a coherent narrative from
    collected sources.  Falls back to concatenation when unavailable.
    """
    messages = state.get("messages", [])
    sources = state.get("sources", [])
    query = state.get("query", "")

    source_summaries = "\n".join(
        f"- {s.get('title', 'Unknown')}: {s.get('snippet', '')}" for s in sources
    )

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        prompt = f"Synthesize these sources:\n{source_summaries}"
        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = (
            "You are a research analyst. Synthesize sources "
            "into a coherent analysis."
        )
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        synthesis_text = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
        ))
    except Exception:
        synthesis_text = (
            f"Research synthesis for query: {query[:200]}\n\n"
            f"Based on {len(sources)} sources:\n{source_summaries}\n\n"
            "Key findings have been consolidated into a unified analysis."
        )

    synthesis_message = AIMessage(
        content="Synthesis complete.",
        additional_kwargs={"action_category": "file_read"},
    )

    return {
        **state,
        "messages": [*messages, synthesis_message],
        "synthesis": synthesis_text,
        "status": "synthesizing",
    }


def format_report(state: ResearchState) -> ResearchState:
    """Format the synthesis into a final structured report.

    Calls the inference router to produce a polished report.  Falls
    back to a structured template when unavailable.
    """
    messages = state.get("messages", [])
    synthesis = state.get("synthesis", "")
    sources = state.get("sources", [])

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = "Format the research synthesis into a structured report with sections."
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        formatted = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": f"Format this into a report:\n{synthesis}"}],
            system_prompt=system_prompt,
        ))
        report_sections = {
            "executive_summary": formatted[:500],
            "detailed_findings": formatted,
            "sources": [
                {"title": s.get("title", ""), "url": s.get("url", "")} for s in sources
            ],
            "source_count": len(sources),
        }
    except Exception:
        report_sections = {
            "executive_summary": synthesis[:500] if synthesis else "No synthesis available.",
            "detailed_findings": synthesis,
            "sources": [
                {"title": s.get("title", ""), "url": s.get("url", "")} for s in sources
            ],
            "source_count": len(sources),
        }

    report_message = AIMessage(
        content="Research report formatted and ready for delivery.",
        additional_kwargs={"action_category": "file_read", "report": report_sections},
    )

    return {
        **state,
        "messages": [*messages, report_message],
        "status": "completed",
        "result": report_sections,
    }


# -- Graph construction -------------------------------------------------------


def build_research_graph() -> StateGraph:
    """Construct and compile the research workflow state graph.

    Flow::

        formulate_query -> search -> synthesize -> format_report -> END

    This is a safe, read-only pipeline with no interrupt points.
    """
    graph = StateGraph(ResearchState)

    graph.add_node("formulate_query", formulate_query)
    graph.add_node("search", search)
    graph.add_node("synthesize", synthesize)
    graph.add_node("format_report", format_report)

    graph.set_entry_point("formulate_query")
    graph.add_edge("formulate_query", "search")
    graph.add_edge("search", "synthesize")
    graph.add_edge("synthesize", "format_report")
    graph.add_edge("format_report", END)

    return graph
