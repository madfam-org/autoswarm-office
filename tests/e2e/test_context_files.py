"""
E2E tests — Gap 5: Project Context Files (AGENTS.md / .selva.md)
"""


class TestContextFileLoader:
    def test_loads_agents_md(self, tmp_path):
        """AGENTS.md in workspace root is loaded and returned."""
        (tmp_path / "AGENTS.md").write_text("# Project Architecture\nUse hexagonal architecture.")
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader()
        result = loader.load_context(str(tmp_path))
        assert "Project Architecture" in result
        assert "hexagonal architecture" in result

    def test_selva_md_takes_precedence(self, tmp_path):
        """Both present: both injected, .selva.md listed last (highest priority)."""
        (tmp_path / "AGENTS.md").write_text("# AGENTS\nBase instructions.")
        (tmp_path / ".selva.md").write_text("# Local Override\nWorkspace-specific override.")
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader()
        result = loader.load_context(str(tmp_path))
        # Both present, .selva.md appears after AGENTS.md
        agents_pos = result.index("AGENTS")
        local_pos = result.index("Local Override")
        assert local_pos > agents_pos

    def test_cross_tool_files_loaded(self, tmp_path):
        """CLAUDE.md and GEMINI.md are also picked up for cross-tool compatibility."""
        (tmp_path / "CLAUDE.md").write_text("# Claude context\nSome docs.")
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader()
        result = loader.load_context(str(tmp_path))
        assert "Claude context" in result

    def test_nonexistent_workspace_returns_empty(self):
        """Non-existent workspace returns empty string without crashing."""
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader()
        result = loader.load_context("/this/does/not/exist")
        assert result == ""

    def test_empty_workspace_returns_empty(self, tmp_path):
        """Workspace with no context files returns empty string."""
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader()
        result = loader.load_context(str(tmp_path))
        assert result == ""

    def test_oversized_file_is_truncated(self, tmp_path):
        """Files exceeding the token cap are truncated with a warning marker."""
        huge_content = "word " * 50_000  # ~250k chars >> 32k limit
        (tmp_path / "AGENTS.md").write_text(huge_content)
        from selva_workflows.context_files import ContextFileLoader

        loader = ContextFileLoader(max_chars_per_file=1000)
        result = loader.load_context(str(tmp_path))
        assert "truncated" in result.lower()
        assert len(result) < 5000  # Sanity: nowhere near the full content
