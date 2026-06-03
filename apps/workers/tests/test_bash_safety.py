"""Tests for BashTool blocked command patterns."""

from __future__ import annotations

import pytest

from selva_workers.tools.bash_tool import BashTool


@pytest.fixture
def bash() -> BashTool:
    return BashTool()


@pytest.mark.asyncio
async def test_blocks_rm_rf_absolute_home(bash: BashTool) -> None:
    result = await bash.execute("rm -rf /home/user")
    assert result.return_code == 126
    assert "blocked" in result.stderr.lower()


@pytest.mark.asyncio
async def test_blocks_rm_rf_tilde(bash: BashTool) -> None:
    result = await bash.execute("rm -rf ~/Documents")
    assert result.return_code == 126
    assert "blocked" in result.stderr.lower()


@pytest.mark.asyncio
async def test_blocks_rm_rf_env_var(bash: BashTool) -> None:
    result = await bash.execute("rm -rf $HOME")
    assert result.return_code == 126
    assert "blocked" in result.stderr.lower()


@pytest.mark.asyncio
async def test_blocks_rm_rf_var_data(bash: BashTool) -> None:
    result = await bash.execute("rm -rf /var/data")
    assert result.return_code == 126
    assert "blocked" in result.stderr.lower()


@pytest.mark.asyncio
async def test_allows_rm_rf_relative_build(bash: BashTool) -> None:
    """rm -rf on relative paths like ./build/ should NOT be blocked."""
    # We're not actually running rm — just checking it's not blocked.
    # Use _is_blocked directly for a clean test.
    assert bash._is_blocked("rm -rf ./build/") is None


@pytest.mark.asyncio
async def test_allows_rm_rf_relative_worktree(bash: BashTool) -> None:
    """Relative worktree paths should be allowed."""
    assert bash._is_blocked("rm -rf _worktrees/selva_task-1") is None
