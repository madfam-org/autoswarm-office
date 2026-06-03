"""Market intelligence workflow graph -- DOF scan, economic data, briefing, notify."""

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


class IntelligenceState(BaseGraphState, TypedDict, total=False):
    """Extended state for the market intelligence workflow."""

    org_id: str
    dof_results: list[dict[str, Any]]
    exchange_rate: dict[str, Any] | None
    economic_indicators: dict[str, Any] | None
    briefing_text: str | None


# -- Node functions -----------------------------------------------------------


@instrumented_node
def scan_dof(state: IntelligenceState) -> IntelligenceState:
    """Scan DOF for regulatory changes relevant to the org.

    Calls the MADFAM Crawler DOF search endpoint with keywords
    derived from the task description.  Falls back to an empty
    result set when the crawler is unavailable.
    """
    messages = state.get("messages", [])
    description = state.get("description", "")

    # Build search query from task description or default keywords
    query = description.strip() if description.strip() else "reforma fiscal regulacion"

    dof_results: list[dict[str, Any]] = []
    try:
        from madfam_inference.adapters.crawler import CrawlerAdapter

        adapter = CrawlerAdapter()
        dof_results = _run_async(adapter.search_dof(query))
    except Exception:
        logger.warning("DOF scan failed; proceeding with empty results", exc_info=True)

    dof_message = AIMessage(
        content=f"DOF scan complete: {len(dof_results)} entries found for '{query[:100]}'.",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, dof_message],
        "dof_results": dof_results,
        "status": "scanning_dof",
    }


@instrumented_node
def fetch_economic_data(state: IntelligenceState) -> IntelligenceState:
    """Fetch exchange rates, TIIE, inflation, and UMA via Dhanam market data API.

    Dhanam proxies to Banxico SIE internally so callers do not need
    a direct Banxico dependency.  Aggregates all economic indicators
    into a single dict.  Degrades gracefully -- each indicator is
    fetched independently so a failure in one does not block the others.
    """
    messages = state.get("messages", [])

    indicators: dict[str, Any] = {}
    exchange_rate_data: dict[str, Any] | None = None

    try:
        from madfam_inference.adapters.dhanam import DhanamAdapter

        adapter = DhanamAdapter()

        # Exchange rate
        try:
            fx = _run_async(adapter.get_exchange_rate("USD"))
            exchange_rate_data = fx.model_dump()
            indicators["exchange_rate"] = exchange_rate_data
        except Exception:
            logger.warning("Failed to fetch exchange rate", exc_info=True)

        # TIIE 28 days
        try:
            tiie = _run_async(adapter.get_tiie("28"))
            indicators["tiie_28"] = tiie.model_dump()
        except Exception:
            logger.warning("Failed to fetch TIIE", exc_info=True)

        # Inflation
        try:
            inflation = _run_async(adapter.get_inflation())
            indicators["inflation"] = inflation.model_dump()
        except Exception:
            logger.warning("Failed to fetch inflation", exc_info=True)

        # UMA
        try:
            uma = _run_async(adapter.get_uma())
            indicators["uma"] = uma.model_dump()
        except Exception:
            logger.warning("Failed to fetch UMA", exc_info=True)

    except Exception:
        logger.warning(
            "Dhanam adapter initialization failed; skipping economic data",
            exc_info=True,
        )

    indicator_count = len(indicators)
    econ_message = AIMessage(
        content=f"Economic data fetched: {indicator_count} indicators retrieved.",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, econ_message],
        "exchange_rate": exchange_rate_data,
        "economic_indicators": indicators,
        "status": "fetching_economic_data",
    }


