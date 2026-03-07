"""Tests for LLM inference wiring in worker graph nodes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage


# ---------------------------------------------------------------------------
# Phase 1A: build_model_router / get_model_router
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Create a Settings instance without reading the .env file."""
    from autoswarm_workers.config import Settings

    return Settings(_env_file=None, **overrides)


def test_build_model_router_creates_providers():
    """build_model_router creates real provider instances when API keys are set."""
    from autoswarm_workers.inference import build_model_router

    mock_settings = _make_settings(
        anthropic_api_key="sk-test-ant",
        openai_api_key="sk-test-oai",
        openrouter_api_key="sk-test-or",
    )
    with patch("autoswarm_workers.inference.get_settings", return_value=mock_settings):
        router = build_model_router()

    names = router.available_providers
    assert "anthropic" in names
    assert "openai" in names
    assert "openrouter" in names
    assert "ollama" in names  # always present


def test_build_model_router_always_includes_ollama():
    """build_model_router includes Ollama even when no cloud API keys are set."""
    from autoswarm_workers.inference import build_model_router

    mock_settings = _make_settings()
    with patch("autoswarm_workers.inference.get_settings", return_value=mock_settings):
        router = build_model_router()

    names = router.available_providers
    assert "ollama" in names
    # Cloud providers should not be present without keys.
    assert "anthropic" not in names


def test_get_model_router_returns_singleton():
    """get_model_router caches and returns the same instance."""
    import autoswarm_workers.inference as inf

    # Reset singleton state.
    inf._router = None

    with patch.object(inf, "build_model_router") as mock_build:
        mock_router = MagicMock()
        mock_build.return_value = mock_router

        r1 = inf.get_model_router()
        r2 = inf.get_model_router()

        assert r1 is r2
        mock_build.assert_called_once()

    # Clean up singleton for other tests.
    inf._router = None


# ---------------------------------------------------------------------------
# Phase 1C-E: Graph node wiring with mocked LLM
# ---------------------------------------------------------------------------


def _make_coding_state(task_text: str = "Fix the login bug") -> dict:
    return {
        "messages": [HumanMessage(content=task_text)],
        "task_id": "task-1",
        "agent_id": "agent-1",
        "status": "running",
        "result": None,
        "requires_approval": False,
        "approval_request_id": None,
        "code_changes": [],
        "iteration": 0,
    }


@patch("autoswarm_workers.inference.get_model_router")
@patch("autoswarm_workers.inference.call_llm", new_callable=AsyncMock)
def test_plan_node_with_mocked_llm(mock_call_llm, mock_get_router):
    """plan() calls LLM and produces structured plan output."""
    import json

    mock_call_llm.return_value = json.dumps(
        {"description": "Fix login", "steps": ["Read auth.py", "Fix the bug", "Add test"]}
    )
    mock_get_router.return_value = MagicMock()

    from autoswarm_workers.graphs.coding import plan

    state = plan(_make_coding_state())

    assert state["status"] == "planning"
    plan_data = state["messages"][-1].additional_kwargs.get("plan")
    assert plan_data is not None
    assert len(plan_data["steps"]) == 3
    assert "Read auth.py" in plan_data["steps"]


def test_plan_node_fallback_without_llm():
    """plan() falls back to static steps when LLM is unavailable."""
    from autoswarm_workers.graphs.coding import plan

    # No LLM configured — should use fallback.
    with patch("autoswarm_workers.inference.get_model_router", side_effect=RuntimeError("no providers")):
        state = plan(_make_coding_state())

    assert state["status"] == "planning"
    plan_data = state["messages"][-1].additional_kwargs["plan"]
    assert len(plan_data["steps"]) == 5
    assert "Analyze requirements" in plan_data["steps"][0]


@patch("autoswarm_workers.inference.get_model_router")
@patch("autoswarm_workers.inference.call_llm", new_callable=AsyncMock)
def test_implement_node_with_mocked_llm(mock_call_llm, mock_get_router):
    """implement() calls LLM and records a change with summary."""
    mock_call_llm.return_value = "def fix_login():\n    pass"
    mock_get_router.return_value = MagicMock()

    from autoswarm_workers.graphs.coding import plan, implement

    # First produce a plan so implement can reference plan steps.
    import json

    mock_call_llm.return_value = json.dumps(
        {"description": "Fix login", "steps": ["Fix auth"]}
    )
    state = plan(_make_coding_state())

    mock_call_llm.return_value = "def fix_login():\n    pass"
    state = implement(state)

    assert state["status"] == "implementing"
    assert state["iteration"] == 1
    assert len(state["code_changes"]) == 1
    assert "fix_login" in state["code_changes"][0]["summary"]


@patch("autoswarm_workers.inference.get_model_router")
@patch("autoswarm_workers.inference.call_llm", new_callable=AsyncMock)
def test_review_node_with_mocked_llm(mock_call_llm, mock_get_router):
    """review() calls LLM and returns parsed review summary."""
    import json

    mock_call_llm.return_value = json.dumps(
        {"changes_reviewed": 2, "issues_found": 1, "recommendation": "revise"}
    )
    mock_get_router.return_value = MagicMock()

    from autoswarm_workers.graphs.coding import review

    state = _make_coding_state()
    state["code_changes"] = [
        {"iteration": 1, "summary": "change 1"},
        {"iteration": 2, "summary": "change 2"},
    ]

    state = review(state)

    assert state["status"] == "reviewed"
    review_data = state["messages"][-1].additional_kwargs.get("review")
    assert review_data["issues_found"] == 1
    assert review_data["recommendation"] == "revise"


# ---------------------------------------------------------------------------
# Phase 2: tool_executor – unknown tools
# ---------------------------------------------------------------------------


def _make_tool_call_message(tool_name: str, tool_args: dict | None = None):
    """Create an AIMessage with a single tool_calls entry."""
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": tool_args or {}, "id": "call-1"}],
    )


def test_tool_executor_unknown_tool_returns_failure():
    """tool_executor marks unrecognised tools as failed, not successful."""
    from autoswarm_workers.graphs.base import tool_executor

    state = {
        "messages": [_make_tool_call_message("unknown_tool", {"foo": "bar"})],
        "task_id": "task-1",
        "agent_id": "agent-1",
        "status": "running",
        "result": None,
        "requires_approval": False,
        "approval_request_id": None,
    }

    result_state = tool_executor(state)

    assert result_state["status"] == "completed"
    tool_results = result_state["result"]["tool_results"]
    assert len(tool_results) == 1
    assert tool_results[0]["success"] is False
    assert "No handler registered" in tool_results[0]["error"]
    assert tool_results[0]["tool"] == "unknown_tool"
