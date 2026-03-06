"""Research workflow graph -- query formulation, search, synthesis, report."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph

from .base import BaseGraphState

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class ResearchState(BaseGraphState, TypedDict, total=False):
    """Extended state for the research workflow."""

    query: str
    sources: list[dict[str, Any]]
    synthesis: str | None


# -- Node functions -----------------------------------------------------------


def formulate_query(state: ResearchState) -> ResearchState:
    """Refine the raw task description into a structured search query.

    Extracts key terms and intent from the conversation messages to
    build an effective search strategy.
    """
    messages = state.get("messages", [])
    raw_text = " ".join(
        msg.content for msg in messages if hasattr(msg, "content") and msg.content
    )

    # In production the inference engine rewrites the query for optimal
    # retrieval.  Here we use the raw concatenation as the query.
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

    This is a read-only operation -- no interrupts required.  In
    production this node calls external search APIs (web, internal
    knowledge base, CRM) and collects results.
    """
    messages = state.get("messages", [])
    query = state.get("query", "")

    # Simulated search results.  Real implementation dispatches to
    # configured search providers.
    sources: list[dict[str, Any]] = [
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

    Combines information from all sources, resolves contradictions, and
    produces a unified narrative.
    """
    messages = state.get("messages", [])
    sources = state.get("sources", [])
    query = state.get("query", "")

    source_summaries = "\n".join(
        f"- {s.get('title', 'Unknown')}: {s.get('snippet', '')}" for s in sources
    )

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

    Produces a human-readable report with citations and
    recommendations.
    """
    messages = state.get("messages", [])
    synthesis = state.get("synthesis", "")
    sources = state.get("sources", [])

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
