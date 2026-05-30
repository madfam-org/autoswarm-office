"""Load-test calibration graph — no LLM, no external APIs, completes immediately."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..event_emitter import instrumented_node
from .base import BaseGraphState


class CalibrationState(BaseGraphState, TypedDict, total=False):
    """Minimal state for k6 concurrency calibration runs."""

    org_id: str
    result: dict[str, object]


@instrumented_node
def complete(state: CalibrationState) -> CalibrationState:
    """Mark task completed without side effects (Phase 0 load calibration)."""
    return {
        **state,
        "status": "completed",
        "result": {"calibration": True, "purpose": "load_test_noop"},
    }


def build_calibration_graph() -> StateGraph:
    """Single-node graph: complete → END (~sub-second, no I/O)."""
    graph = StateGraph(CalibrationState)
    graph.add_node("complete", complete)
    graph.set_entry_point("complete")
    graph.add_edge("complete", END)
    return graph
