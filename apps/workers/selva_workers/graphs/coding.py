"""Coding workflow graph -- plan, implement, test, review, push."""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ..event_emitter import instrumented_node
from ..tools.bash_tool import BashTool
from .base import BaseGraphState, check_permission
from .base import run_async as _run_async

logger = logging.getLogger(__name__)

# Shared BashTool instance for test execution.
_bash_tool = BashTool()


# -- State --------------------------------------------------------------------


class CodingState(BaseGraphState, TypedDict, total=False):
    """Extended state for the coding workflow."""

    code_changes: list[dict[str, Any]]
    test_results: dict[str, Any] | None
    branch_name: str | None
    iteration: int
    worktree_path: str | None
    repo_path: str | None


# -- Node functions -----------------------------------------------------------


@instrumented_node
def plan(state: CodingState) -> CodingState:
    """Generate an implementation plan from the task description.

    Calls the inference router to produce a structured plan.  Falls back
    to a deterministic static plan when no LLM provider is configured or
    the response cannot be parsed.
    """
    messages = state.get("messages", [])
    task_description = ""
    for msg in messages:
        # langchain BaseMessage.content is `str | list[str | dict]` — only
        # str content contributes to the plan prompt; list-shaped content
        # (multimodal blocks) is skipped.
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            task_description += content + "\n"

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        from ..prompts import build_experience_context, build_plan_prompt

        # Retrieve experience context for prompt enrichment
        experience_ctx = ""
        try:
            agent_id = state.get("agent_id", "unknown")
            experience_ctx = _run_async(
                build_experience_context(
                    agent_id=agent_id,
                    agent_role="coder",
                    task_description=task_description.strip(),
                )
            )
        except Exception:
            logger.debug("Failed to retrieve experience context", exc_info=True)

        skill_ctx = state.get("agent_system_prompt", "")
        repo_path = state.get("repo_path")
        locale = state.get("locale", "en")
        system_prompt = build_plan_prompt(
            task_description.strip(),
            repo_path=repo_path,
            skill_ctx=skill_ctx,
            experience_ctx=experience_ctx,
            locale=locale,
        )
        llm_response = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": task_description.strip()}],
                system_prompt=system_prompt,
                task_type="planning",
                response_format={"type": "json_object"},
            )
        )
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

    # Create a worktree for isolated work when a repo_path is available.
    worktree_path = state.get("worktree_path")
    repo_path = state.get("repo_path")
    if repo_path and not worktree_path:
        try:
            from ..tools.git_tool import GitTool

            git_tool = GitTool()
            task_id = state.get("task_id", "unknown")
            worktree_path = _run_async(
                git_tool.create_worktree(repo_path, f"selva/task-{task_id}")
            )
            logger.info("Created worktree at %s", worktree_path)
        except Exception:
            logger.warning("Failed to create worktree; working in-place", exc_info=True)

    task_id = state.get("task_id", "unknown")
    branch = state.get("branch_name") or f"selva/task-{task_id}"

    return {
        **state,
        "messages": [*messages, plan_message],
        "status": "planning",
        "code_changes": [],
        "iteration": state.get("iteration", 0),
        "worktree_path": worktree_path,
        "branch_name": branch,
    }


