"""Conditional edge evaluation for workflow routing."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from .safe_eval import UnsafeExpressionError, safe_eval_bool_expression
from .schema import EdgeDefinition, TriggerCondition

logger = logging.getLogger(__name__)

# Sentinel for "no match" — the default/fallback edge target
END_SENTINEL = "__end__"


def evaluate_condition(condition: TriggerCondition, state: dict) -> bool:
    """Evaluate a single trigger condition against the current graph state.

    Returns True if the condition matches.
    """
    # Get the last message content or result for matching
    output = _extract_output(state)

    if condition.regex is not None:
        try:
            return bool(re.search(condition.regex, output))
        except re.error:
            logger.warning("Invalid regex in edge condition: %s", condition.regex)
            return False

    if condition.keyword is not None:
        return condition.keyword.lower() in output.lower()

    if condition.expression is not None:
        return _eval_expression(condition.expression, state)

    return True


def build_conditional_router(
    source_id: str,
    edges: list[EdgeDefinition],
) -> Any:
    """Build a conditional routing function for add_conditional_edges().

    Returns a function that takes state and returns the target node ID.
    The function evaluates conditions in order; the first match wins.
    If no conditional edge matches, the unconditional (default) edge is used.
    If no default exists, returns END_SENTINEL.
    """
    conditional = [(e.target, e.condition) for e in edges if e.condition is not None]
    defaults = [e.target for e in edges if e.condition is None]
    default_target = defaults[0] if defaults else END_SENTINEL

    def route(state: dict) -> str:
        for target, condition in conditional:
            if condition and evaluate_condition(condition, state):
                logger.debug("Edge from '%s' matched condition → '%s'", source_id, target)
                return target
        return default_target

    route.__name__ = f"route_{source_id}"
    return route


def group_edges_by_source(edges: list[EdgeDefinition]) -> dict[str, list[EdgeDefinition]]:
    """Group edges by their source node ID."""
    groups: dict[str, list[EdgeDefinition]] = defaultdict(list)
    for edge in edges:
        groups[edge.source].append(edge)
    return dict(groups)


def _extract_output(state: dict) -> str:
    """Extract the textual output from the current state for condition matching."""
    # Check workflow variables for explicit output
    wf_vars = state.get("workflow_variables", {})
    current_node = state.get("current_node_id", "")
    node_result = wf_vars.get(f"{current_node}_result")
    if node_result is not None:
        return str(node_result)

    # Check last message content
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        content = getattr(last, "content", None) or ""
        return str(content)

    # Check result
    result = state.get("result")
    if result is not None:
        return str(result)

    return ""


def _eval_expression(expression: str, state: dict) -> bool:
    """Evaluate a restricted Python expression against workflow state."""
    try:
        context = {
            "state": state,
            "messages": state.get("messages", []),
            "variables": state.get("workflow_variables", {}),
            "result": state.get("result"),
            "status": state.get("status", ""),
            "len": len,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "sorted": sorted,
            "sum": sum,
            "min": min,
            "max": max,
        }
        return safe_eval_bool_expression(
            expression,
            context,
            allowed_call_targets={
                "len",
                "int",
                "float",
                "str",
                "bool",
                "sorted",
                "sum",
                "min",
                "max",
            },
            allowed_get_attrs_for={"state", "variables", "messages", "result", "status"},
        )
    except UnsafeExpressionError as exc:
        logger.warning("Failed to validate edge expression: %s", exc)
        return False
    except Exception:
        logger.warning("Failed to evaluate edge expression: %s", expression)
        return False
