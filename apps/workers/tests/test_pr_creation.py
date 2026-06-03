"""Tests for PR creation after push (Gap B)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreatePr:
    """GitTool.create_pr calls gh CLI."""

    @pytest.mark.asyncio
    async def test_create_pr_calls_gh(self) -> None:
        from selva_workers.tools.git_tool import GitTool

        tool = GitTool()
        tool.bash = MagicMock()
        # First call: `command -v gh` (check), second: `gh pr create ...`
        tool.bash.execute = AsyncMock(
            return_value=MagicMock(
                success=True,
                stdout="https://github.com/org/repo/pull/42\n",
                stderr="",
                return_code=0,
            )
        )

        result = await tool.create_pr("/repo", "feat/x", "Title", "Body text")

        assert tool.bash.execute.call_count == 3  # command -v gh, git remote get-url, gh pr create
        cmd = tool.bash.execute.call_args_list[2][0][0]
        assert "gh pr create" in cmd
        assert "--head feat/x" in cmd
        assert "Title" in cmd
        assert "Body text" in cmd
        assert result.return_code == 0

    @pytest.mark.asyncio
    async def test_create_pr_escapes_quotes(self) -> None:
        from selva_workers.tools.git_tool import GitTool

        tool = GitTool()
        tool.bash = MagicMock()
        tool.bash.execute = AsyncMock(
            return_value=MagicMock(success=True, stdout="", stderr="", return_code=0)
        )

        await tool.create_pr("/repo", "feat/x", "It's a title", "It's a body")

        # Third call is the actual gh pr create (1st: command -v gh, 2nd: git remote)
        cmd = tool.bash.execute.call_args_list[2][0][0]
        # Single quotes should be escaped
        assert "'\\''" in cmd


class TestPrCreationAfterPush:
    """_create_pr_after_push is called in push_gate on successful push."""

    def test_pr_created_on_successful_push(self) -> None:
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
            return_value=MagicMock(return_code=0, stdout="https://github.com/pull/1\n", stderr=""),
        )
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = "ghp_test"
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch("selva_workers.graphs.coding.interrupt", return_value={"approved": True}),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch("selva_workers.config.get_settings", return_value=mock_settings),
        ):
            result = push_gate(
                {
                    "messages": [],
                    "code_changes": [{"iteration": 1, "files_modified": ["src/main.py"]}],
                    "worktree_path": "/tmp/worktrees/task-t1",
                    "task_id": "t1",
                    "description": "Add feature X",
                    "branch_name": "selva/task-t1",
                }
            )

        assert result["status"] == "pushed"
        mock_git.create_pr.assert_called_once()

    def test_pr_not_created_on_push_failure(self) -> None:
        from selva_workers.graphs.coding import push_gate

        mock_git = MagicMock()
        mock_git.configure_identity = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.commit = AsyncMock(
            return_value=MagicMock(return_code=0, stderr=""),
        )
        mock_git.push = AsyncMock(
            return_value=MagicMock(return_code=1, stderr="rejected"),
        )
        mock_git.create_pr = AsyncMock()
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = "ghp_test"
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch("selva_workers.graphs.coding.interrupt", return_value={"approved": True}),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch("selva_workers.config.get_settings", return_value=mock_settings),
        ):
            push_gate(
                {
                    "messages": [],
                    "code_changes": [{"iteration": 1}],
                    "worktree_path": "/tmp/worktrees/task-t1",
                    "task_id": "t1",
                    "branch_name": "selva/task-t1",
                }
            )

        mock_git.create_pr.assert_not_called()

    def test_pr_failure_does_not_block_task(self) -> None:
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
            return_value=MagicMock(return_code=1, stdout="", stderr="gh: error"),
        )
        mock_git.cleanup_worktree = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.github_token = "ghp_test"
        mock_settings.git_author_name = "selva-bot"
        mock_settings.git_author_email = "bot@selva.town"

        with (
            patch("selva_workers.graphs.coding.interrupt", return_value={"approved": True}),
            patch("selva_workers.tools.git_tool.GitTool", return_value=mock_git),
            patch("selva_workers.config.get_settings", return_value=mock_settings),
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

        # Task should still succeed even if PR creation fails
        assert result["status"] == "pushed"
