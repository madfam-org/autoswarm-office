"""Tests for coding graph worktree isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage


class TestCodingWorktree:
    """Worktree lifecycle in the coding graph."""

    def test_plan_creates_worktree_when_repo_path_set(self) -> None:
        from autoswarm_workers.graphs.coding import plan

        mock_git = MagicMock()
        mock_git.create_worktree = AsyncMock(return_value="/tmp/worktrees/task-t1")

        with patch("autoswarm_workers.tools.git_tool.GitTool", return_value=mock_git):
            result = plan({
                "messages": [AIMessage(content="Build a feature")],
                "repo_path": "/repos/myapp",
                "task_id": "t1",
            })

        assert result["worktree_path"] == "/tmp/worktrees/task-t1"

    def test_plan_skips_worktree_when_no_repo_path(self) -> None:
        from autoswarm_workers.graphs.coding import plan

        result = plan({
            "messages": [AIMessage(content="Build a feature")],
            "task_id": "t1",
        })

        assert result.get("worktree_path") is None

    def test_plan_skips_worktree_when_already_set(self) -> None:
        from autoswarm_workers.graphs.coding import plan

        result = plan({
            "messages": [AIMessage(content="Build a feature")],
            "repo_path": "/repos/myapp",
            "worktree_path": "/existing/worktree",
            "task_id": "t1",
        })

        assert result["worktree_path"] == "/existing/worktree"

    def test_implement_sets_bash_cwd_to_worktree(self) -> None:
        from autoswarm_workers.graphs.coding import _bash_tool, implement

        original_cwd = getattr(_bash_tool, "allowed_cwd", None)
        try:
            implement({
                "messages": [AIMessage(
                    content="Plan ready",
                    additional_kwargs={"plan": {"steps": ["step1"]}}
                )],
                "worktree_path": "/tmp/worktrees/task-t1",
                "iteration": 0,
            })
            assert _bash_tool.allowed_cwd == "/tmp/worktrees/task-t1"
        finally:
            _bash_tool.allowed_cwd = original_cwd

    def test_push_gate_cleans_up_worktree_on_approve(self) -> None:
        from autoswarm_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.cleanup_worktree = AsyncMock()

        with (
            patch(
                "autoswarm_workers.graphs.coding.interrupt",
                return_value={"approved": True},
            ),
            patch("autoswarm_workers.tools.git_tool.GitTool", return_value=mock_git),
        ):
            result = push_gate({
                "messages": [],
                "code_changes": [{"iteration": 1}],
                "worktree_path": "/tmp/worktrees/task-t1",
            })

        assert result["status"] == "pushed"
        assert result["worktree_path"] is None
        mock_git.cleanup_worktree.assert_called_once_with("/tmp/worktrees/task-t1")

    def test_push_gate_cleans_up_worktree_on_deny(self) -> None:
        from autoswarm_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.cleanup_worktree = AsyncMock()

        with (
            patch(
                "autoswarm_workers.graphs.coding.interrupt",
                return_value={"approved": False, "feedback": "Needs work"},
            ),
            patch("autoswarm_workers.tools.git_tool.GitTool", return_value=mock_git),
        ):
            result = push_gate({
                "messages": [],
                "code_changes": [],
                "worktree_path": "/tmp/worktrees/task-t1",
            })

        assert result["status"] == "denied"
        assert result["worktree_path"] is None
        mock_git.cleanup_worktree.assert_called_once_with("/tmp/worktrees/task-t1")

    def test_worktree_path_stored_in_state(self) -> None:
        from autoswarm_workers.graphs.coding import CodingState

        # Verify the TypedDict has the field.
        annotations = CodingState.__annotations__
        assert "worktree_path" in annotations
        assert "repo_path" in annotations

    def test_test_node_uses_worktree_path(self) -> None:
        from autoswarm_workers.graphs.coding import test

        result = test({
            "messages": [],
            "iteration": 1,
            "worktree_path": "/tmp/worktrees/task-t1",
        })

        # Should complete without error (falls back to simulated results).
        assert result["status"] == "testing"
