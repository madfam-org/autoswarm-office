"""Tests for coding graph worktree isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage


class TestCodingWorktree:
    """Worktree lifecycle in the coding graph."""

    def test_plan_creates_worktree_when_repo_path_set(self) -> None:
        from selva_workers.graphs.coding import plan

        mock_git = MagicMock()
        mock_git.create_worktree = AsyncMock(return_value="/tmp/worktrees/task-t1")

        with patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git):
            result = plan(
                {
                    "messages": [AIMessage(content="Build a feature")],
                    "repo_path": "/repos/myapp",
                    "task_id": "t1",
                }
            )

        assert result["worktree_path"] == "/tmp/worktrees/task-t1"

    def test_plan_skips_worktree_when_no_repo_path(self) -> None:
        from selva_workers.graphs.coding import plan

        result = plan(
            {
                "messages": [AIMessage(content="Build a feature")],
                "task_id": "t1",
            }
        )

        assert result.get("worktree_path") is None

    def test_plan_skips_worktree_when_already_set(self) -> None:
        from selva_workers.graphs.coding import plan

        result = plan(
            {
                "messages": [AIMessage(content="Build a feature")],
                "repo_path": "/repos/myapp",
                "worktree_path": "/existing/worktree",
                "task_id": "t1",
            }
        )

        assert result["worktree_path"] == "/existing/worktree"

    def test_implement_sets_bash_cwd_to_worktree(self, tmp_path) -> None:
        from selva_workers.graphs.coding import _bash_tool, implement

        worktree = str(tmp_path / "worktree")
        (tmp_path / "worktree").mkdir()

        original_cwd = getattr(_bash_tool, "allowed_cwd", None)
        try:
            implement(
                {
                    "messages": [
                        AIMessage(
                            content="Plan ready", additional_kwargs={"plan": {"steps": ["step1"]}}
                        )
                    ],
                    "worktree_path": worktree,
                    "iteration": 0,
                }
            )
            assert _bash_tool.allowed_cwd == worktree
        finally:
            _bash_tool.allowed_cwd = original_cwd

    def test_push_gate_cleans_up_worktree_on_approve(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.configure_identity = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.commit = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.push = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.create_pr = AsyncMock(
            return_value=MagicMock(return_code=0, stdout="", stderr=""),
        )
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = None
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch(
                "selva_workers.graphs.coding.interrupt",
                return_value={"approved": True},
            ),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch(
                "selva_workers.config.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [{"iteration": 1}],
                    "worktree_path": "/tmp/worktrees/task-t1",
                }
            )

        assert result["status"] == "pushed"
        assert result["worktree_path"] is None
        mock_git.cleanup_worktree.assert_called_once_with("/tmp/worktrees/task-t1")

    def test_push_gate_cleans_up_worktree_on_deny(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.cleanup_worktree = AsyncMock()

        with (
            patch(
                "selva_workers.graphs.coding.interrupt",
                return_value={"approved": False, "feedback": "Needs work"},
            ),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [],
                    "worktree_path": "/tmp/worktrees/task-t1",
                }
            )

        assert result["status"] == "denied"
        assert result["worktree_path"] is None
        mock_git.cleanup_worktree.assert_called_once_with("/tmp/worktrees/task-t1")

    def test_worktree_path_stored_in_state(self) -> None:
        from selva_workers.graphs.coding import CodingState

        # Verify the TypedDict has the field.
        annotations = CodingState.__annotations__
        assert "worktree_path" in annotations
        assert "repo_path" in annotations

    def test_test_node_uses_worktree_path(self) -> None:
        from selva_workers.graphs.coding import test

        result = test(
            {
                "messages": [],
                "iteration": 1,
                "worktree_path": "/tmp/worktrees/task-t1",
            }
        )

        # Should complete without error (falls back to simulated results).
        assert result["status"] == "testing"

    def test_plan_sets_branch_name(self) -> None:
        from selva_workers.graphs.coding import plan

        result = plan(
            {
                "messages": [AIMessage(content="Build a feature")],
                "task_id": "t1",
            }
        )

        assert result["branch_name"] == "selva/task-t1"


class TestPushGateCommitPush:
    """push_gate commits and pushes on approval (Gap 3)."""

    def test_approved_commits_and_pushes_before_cleanup(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.configure_identity = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.commit = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.push = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.create_pr = AsyncMock(
            return_value=MagicMock(return_code=0, stdout="", stderr=""),
        )
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = None
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch(
                "selva_workers.graphs.coding.interrupt",
                return_value={"approved": True},
            ),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch(
                "selva_workers.config.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [{"iteration": 1}],
                    "worktree_path": "/tmp/worktrees/task-t1",
                    "task_id": "t1",
                    "description": "Add feature X",
                    "branch_name": "selva/task-t1",
                }
            )

        assert result["status"] == "pushed"
        mock_git.commit.assert_called_once_with(
            "/tmp/worktrees/task-t1",
            "selva: Add feature X",
        )
        mock_git.push.assert_called_once_with(
            "/tmp/worktrees/task-t1",
            "selva/task-t1",
            token=None,
        )
        # Cleanup should still happen after commit+push.
        mock_git.cleanup_worktree.assert_called_once()

    def test_denied_does_not_commit_or_push(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.commit = AsyncMock()
        mock_git.push = AsyncMock()
        mock_git.cleanup_worktree = AsyncMock()

        with (
            patch(
                "selva_workers.graphs.coding.interrupt",
                return_value={"approved": False, "feedback": "Needs work"},
            ),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [],
                    "worktree_path": "/tmp/worktrees/task-t1",
                    "task_id": "t1",
                }
            )

        assert result["status"] == "denied"
        mock_git.commit.assert_not_called()
        mock_git.push.assert_not_called()
        # Cleanup still happens on deny.
        mock_git.cleanup_worktree.assert_called_once()

    def test_commit_failure_does_not_prevent_cleanup(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.configure_identity = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.commit = AsyncMock(
            return_value=MagicMock(return_code=1, stderr="nothing to commit"),
        )
        mock_git.push = AsyncMock()
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = None
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch(
                "selva_workers.graphs.coding.interrupt",
                return_value={"approved": True},
            ),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch(
                "selva_workers.config.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [{"iteration": 1}],
                    "worktree_path": "/tmp/worktrees/task-t1",
                    "task_id": "t1",
                    "branch_name": "selva/task-t1",
                }
            )

        assert result["status"] == "pushed"
        # Push should NOT be called when commit fails.
        mock_git.push.assert_not_called()
        # Cleanup should still happen.
        mock_git.cleanup_worktree.assert_called_once()
