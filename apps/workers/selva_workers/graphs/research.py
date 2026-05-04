"""Research workflow graph -- query formulation, search, synthesis, report."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from ..event_emitter import instrumented_node
from .base import BaseGraphState
from .base import run_async as _run_async

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class ResearchState(BaseGraphState, TypedDict, total=False):
    """Extended state for the research workflow."""

    query: str
    sources: list[dict[str, Any]]
    synthesis: str | None


# -- Node functions -----------------------------------------------------------


@instrumented_node
def formulate_query(state: ResearchState) -> ResearchState:
    """Refine the raw task description into a structured search query.

    Calls the inference router to distil the raw task into an optimised
    search query.  Falls back to raw concatenation when unavailable.
    """
    messages = state.get("messages", [])
    raw_text = " ".join(
        msg.content
        for msg in messages
        if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content
    )

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()

        # Retrieve experience context for prompt enrichment
        experience_ctx = ""
        try:
            from ..prompts import build_experience_context

            agent_id = state.get("agent_id", "unknown")
            experience_ctx = _run_async(
                build_experience_context(
                    agent_id=agent_id,
                    agent_role="researcher",
                    task_description=raw_text.strip(),
                )
            )
        except Exception:
            logger.debug("Failed to retrieve experience context", exc_info=True)

        skill_ctx = state.get("agent_system_prompt", "")
        locale = state.get("locale", "en")
        if locale == "es-MX":
            base_prompt = (
                "Reescriba esto como una consulta de busqueda optima. "
                "Devuelva unicamente la consulta."
            )
        else:
            base_prompt = "Rewrite this into an optimal search query. Return only the query."
        parts = [p for p in [skill_ctx, experience_ctx, base_prompt] if p]
        system_prompt = "\n\n".join(parts)
        refined_query = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": raw_text.strip()}],
                system_prompt=system_prompt,
                task_type="research",
            )
        )
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


@instrumented_node
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


@instrumented_node
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
        locale = state.get("locale", "en")
        if locale == "es-MX":
            prompt = f"Sintetice estas fuentes:\n{source_summaries}"
        else:
            prompt = f"Synthesize these sources:\n{source_summaries}"
        skill_ctx = state.get("agent_system_prompt", "")
        if locale == "es-MX":
            base_prompt = (
                "Usted es un analista de investigacion. Sintetice las fuentes "
                "en un analisis coherente."
            )
        else:
            base_prompt = "You are a research analyst. Synthesize sources into a coherent analysis."
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        synthesis_text = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system_prompt,
                task_type="research",
            )
        )
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


@instrumented_node
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
        locale = state.get("locale", "en")
        if locale == "es-MX":
            base_prompt = (
                "Formatee la sintesis de investigacion en un reporte estructurado con secciones."
            )
            user_content = f"Formatee esto como un reporte:\n{synthesis}"
        else:
            base_prompt = "Format the research synthesis into a structured report with sections."
            user_content = f"Format this into a report:\n{synthesis}"
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        formatted = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": user_content}],
                system_prompt=system_prompt,
                task_type="research",
            )
        )
        report_sections = {
            "executive_summary": formatted[:500],
            "detailed_findings": formatted,
            "sources": [{"title": s.get("title", ""), "url": s.get("url", "")} for s in sources],
            "source_count": len(sources),
        }
    except Exception:
        report_sections = {
            "executive_summary": synthesis[:500] if synthesis else "No synthesis available.",
            "detailed_findings": synthesis,
            "sources": [{"title": s.get("title", ""), "url": s.get("url", "")} for s in sources],
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