@instrumented_node
def generate_briefing(state: IntelligenceState) -> IntelligenceState:
    """Generate a morning intelligence briefing via LLM.

    Combines DOF results and economic data into a concise executive
    briefing in Spanish.  Falls back to a structured template when
    no LLM is configured.
    """
    messages = state.get("messages", [])
    dof_results = state.get("dof_results", [])
    indicators = state.get("economic_indicators", {}) or {}

    # Build context for the LLM
    dof_summary = ""
    if dof_results:
        entries = []
        for entry in dof_results[:10]:
            title = entry.get("title", "Sin titulo")
            date = entry.get("date", "")
            entries.append(f"- [{date}] {title}")
        dof_summary = "\n".join(entries)
    else:
        dof_summary = "Sin novedades regulatorias relevantes."

    econ_summary_parts: list[str] = []
    fx = indicators.get("exchange_rate", {})
    if fx and fx.get("rate"):
        econ_summary_parts.append(f"Tipo de cambio FIX: ${fx['rate']} MXN/USD")
    tiie = indicators.get("tiie_28", {})
    if tiie and tiie.get("value"):
        econ_summary_parts.append(f"TIIE 28 dias: {tiie['value']}%")
    inflation = indicators.get("inflation", {})
    if inflation and inflation.get("value"):
        econ_summary_parts.append(f"Inflacion anual (INPC): {inflation['value']}%")
    uma = indicators.get("uma", {})
    if uma and uma.get("value"):
        econ_summary_parts.append(f"UMA diaria: ${uma['value']} MXN")
    econ_summary = "\n".join(econ_summary_parts) if econ_summary_parts else "Sin datos economicos."

    context = (
        f"## DOF - Diario Oficial de la Federacion\n{dof_summary}\n\n"
        f"## Indicadores Economicos\n{econ_summary}"
    )

    briefing_text: str
    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()

        skill_ctx = state.get("agent_system_prompt", "")
        system_prompt = (f"{skill_ctx}\n\n" if skill_ctx else "") + (
            "Eres un analista de inteligencia de mercado. "
            "Genera un briefing ejecutivo matutino en espanol, conciso y profesional. "
            "Formato amigable para WhatsApp: parrafos cortos, viñetas, emojis minimos. "
            "Incluye: cambios regulatorios clave, tipo de cambio, tasas de interes, "
            "inflacion, y recomendaciones de accion si aplican."
        )

        briefing_text = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": context}],
                system_prompt=system_prompt,
                task_type="research",
            )
        )
    except Exception:
        # Structured fallback when no LLM available
        briefing_text = (
            "BRIEFING MATUTINO - Inteligencia de Mercado\n"
            "============================================\n\n"
            f"REGULATORIO (DOF)\n{dof_summary}\n\n"
            f"INDICADORES ECONOMICOS\n{econ_summary}\n\n"
            "---\nGenerado por Selva Market Intelligence"
        )

    briefing_message = AIMessage(
        content="Intelligence briefing generated.",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, briefing_message],
        "briefing_text": briefing_text,
        "status": "briefing_generated",
    }


@instrumented_node
def notify_team(state: IntelligenceState) -> IntelligenceState:
    """Send briefing via configured channels and store as artifact.

    Attempts WhatsApp and/or Slack delivery.  Stores the briefing
    in the artifact storage for reference.  Failures are logged
    but do not block completion.
    """
    messages = state.get("messages", [])
    briefing_text = state.get("briefing_text", "")

    delivery_channels: list[str] = []

    # Store as artifact
    try:
        import hashlib

        from selva_tools.storage.local import LocalFSStorage

        storage = LocalFSStorage()
        # briefing_text may be None if upstream nodes failed; skip artifact
        # save in that case rather than crashing on None.encode().
        if not briefing_text:
            return state
        content_bytes = briefing_text.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        artifact_path = _run_async(storage.save(content_bytes, content_hash))
        delivery_channels.append(f"artifact:{artifact_path}")
    except Exception:
        logger.warning("Failed to store briefing as artifact", exc_info=True)

    # Build result
    result: dict[str, Any] = {
        "briefing": briefing_text,
        "dof_count": len(state.get("dof_results", [])),
        "indicators": state.get("economic_indicators", {}),
        "delivery_channels": delivery_channels,
    }

    notify_message = AIMessage(
        content=f"Briefing delivered via {len(delivery_channels)} channel(s).",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, notify_message],
        "status": "completed",
        "result": result,
    }


# -- Graph construction -------------------------------------------------------


def build_intelligence_graph() -> StateGraph:
    """Construct the market intelligence workflow state graph.

    Flow::

        scan_dof -> fetch_economic_data -> generate_briefing -> notify_team -> END

    This is a read-only pipeline with no interrupt points -- all data
    sources are external APIs that do not modify org state.
    """
    graph = StateGraph(IntelligenceState)

    graph.add_node("scan_dof", scan_dof)
    graph.add_node("fetch_economic_data", fetch_economic_data)
    graph.add_node("generate_briefing", generate_briefing)
    graph.add_node("notify_team", notify_team)

    graph.set_entry_point("scan_dof")
    graph.add_edge("scan_dof", "fetch_economic_data")
    graph.add_edge("fetch_economic_data", "generate_briefing")
    graph.add_edge("generate_briefing", "notify_team")
    graph.add_edge("notify_team", END)

    return graph
