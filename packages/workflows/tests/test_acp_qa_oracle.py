"""Tests for the ACP QA Oracle (Phase IV validation loop)."""

from __future__ import annotations

import builtins
import logging
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from selva_workflows.acp_qa_oracle import ACPQAOracleNode

_real_import = builtins.__import__


@dataclass
class _BashResult:
    """Lightweight stand-in for the real BashTool result."""

    return_code: int
    stdout: str = ""
    stderr: str = ""


def _block_imports(*blocked_names: str):
    """Return an import function that raises ImportError for *blocked_names*
    and delegates everything else to the real import machinery."""

    def _import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name in blocked_names:
            raise ImportError(f"mocked: {name}")
        return _real_import(name, *args, **kwargs)

    return _import


class TestACPQAOracleInit:
    def test_init_stores_source_and_test_suite(self) -> None:
        node = ACPQAOracleNode(source_code="print(1)", test_suite="pytest -x")
        assert node.source_code == "print(1)"
        assert node.test_suite == "pytest -x"


class TestValidate:
    """Tests for ``ACPQAOracleNode.validate``."""

    # -- BashTool unavailable (ImportError) --------------------------------

    @patch("selva_workflows.acp_qa_oracle.asyncio")
    def test_validate_passes_when_bash_tool_unavailable(
        self, mock_asyncio: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When BashTool cannot be imported, tests_passed defaults to True
        and a warning is logged."""
        node = ACPQAOracleNode(source_code="x = 1", test_suite="pytest tests/")

        blocker = _block_imports(
            "selva_tools.approval",
            "selva_workers.tools.bash_tool",
        )

        with patch("builtins.__import__", side_effect=blocker):
            with caplog.at_level(logging.WARNING):
                result = node.validate("run-bash-missing")

        assert result is True
        assert any("BashTool unavailable" in msg for msg in caplog.messages)

    # -- BashTool returns exit code 0 (tests pass) -------------------------

    @patch("selva_workflows.acp_qa_oracle.asyncio")
    def test_validate_passes_when_bash_returns_zero(self, mock_asyncio: MagicMock) -> None:
        node = ACPQAOracleNode(source_code="x = 1", test_suite="pytest tests/")

        bash_result = _BashResult(return_code=0, stdout="all passed")
        # First asyncio.run call -> BashTool.execute; second -> compile_skill_async
        mock_asyncio.run.side_effect = [bash_result, None]

        def _import_with_mock_bash(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "selva_tools.approval":
                raise ImportError("mocked")
            if name == "selva_workers.tools.bash_tool":
                mod = MagicMock()
                mod.BashTool.return_value = MagicMock()
                return mod
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_with_mock_bash):
            result = node.validate("run-zero")

        assert result is True

    # -- BashTool returns non-zero exit code (tests fail) ------------------

    @patch("selva_workflows.acp_qa_oracle.asyncio")
    def test_validate_fails_when_bash_returns_nonzero(self, mock_asyncio: MagicMock) -> None:
        node = ACPQAOracleNode(source_code="x = 1", test_suite="pytest tests/")

        bash_result = _BashResult(return_code=1, stderr="FAILED test_foo")
        mock_asyncio.run.return_value = bash_result

        def _import_with_mock_bash(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "selva_tools.approval":
                raise ImportError("mocked")
            if name == "selva_workers.tools.bash_tool":
                mod = MagicMock()
                mod.BashTool.return_value = MagicMock()
                return mod
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_with_mock_bash):
            result = node.validate("run-nonzero")

        assert result is False
        # compile_skill_async should NOT have been called (only 1 asyncio.run)
        assert mock_asyncio.run.call_count == 1

    # -- Empty test_suite skips BashTool entirely --------------------------

    @patch("selva_workflows.acp_qa_oracle.asyncio")
    def test_validate_passes_with_empty_test_suite(self, mock_asyncio: MagicMock) -> None:
        """When test_suite is an empty string the ``if self.test_suite:``
        branch is skipped, so tests_passed stays True without needing BashTool."""
        node = ACPQAOracleNode(source_code="x = 1", test_suite="")

        mock_asyncio.run.return_value = None  # for compile_skill_async

        blocker = _block_imports("selva_tools.approval")

        with patch("builtins.__import__", side_effect=blocker):
            result = node.validate("run-empty-suite")

        assert result is True
        # asyncio.run should be called exactly once -- for compile_skill_async,
        # NOT for BashTool execution.
        mock_asyncio.run.assert_called_once()


class TestCompileSkillStub:
    """Tests for ``ACPQAOracleNode._compile_skill_stub``."""

    def test_compile_skill_stub_writes_file(self, tmp_path: pytest.TempPathFactory) -> None:
        node = ACPQAOracleNode(source_code="x = 1", test_suite="")
        run_id = "stub-run-001"

        with patch.dict(os.environ, {"SELVA_SKILLS_DIR": str(tmp_path)}):
            filepath = node._compile_skill_stub(run_id)

        assert filepath is not None
        assert os.path.isfile(filepath)

        with open(filepath) as f:
            content = f.read()
        assert "SKILL_DESCRIPTION" in content
        assert run_id in content
        assert "SKILL_ENTRYPOINT" in content
        assert "SKILL_METADATA" in content