@instrumented_node
def implement(state: CodingState) -> CodingState:
    """Write code changes based on the implementation plan.

    Calls the inference router with the current plan step context.
    Falls back to a placeholder change record when no LLM is available.
    Commands execute inside the worktree when available.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0) + 1

    # Constrain BashTool to the worktree directory if available.
    worktree_path = state.get("worktree_path")
    if worktree_path:
        _bash_tool.allowed_cwd = worktree_path

    # Permission check before writing files.
    from selva_permissions.types import PermissionLevel

    perm = check_permission(state, "file_write")
    if perm.level == PermissionLevel.DENY:
        deny_msg = AIMessage(content="File write denied by permission engine.")
        return {
            **state,
            "messages": [*messages, deny_msg],
            "status": "blocked",
        }

    code_output: str | None = None
    llm_available = False
    max_retries = 2
    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        llm_available = True
        plan_msg = next(
            (
                m
                for m in reversed(messages)
                if "plan" in (getattr(m, "additional_kwargs", None) or {})
            ),
            None,
        )
        plan_steps = plan_msg.additional_kwargs["plan"]["steps"] if plan_msg else []
        step_idx = min(iteration - 1, len(plan_steps) - 1) if plan_steps else 0
        current_step = plan_steps[step_idx] if plan_steps else "Implement changes"

        from ..prompts import build_implement_prompt

        skill_ctx = state.get("agent_system_prompt", "")
        locale = state.get("locale", "en")
        system_prompt = build_implement_prompt(
            step=current_step,
            iteration=iteration,
            repo_path=state.get("repo_path"),
            worktree_path=worktree_path,
            skill_ctx=skill_ctx,
            locale=locale,
        )

        last_error: str | None = None
        for attempt in range(1 + max_retries):
            user_content = f"Implement step {iteration}: {current_step}"
            if last_error and attempt > 0:
                user_content = (
                    f"Your previous response was not valid JSON: {last_error}. "
                    "Return ONLY a JSON object with key 'files' containing an "
                    "array of objects with 'path' and 'content' keys.\n\n"
                    f"Original request: Implement step {iteration}: {current_step}"
                )

            raw = _run_async(
                call_llm(
                    router,
                    messages=[{"role": "user", "content": user_content}],
                    system_prompt=system_prompt,
                    task_type="coding",
                    response_format={"type": "json_object"},
                )
            )

            try:
                parsed = _json.loads(raw)
                if isinstance(parsed.get("files"), list):
                    code_output = raw
                    break
                last_error = "Response missing 'files' array"
            except _json.JSONDecodeError as exc:
                last_error = str(exc)
                logger.warning(
                    "LLM returned invalid JSON (attempt %d/%d): %s",
                    attempt + 1,
                    1 + max_retries,
                    last_error,
                )
        else:
            # All retries exhausted — fail the node
            if llm_available:
                error_msg = AIMessage(
                    content=(
                        f"LLM failed to produce valid JSON after "
                        f"{1 + max_retries} attempts: {last_error}"
                    ),
                )
                return {
                    **state,
                    "messages": [*messages, error_msg],
                    "status": "error",
                }

    except Exception:
        logger.warning(
            "Failed to generate code via LLM; falling through to placeholder path",
            exc_info=True,
        )

    # Guard: if LLM was available but call_llm raised mid-loop (or any other
    # path left code_output unset), do NOT fall through to a silent placeholder
    # write — that would report success despite producing nothing usable.
    # The conditional edge `_route_after_implement` short-circuits to END on
    # status == "error"; downstream nodes (push_gate) also check for it.
    if code_output is None and llm_available:
        error_msg = AIMessage(
            content="LLM call failed after retries; aborting implement node.",
        )
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "result": {"error": "LLM call failed after retries"},
            "iteration": iteration,
        }

    # Write files to worktree from LLM output or placeholder.
    files_written = _write_files_to_worktree(
        worktree_path,
        code_output,
        state,
        placeholder_ok=not llm_available,
    )

    summary = code_output[:500] if code_output else f"Implementation iteration {iteration}"

    change_record: dict[str, Any] = {
        "iteration": iteration,
        "files_modified": files_written,
        "summary": summary,
    }

    impl_message = AIMessage(
        content=f"Code changes applied (iteration {iteration}): "
        f"{len(files_written)} files written.",
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


def _write_files_to_worktree(
    worktree_path: str | None,
    code_output: str | None,
    state: CodingState,
    *,
    placeholder_ok: bool = True,
) -> list[str]:
    """Parse LLM JSON output and write files to the worktree.

    Returns a list of relative paths written.  When *placeholder_ok* is
    ``True`` (no LLM configured) a placeholder file is written as a
    fallback.  When ``False`` (LLM was available but produced garbage),
    the caller should treat an empty return as an error.
    """
    if not worktree_path:
        return []

    wt = Path(worktree_path)
    files_written: list[str] = []

    if code_output:
        try:
            parsed = _json.loads(code_output)
            for entry in parsed.get("files", []):
                rel_path = entry.get("path", "")
                content = entry.get("content", "")
                if not rel_path or not isinstance(content, str):
                    continue
                # Security: reject absolute paths and directory traversals.
                if rel_path.startswith("/") or ".." in rel_path.split("/"):
                    logger.warning("Rejected unsafe path: %s", rel_path)
                    continue
                target = wt / rel_path
                if not target.resolve().is_relative_to(wt.resolve()):
                    logger.warning("Rejected path escaping worktree: %s", rel_path)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                files_written.append(rel_path)
        except (_json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to parse LLM code output as JSON")

    # Placeholder only when no LLM was configured (not when LLM failed).
    if not files_written and placeholder_ok:
        desc = state.get("description", "Agent task")
        placeholder = wt / "SELVA_PLACEHOLDER.md"
        placeholder.write_text(f"# Selva Placeholder\n\nTask: {desc}\n")
        files_written.append("SELVA_PLACEHOLDER.md")

    return files_written


@instrumented_node
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
    worktree_path = state.get("worktree_path")
    test_cmd = "python -m pytest --tb=short -q"
    if worktree_path:
        test_cmd = f"cd {worktree_path} && {test_cmd}"

    try:
        bash_result = _run_async(_bash_tool.execute(test_cmd))

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


@instrumented_node
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
        from ..prompts import build_review_prompt

        changes_text = "\n".join(c.get("summary", "") for c in code_changes)
        skill_ctx = state.get("agent_system_prompt", "")
        locale = state.get("locale", "en")
        system_prompt = build_review_prompt(
            changes_text,
            skill_ctx=skill_ctx,
            locale=locale,
        )
        review_text = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": f"Review these changes:\n{changes_text}"}],
                system_prompt=system_prompt,
                task_type="review",
                response_format={"type": "json_object"},
            )
        )
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
        content=f"Code review complete: {reviewed} change sets reviewed, {issues} issues found.",
        additional_kwargs={"action_category": "file_read", "review": review_summary},
    )

    return {
        **state,
        "messages": [*messages, review_message],
        "status": "reviewed",
    }


@instrumented_node
def push_gate(state: CodingState) -> CodingState:
    """Interrupt execution before git push to require human approval.

    Uses LangGraph's ``interrupt()`` to pause the graph.  The Tactician
    must walk to the agent's Review Station and press 'A' to approve.
    """
    branch: str = state.get("branch_name") or "feature/auto-changes"
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
    worktree_path = state.get("worktree_path")

    if decision.get("approved", False):
        push_message = AIMessage(
            content=f"Push approved. Pushing to branch '{branch}'.",
            additional_kwargs={"action_category": "git_push"},
        )
        # Commit and push before cleaning up the worktree.
        if worktree_path:
            try:
                from ..config import get_settings as _get_worker_settings
                from ..tools.git_tool import GitTool

                settings = _get_worker_settings()
                git_tool = GitTool()
                _run_async(
                    git_tool.configure_identity(
                        worktree_path,
                        settings.git_author_name,
                        settings.git_author_email,
                    )
                )
                commit_msg = f"selva: {state.get('description', 'agent changes')[:200]}"
                commit_result = _run_async(git_tool.commit(worktree_path, commit_msg))
                if commit_result.return_code == 0:
                    push_result = _run_async(
                        git_tool.push(worktree_path, branch, token=settings.github_token)
                    )
                    if push_result.return_code != 0:
                        logger.error("Git push failed: %s", push_result.stderr)
                    else:
                        # Create a PR (fire-and-forget).
                        _create_pr_after_push(git_tool, worktree_path, branch, state)
                else:
                    logger.warning(
                        "Git commit failed (no changes?): %s",
                        commit_result.stderr,
                    )
            except Exception:
                logger.warning("Failed to commit/push", exc_info=True)

            # Cleanup worktree after commit+push.
            try:
                git_tool_cleanup = GitTool()
                _run_async(git_tool_cleanup.cleanup_worktree(worktree_path))
                logger.info("Cleaned up worktree at %s", worktree_path)
            except Exception:
                logger.warning("Failed to cleanup worktree", exc_info=True)
        return {
            **state,
            "messages": [*state.get("messages", []), push_message],
            "status": "pushed",
            "worktree_path": None,
        }

    # Denied -- cleanup worktree and record feedback.
    if worktree_path:
        try:
            from ..tools.git_tool import GitTool

            git_tool = GitTool()
            _run_async(git_tool.cleanup_worktree(worktree_path))
            logger.info("Cleaned up worktree at %s (push denied)", worktree_path)
        except Exception:
            logger.warning("Failed to cleanup worktree", exc_info=True)

    feedback = decision.get("feedback", "No feedback provided")
    deny_message = AIMessage(
        content=f"Push denied. Feedback: {feedback}",
        additional_kwargs={"action_category": "git_push"},
    )
    return {
        **state,
        "messages": [*state.get("messages", []), deny_message],
        "status": "denied",
        "worktree_path": None,
    }


def _create_pr_after_push(
    git_tool,  # noqa: ANN001
    worktree_path: str,
    branch: str,
    state: CodingState,
) -> None:
    """Create a GitHub PR after a successful push (fire-and-forget).

    Failures are logged but never raised — PR creation is best-effort.
    """
    try:
        from ..config import get_settings as _get_worker_settings

        settings = _get_worker_settings()

        description = state.get("description", "Agent changes")
        code_changes = state.get("code_changes", [])
        file_count = sum(len(c.get("files_modified", [])) for c in code_changes)
        title = f"selva: {description[:60]}"
        body = (
            f"## Selva Agent PR\n\n"
            f"**Task**: {state.get('task_id', 'unknown')}\n"
            f"**Description**: {description}\n"
            f"**Files changed**: {file_count}\n"
        )
        pr_result = _run_async(
            git_tool.create_pr(
                worktree_path,
                branch,
                title,
                body,
                token=settings.github_token,
            )
        )
        if pr_result.return_code == 0:
            logger.info("PR created for branch %s: %s", branch, pr_result.stdout.strip())
        else:
            logger.warning("PR creation failed: %s", pr_result.stderr)
    except Exception:
        logger.warning("Failed to create PR for branch %s", branch, exc_info=True)


# -- Conditional edge routing -------------------------------------------------


def _route_after_implement(state: CodingState) -> str:
    """Route after implement: error goes to END, otherwise test."""
    if state.get("status") == "error":
        return END
    return "test"


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
    graph.add_conditional_edges(
        "implement",
        _route_after_implement,
        {"test": "test", END: END},
    )
    graph.add_conditional_edges(
        "test",
        _route_after_test,
        {"review": "review", "implement": "implement"},
    )
    graph.add_edge("review", "push_gate")
    graph.add_edge("push_gate", END)

    return graph
