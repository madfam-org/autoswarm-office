"""Tests for hardened command parsing and MCP command validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from selva_tools.mcp.client import _validate_stdio_command
from selva_tools.process_registry import _split_command


def test_process_registry_splits_quoted_commands() -> None:
    assert _split_command('echo "hello world"') == ["echo", "hello world"]


@pytest.mark.parametrize(
    "command",
    [
        "echo hello; echo world",
        "echo hello & echo world",
        "echo hello | cat",
        "cat < input.txt",
        "cat > output.txt",
        "echo `whoami`",
        "echo $HOME",
        "echo \n",
    ],
)
def test_process_registry_rejects_shell_metacharacters(command: str) -> None:
    with pytest.raises(ValueError, match="Shell metacharacters are not allowed"):
        _split_command(command)


def test_mcp_stdio_validation_rejects_disallowed_binary(tmp_path: Path) -> None:
    executable = tmp_path / "not_allowed"
    executable.write_text("#!/bin/sh\necho hi\n")
    executable.chmod(0o755)
    with pytest.raises(ValueError, match="Disallowed MCP stdio executable"):
        _validate_stdio_command([str(executable), "tool"])


def test_mcp_stdio_validation_accepts_absolute_executable(tmp_path: Path) -> None:
    executable = tmp_path / "node"
    executable.write_text("#!/bin/sh\necho hi\n")
    executable.chmod(0o755)
    validated = _validate_stdio_command([str(executable), "--help"])
    assert validated == [str(executable), "--help"]

