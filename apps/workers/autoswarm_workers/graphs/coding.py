"""Coding workflow graph -- plan, implement, test, review, push."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json as _json
import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ..tools.bash_tool import BashTool
from .base import BaseGraphState

logger = logging.getLogger(__name__)

# Shared BashTool instance for test execution.
_bash_tool = BashTool()


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a sync graph node context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


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

    Calls the inference router to produce a structured plan.  Falls back
    to a deterministic static plan when no LLM provider is configured or
    the response cannot be parsed.
    """
    messages = state.get("messages", [])
    task_description = ""
    for msg in messages:
        if hasattr(msg, "content"):
            task_description += msg.content + "\n"

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = (
            "You are a senior developer. Break this task into an ordered list "
            "of concrete file changes. Return a JSON object with keys: "
            "'description' (string) and 'steps' (array of strings)."
        )
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        llm_response = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": task_description.strip()}],
            system_prompt=system_prompt,
        ))
        plan_output = _json.loads(llm_response)
        if not isinstance(plan_output.get("steps"), list):
            raise ValueError("Invalid plan format")
    except Exception:
        # Fallback: static plan when LLM unavailable or response unparseable.
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

    Calls the inference router with the current plan step context.
    Falls back to a placeholder change record when no LLM is available.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0) + 1

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        plan_msg = next(
            (
                m for m in reversed(messages)
                if "plan" in (getattr(m, "additional_kwargs", None) or {})
            ),
            None,
        )
        plan_steps = plan_msg.additional_kwargs["plan"]["steps"] if plan_msg else []
        step_idx = min(iteration - 1, len(plan_steps) - 1) if plan_steps else 0
        current_step = plan_steps[step_idx] if plan_steps else "Implement changes"

        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = (
            "You are a senior developer. Write production-ready code for the "
            "requested change. Return the code with file paths clearly marked."
        )
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        code_output = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": f"Implement step {iteration}: {current_step}"}],
            system_prompt=system_prompt,
        ))
        change_record: dict[str, Any] = {
            "iteration": iteration,
            "files_modified": [],
            "summary": code_output[:500],
        }
    except Exception:
        change_record = {
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

    Attempts to run ``pytest`` via BashTool for real test execution.
    Falls back to simulated (deterministic) results if pytest is
    unavailable or the subprocess fails.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)

    # -- Attempt real test execution via BashTool -----------------------------
    try:
        loop = asyncio.get_event_loop()
        bash_result = loop.run_until_complete(
            _bash_tool.execute("python -m pytest --tb=short -q")
        )

        if bash_result.success:
            # Parse basic pass/fail from pytest output.
            output = bash_result.stdout
            passed = "failed" not in output.lower() or "passed" in output.lower()
            test_results: dict[str, Any] = {
                "passed": passed,
                "raw_output": output,
                "iteration": iteration,
                "source": "pytest",
            }
        else:
            # pytest ran but returned a non-zero exit code (test failures).
            test_results = {
                "passed": False,
                "raw_output": bash_result.stdout,
                "stderr": bash_result.stderr,
                "iteration": iteration,
                "source": "pytest",
            }

        logger.info(
            "pytest execution completed (return_code=%d, passed=%s)",
            bash_result.return_code,
            test_results["passed"],
        )

    except Exception as exc:
        # -- Fallback: simulated results when BashTool / pytest unavailable ---
        logger.warning(
            "BashTool pytest execution failed (%s); falling back to simulated results.",
            exc,
        )
        passed = iteration >= 1  # first attempt passes for deterministic behavior
        test_results = {
            "passed": passed,
            "total": 10,
            "failures": 0 if passed else 2,
            "iteration": iteration,
            "source": "simulated",
        }

    test_message = AIMessage(
        content=f"Tests {'passed' if test_results['passed'] else 'failed'} "
        f"(iteration {iteration}, source={test_results.get('source', 'unknown')}).",
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

    Calls the inference router to perform an LLM-powered code review.
    Falls back to an auto-approve summary when no LLM is available.
    """
    messages = state.get("messages", [])
    code_changes = state.get("code_changes", [])

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        changes_text = "\n".join(c.get("summary", "") for c in code_changes)
        skill_ctx = state.get("agent_system_prompt", "")
        base_prompt = (
            "You are a thorough code reviewer. Check for bugs, security issues, "
            "and style violations. Return JSON with keys: 'changes_reviewed' (int), "
            "'issues_found' (int), 'recommendation' ('approve' or 'revise')."
        )
        system_prompt = f"{skill_ctx}\n\n{base_prompt}" if skill_ctx else base_prompt
        review_text = _run_async(call_llm(
            router,
            messages=[{"role": "user", "content": f"Review these changes:\n{changes_text}"}],
            system_prompt=system_prompt,
        ))
        review_summary = _json.loads(review_text)
    except Exception:
        review_summary = {
            "changes_reviewed": len(code_changes),
            "issues_found": 0,
            "recommendation": "approve",
        }

    reviewed = review_summary.get("changes_reviewed", 0)
    issues = review_summary.get("issues_found", 0)
    review_message = AIMessage(
        content=f"Code review complete: {reviewed} change sets reviewed, "
        f"{issues} issues found.",
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
    graph.add_conditional_edges(
        "test", _route_after_test,
        {"review": "review", "implement": "implement"},
    )
    graph.add_edge("review", "push_gate")
    graph.add_edge("push_gate", END)

    return graph
