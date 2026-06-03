"""Tests for implement() file writing (Gap 2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage


class TestWriteFilesToWorktree:
    """_write_files_to_worktree parses JSON and writes files safely."""

    def test_writes_valid_json_files(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "src/main.py", "content": "print('hello')"},
                    {"path": "README.md", "content": "# Project"},
                ]
            }
        )

        result = _write_files_to_worktree(str(tmp_path), llm_output, {})

        assert result == ["src/main.py", "README.md"]
        assert (tmp_path / "src" / "main.py").read_text() == "print('hello')"
        assert (tmp_path / "README.md").read_text() == "# Project"

    def test_rejects_absolute_paths(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "/etc/passwd", "content": "malicious"},
                ]
            }
        )

        result = _write_files_to_worktree(str(tmp_path), llm_output, {})

        # Should fall back to placeholder since no valid files were written.
        assert result == ["SELVA_PLACEHOLDER.md"]
        assert not Path("/etc/passwd").exists() or Path("/etc/passwd").read_text() != "malicious"

    def test_rejects_directory_traversal(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "../../../etc/shadow", "content": "malicious"},
                ]
            }
        )

        result = _write_files_to_worktree(str(tmp_path), llm_output, {})

        assert result == ["SELVA_PLACEHOLDER.md"]

    def test_writes_placeholder_on_invalid_json(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        result = _write_files_to_worktree(str(tmp_path), "not valid json", {})

        assert result == ["SELVA_PLACEHOLDER.md"]
        assert (tmp_path / "SELVA_PLACEHOLDER.md").exists()

    def test_writes_placeholder_when_no_llm_output(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        result = _write_files_to_worktree(
            str(tmp_path),
            None,
            {"description": "Create hello world"},
        )

        assert result == ["SELVA_PLACEHOLDER.md"]
        content = (tmp_path / "SELVA_PLACEHOLDER.md").read_text()
        assert "Create hello world" in content

    def test_returns_empty_when_no_worktree(self) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        result = _write_files_to_worktree(None, '{"files": []}', {})
        assert result == []

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "a/b/c/deep.py", "content": "deep"},
                ]
            }
        )

        result = _write_files_to_worktree(str(tmp_path), llm_output, {})

        assert result == ["a/b/c/deep.py"]
        assert (tmp_path / "a" / "b" / "c" / "deep.py").read_text() == "deep"

    def test_skips_entries_with_empty_path(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import _write_files_to_worktree

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "", "content": "empty path"},
                    {"path": "valid.py", "content": "ok"},
                ]
            }
        )

        result = _write_files_to_worktree(str(tmp_path), llm_output, {})

        assert result == ["valid.py"]


class TestImplementWritesFiles:
    """implement() integration: LLM output → files on disk."""

    def test_implement_writes_files_from_llm(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import implement

        llm_output = json.dumps(
            {
                "files": [
                    {"path": "app.py", "content": "print('app')"},
                ]
            }
        )

        with (
            patch(
                "selva_workers.inference.call_llm",
                return_value=llm_output,
            ),
            patch(
                "selva_workers.inference.get_model_router",
                return_value=MagicMock(),
            ),
        ):
            result = implement(
                {
                    "messages": [
                        AIMessage(
                            content="Plan ready",
                            additional_kwargs={"plan": {"steps": ["step1"]}},
                        )
                    ],
                    "worktree_path": str(tmp_path),
                    "iteration": 0,
                }
            )

        assert (tmp_path / "app.py").read_text() == "print('app')"
        assert result["code_changes"][-1]["files_modified"] == ["app.py"]

    def test_implement_falls_back_to_placeholder(self, tmp_path: Path) -> None:
        from selva_workers.graphs.coding import implement

        with patch(
            "selva_workers.inference.get_model_router",
            side_effect=RuntimeError("no providers"),
        ):
            result = implement(
                {
                    "messages": [
                        AIMessage(
                            content="Plan ready",
                            additional_kwargs={"plan": {"steps": ["step1"]}},
                        )
                    ],
                    "worktree_path": str(tmp_path),
                    "iteration": 0,
                    "description": "Test task",
                }
            )

        assert (tmp_path / "SELVA_PLACEHOLDER.md").exists()
        assert "SELVA_PLACEHOLDER.md" in result["code_changes"][-1]["files_modified"]

    def test_implement_blocked_by_permission_deny(self) -> None:
        from selva_workers.graphs.coding import implement

        mock_result = MagicMock()
        mock_result.level = MagicMock()
        mock_result.level.__eq__ = lambda self, other: str(other) == "deny" or other.value == "deny"

        from selva_permissions.types import PermissionLevel

        mock_result.level = PermissionLevel.DENY

        with patch(
            "selva_workers.graphs.coding.check_permission",
            return_value=mock_result,
        ):
            result = implement(
                {
                    "messages": [],
                    "iteration": 0,
                }
            )

        assert result["status"] == "blocked"
