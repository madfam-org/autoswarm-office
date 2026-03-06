"""Common LangGraph state, nodes, and utilities shared across all workflow graphs."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


# -- Shared graph state -------------------------------------------------------


class BaseGraphState(TypedDict, total=False):
    """Base state carried through every LangGraph workflow.

    All workflow-specific graphs extend this with additional fields.
    ``total=False`` allows nodes to write only the keys they care about.
    """

    messages: list[BaseMessage]
    task_id: str
    agent_id: str
    status: str
    result: dict[str, Any] | None
    requires_approval: bool
    approval_request_id: str | None


# -- Permission matrix (mirrors the TypeScript ActionCategory) ----------------

_PERMISSION_MATRIX: dict[str, str] = {
    "file_read": "allow",
    "file_write": "ask",
    "bash_execute": "ask",
    "git_commit": "allow",
    "git_push": "ask",
    "email_send": "ask",
    "crm_update": "ask",
    "deploy": "ask",
    "api_call": "allow",
}


# -- Shared node functions ----------------------------------------------------


def permission_check(state: BaseGraphState) -> BaseGraphState:
    """Evaluate the pending action against the permission matrix.

    If the action category maps to ``"ask"`` the node sets
    ``requires_approval=True`` so downstream nodes (or the interrupt
    handler) can pause execution and request human approval.

    If the category maps to ``"deny"`` the status is set to ``"blocked"``.
    Otherwise (``"allow"``), execution continues unimpeded.
    """
    messages = state.get("messages", [])
    if not messages:
        return {**state, "requires_approval": False}

    # Extract the action category from the last message's metadata.
    last_message = messages[-1]
    action_category: str = getattr(last_message, "additional_kwargs", {}).get(
        "action_category", "api_call"
    )

    permission = _PERMISSION_MATRIX.get(action_category, "ask")

    if permission == "deny":
        logger.warning(
            "Action '%s' denied by permission matrix for agent %s",
            action_category,
            state.get("agent_id", "unknown"),
        )
        return {**state, "status": "blocked", "requires_approval": False}

    if permission == "ask":
        logger.info(
            "Action '%s' requires approval for agent %s",
            action_category,
            state.get("agent_id", "unknown"),
        )
        return {**state, "requires_approval": True}

    return {**state, "requires_approval": False}


def tool_executor(state: BaseGraphState) -> BaseGraphState:
    """Execute the tool call described in the most recent message.

    Before execution the node runs a permission check.  If approval is
    required and has not been granted, the node short-circuits and
    returns the state with ``status="waiting_approval"``.

    This is a lightweight reference implementation; production workers
    would delegate to the actual tool registry.
    """
    # Guard: if approval is still pending, do not execute.
    if state.get("requires_approval") and state.get("status") != "approved":
        logger.info("Tool execution paused pending approval for task %s", state.get("task_id"))
        return {**state, "status": "waiting_approval"}

    messages = state.get("messages", [])
    if not messages:
        return {**state, "status": "error", "result": {"error": "No messages in state"}}

    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if not tool_calls:
        return {**state, "status": "completed", "result": {"output": last_message.content}}

    # Execute each tool call sequentially.
    results: list[dict[str, Any]] = []
    for call in tool_calls:
        tool_name = call.get("name", "unknown")
        tool_args = call.get("args", {})
        logger.info("Executing tool '%s' with args %s", tool_name, tool_args)

        # Placeholder execution -- real implementation dispatches to
        # BashTool, GitTool, etc. based on tool_name.
        results.append(
            {
                "tool": tool_name,
                "args": tool_args,
                "output": f"[executed {tool_name}]",
            }
        )

    return {**state, "status": "completed", "result": {"tool_results": results}}
