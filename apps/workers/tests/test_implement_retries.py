"""Tests for LLM JSON retry logic in implement()."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from selva_workers.graphs.coding import _write_files_to_worktree, implement


def _make_state(worktree_path=None, iteration=0):
    """Build a minimal CodingState for testing."""
    from langchain_core.messages import AIMessage

    plan_msg = AIMessage(
        content="Plan generated.",
        additional_kwargs={
            "plan": {"steps": ["Step 1: implement feature"]},
            "action_category": "file_read",
        },
    )
    return {
        "messages": [plan_msg],
        "task_id": "test-task",
        "agent_id": "test-agent",
        "status": "planning",
        "code_changes": [],
        "iteration": iteration,
        "worktree_path": worktree_path,
        "repo_path": None,
        "agent_system_prompt": "",
        "agent_skill_ids": [],
        "description": "test task",
        "current_node_id": "",
        "result": None,
        "requires_approval": False,
        "approval_request_id": None,
        "workflow_variables": {},
        "branch_name": None,
        "test_results": None,
    }


def _perm_allow():
    from selva_permissions.types import PermissionLevel

    perm_result = MagicMock()
    perm_result.level = PermissionLevel.ALLOW
    return perm_result


def test_implement_retries_on_json_error(tmp_path):
    """LLM returns invalid JSON first, valid second -- success."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    state = _make_state(worktree_path=str(wt))

    valid_response = json.dumps({"files": [{"path": "src/main.py", "content": "print('hello')"}]})

    call_count = {"n": 0}

    async def mock_call_llm(router, messages, system_prompt="", task_type="coding", **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not valid json {{"
        return valid_response

    with (
        patch(
            "selva_workers.inference.get_model_router",
            return_value=MagicMock(),
        ),
        patch(
            "selva_workers.inference.call_llm",
            side_effect=mock_call_llm,
        ),
        patch(
            "selva_workers.graphs.coding.check_permission",
            return_value=_perm_allow(),
        ),
        patch("selva_workers.event_emitter.emit_event", new_callable=AsyncMock),
    ):
        result = implement(state)

    assert result["status"] == "implementing"
    assert call_count["n"] == 2
    assert (wt / "src" / "main.py").exists()


def test_implement_fails_after_max_retries(tmp_path):
    """LLM always returns invalid JSON -- status 'error'."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    state = _make_state(worktree_path=str(wt))

    async def mock_call_llm(router, messages, system_prompt="", task_type="coding", **kwargs):
        return "this is not json at all"

    with (
        patch(
            "selva_workers.inference.get_model_router",
            return_value=MagicMock(),
        ),
        patch(
            "selva_workers.inference.call_llm",
            side_effect=mock_call_llm,
        ),
        patch(
            "selva_workers.graphs.coding.check_permission",
            return_value=_perm_allow(),
        ),
        patch("selva_workers.event_emitter.emit_event", new_callable=AsyncMock),
    ):
        result = implement(state)

    assert result["status"] == "error"


def test_implement_placeholder_only_without_llm(tmp_path):
    """No LLM configured -- placeholder file (preserved behavior)."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    state = _make_state(worktree_path=str(wt))

    # Patch the inference module so the import inside implement() fails
    with (
        patch.dict(
            "sys.modules",
            {"selva_workers.inference": None},
        ),
        patch(
            "selva_workers.graphs.coding.check_permission",
            return_value=_perm_allow(),
        ),
    ):
        result = implement(state)

    assert result["status"] == "implementing"
    assert (wt / "SELVA_PLACEHOLDER.md").exists()


def test_write_files_no_placeholder_when_not_ok(tmp_path):
    """When placeholder_ok=False and no valid output, returns empty list."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    state = _make_state(worktree_path=str(wt))

    result = _write_files_to_worktree(str(wt), None, state, placeholder_ok=False)
    assert result == []
    assert not (wt / "SELVA_PLACEHOLDER.md").exists()


def test_write_files_placeholder_when_ok(tmp_path):
    """When placeholder_ok=True and no valid output, writes placeholder."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    state = _make_state(worktree_path=str(wt))

    result = _write_files_to_worktree(str(wt), None, state, placeholder_ok=True)
    assert "SELVA_PLACEHOLDER.md" in result
    assert (wt / "SELVA_PLACEHOLDER.md").exists()
