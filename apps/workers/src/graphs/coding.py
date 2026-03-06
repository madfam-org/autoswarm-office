"""Coding workflow graph -- plan, implement, test, review, push."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .base import BaseGraphState

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class CodingState(BaseGraphState, TypedDict, total=False):
    """Extended state for the coding workflow."""

    code_changes: list[dict[str, Any]]
    test_results: dict[str, Any] | None
    branch_name: str | None
    iteration: int


# -- Node functions -----------------------------------------------------------


def plan(state: CodingState) -> CodingState:
    """Generate an implementation plan from the task description.

    Analyses the messages and payload to produce a structured list of
    file changes that need to be made.
    """
    messages = state.get("messages", [])
    task_description = ""
    for msg in messages:
        if hasattr(msg, "content"):
            task_description += msg.content + "\n"

    plan_output = {
        "description": task_description.strip(),
        "steps": [
            "Analyze requirements from task description",
            "Identify files to create or modify",
            "Implement changes in isolated worktree",
            "Write or update tests",
            "Run test suite and validate",
        ],
    }

    plan_message = AIMessage(
        content=f"Implementation plan generated with {len(plan_output['steps'])} steps.",
        additional_kwargs={"plan": plan_output, "action_category": "file_read"},
    )

    return {
        **state,
        "messages": [*messages, plan_message],
        "status": "planning",
        "code_changes": [],
        "iteration": state.get("iteration", 0),
    }


def implement(state: CodingState) -> CodingState:
    """Write code changes based on the implementation plan.

    In production this node invokes the inference engine to generate code
    and applies changes via the file system tools.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0) + 1

    change_record: dict[str, Any] = {
        "iteration": iteration,
        "files_modified": [],
        "summary": f"Implementation iteration {iteration}",
    }

    impl_message = AIMessage(
        content=f"Code changes applied (iteration {iteration}).",
        additional_kwargs={"action_category": "file_write"},
    )

    existing_changes = state.get("code_changes", [])

    return {
        **state,
        "messages": [*messages, impl_message],
        "status": "implementing",
        "code_changes": [*existing_changes, change_record],
        "iteration": iteration,
    }


def test(state: CodingState) -> CodingState:
    """Run the test suite against the current code changes.

    Returns test results that drive the conditional edge: pass goes to
    review, fail loops back to implement.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)

    # Simulated test execution.  Real implementation uses BashTool to
    # run ``pytest`` or the project-specific test command.
    passed = iteration >= 1  # first attempt passes for deterministic behavior
    test_results: dict[str, Any] = {
        "passed": passed,
        "total": 10,
        "failures": 0 if passed else 2,
        "iteration": iteration,
    }

    test_message = AIMessage(
        content=f"Tests {'passed' if passed else 'failed'} ({test_results['failures']} failures).",
        additional_kwargs={"action_category": "bash_execute", "test_results": test_results},
    )

    return {
        **state,
        "messages": [*messages, test_message],
        "test_results": test_results,
        "status": "testing",
    }


def review(state: CodingState) -> CodingState:
    """Self-review the accumulated code changes.

    Performs a lightweight quality check before the push gate.
    """
    messages = state.get("messages", [])
    code_changes = state.get("code_changes", [])

    review_summary = {
        "changes_reviewed": len(code_changes),
        "issues_found": 0,
        "recommendation": "approve",
    }

    review_message = AIMessage(
        content=f"Code review complete: {review_summary['changes_reviewed']} change sets reviewed, "
        f"{review_summary['issues_found']} issues found.",
        additional_kwargs={"action_category": "file_read", "review": review_summary},
    )

    return {
        **state,
        "messages": [*messages, review_message],
        "status": "reviewed",
    }


def push_gate(state: CodingState) -> CodingState:
    """Interrupt execution before git push to require human approval.

    Uses LangGraph's ``interrupt()`` to pause the graph.  The Tactician
    must walk to the agent's Review Station and press 'A' to approve.
    """
    branch = state.get("branch_name", "feature/auto-changes")
    code_changes = state.get("code_changes", [])

    approval_context = {
        "action": "git_push",
        "branch": branch,
        "change_count": len(code_changes),
        "test_results": state.get("test_results"),
    }

    # This call pauses graph execution and emits an interrupt event.
    decision = interrupt(approval_context)

    # Execution resumes here after the human responds.
    if decision.get("approved", False):
        push_message = AIMessage(
            content=f"Push approved. Pushing to branch '{branch}'.",
            additional_kwargs={"action_category": "git_push"},
        )
        return {
            **state,
            "messages": [*state.get("messages", []), push_message],
            "status": "pushed",
        }

    # Denied -- record feedback and stop.
    feedback = decision.get("feedback", "No feedback provided")
    deny_message = AIMessage(
        content=f"Push denied. Feedback: {feedback}",
        additional_kwargs={"action_category": "git_push"},
    )
    return {
        **state,
        "messages": [*state.get("messages", []), deny_message],
        "status": "denied",
    }


# -- Conditional edge routing -------------------------------------------------


def _route_after_test(state: CodingState) -> str:
    """Decide whether to proceed to review or loop back to implement."""
    test_results = state.get("test_results")
    if test_results and test_results.get("passed"):
        return "review"

    # Guard against infinite loops.
    if state.get("iteration", 0) >= 3:
        logger.warning("Max implementation iterations reached; proceeding to review anyway.")
        return "review"

    return "implement"


# -- Graph construction -------------------------------------------------------


def build_coding_graph() -> StateGraph:
    """Construct and compile the coding workflow state graph.

    Flow::

        plan -> implement -> test -> (pass?) -> review -> push_gate -> END
                   ^                   |
                   +--- (fail) --------+
    """
    graph = StateGraph(CodingState)

    graph.add_node("plan", plan)
    graph.add_node("implement", implement)
    graph.add_node("test", test)
    graph.add_node("review", review)
    graph.add_node("push_gate", push_gate)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "implement")
    graph.add_edge("implement", "test")
    graph.add_conditional_edges("test", _route_after_test, {"review": "review", "implement": "implement"})
    graph.add_edge("review", "push_gate")
    graph.add_edge("push_gate", END)

    return graph
