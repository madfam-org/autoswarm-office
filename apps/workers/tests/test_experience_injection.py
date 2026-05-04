"""Tests for experience injection into graph prompts (PR 3: Agent Learning Loop)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_settings():
    return MagicMock(
        memory_persist_dir="/tmp/test-memory",
        bandit_persist_path="/tmp/test-bandit.json",
    )


def _make_experience_record(score=0.9, approach="used REST API", outcome="status=completed"):
    """Build a mock ExperienceRecord."""
    rec = MagicMock()
    rec.score = score
    rec.approach = approach
    rec.outcome = outcome
    return rec


class TestBuildExperienceContext:
    """build_experience_context retrieves and formats past experiences."""

    @pytest.mark.asyncio
    async def test_formats_similar_experiences(self) -> None:
        # search_similar / get_shortcuts / get_relevant_context are all
        # awaited inside build_experience_context (PR #108). MagicMock
        # would resolve `await mock(...)` to a non-iterable MagicMock and
        # the function silently returns "".
        mock_store = MagicMock()
        mock_store.search_similar = AsyncMock(
            return_value=[
                _make_experience_record(0.95, "Built REST endpoint", "status=completed, duration=30s"),
                _make_experience_record(0.4, "Used GraphQL", "status=failed, error=timeout"),
            ]
        )
        mock_store.get_shortcuts = AsyncMock(return_value=[])
        mock_mem = MagicMock()
        mock_mem.get_relevant_context = AsyncMock(return_value="")

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=mock_mem),
        ):
            from selva_workers.prompts import build_experience_context

            ctx = await build_experience_context("agent-1", "coder", "Build API endpoint")

            assert "Past Approaches" in ctx
            assert "[SUCCESS]" in ctx
            assert "[PARTIAL]" in ctx
            assert "Built REST endpoint" in ctx

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_string(self) -> None:
        mock_store = MagicMock()
        mock_store.search_similar = AsyncMock(return_value=[])
        mock_store.get_shortcuts = AsyncMock(return_value=[])
        mock_mem = MagicMock()
        mock_mem.get_relevant_context = AsyncMock(return_value="")

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=mock_mem),
        ):
            from selva_workers.prompts import build_experience_context

            ctx = await build_experience_context("agent-1", "coder", "New unique task")

            assert ctx == ""

    @pytest.mark.asyncio
    async def test_includes_shortcuts(self) -> None:
        mock_store = MagicMock()
        mock_store.search_similar = AsyncMock(return_value=[])
        mock_store.get_shortcuts = AsyncMock(return_value=["Use the batch processing pattern"])
        mock_mem = MagicMock()
        mock_mem.get_relevant_context = AsyncMock(return_value="")

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=mock_mem),
        ):
            from selva_workers.prompts import build_experience_context

            ctx = await build_experience_context("agent-1", "coder", "Process data in bulk")

            assert "Proven Approaches" in ctx
            assert "batch processing" in ctx

    @pytest.mark.asyncio
    async def test_includes_agent_memories(self) -> None:
        mock_store = MagicMock()
        mock_store.search_similar = AsyncMock(return_value=[])
        mock_store.get_shortcuts = AsyncMock(return_value=[])
        mock_mem = MagicMock()
        mock_mem.get_relevant_context = AsyncMock(
            return_value="## Relevant Memories\n- [0.85] Previously handled auth refactoring"
        )

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=mock_mem),
        ):
            from selva_workers.prompts import build_experience_context

            ctx = await build_experience_context("agent-1", "coder", "Refactor auth module")

            assert "Relevant Memories" in ctx
            assert "auth refactoring" in ctx

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_embedding_failure(self) -> None:
        with patch(
            "selva_memory.get_embedding_provider",
            side_effect=RuntimeError("embed fail"),
        ):
            from selva_workers.prompts import build_experience_context

            ctx = await build_experience_context("agent-1", "coder", "Some task")
            assert ctx == ""


class TestPlanPromptWithExperience:
    """build_plan_prompt correctly integrates experience_ctx parameter."""

    def test_includes_experience_in_prompt(self) -> None:
        from selva_workers.prompts import build_plan_prompt

        prompt = build_plan_prompt(
            "Build login page",
            experience_ctx="## Past Approaches\n- [SUCCESS] Used JWT auth",
        )

        assert "Past Approaches" in prompt
        assert "Used JWT auth" in prompt
        assert "implementation plan" in prompt.lower()

    def test_empty_experience_no_change(self) -> None:
        from selva_workers.prompts import build_plan_prompt

        prompt_without = build_plan_prompt("Build login page")
        prompt_with = build_plan_prompt("Build login page", experience_ctx="")

        assert prompt_without == prompt_with

    def test_skill_and_experience_both_included(self) -> None:
        from selva_workers.prompts import build_plan_prompt

        prompt = build_plan_prompt(
            "Build login page",
            skill_ctx="SKILL: auth-specialist",
            experience_ctx="## Past Approaches\n- Used OAuth",
        )

        assert "SKILL: auth-specialist" in prompt
        assert "Past Approaches" in prompt


class TestImplementPromptWithExperience:
    """build_implement_prompt includes experience_ctx."""

    def test_includes_experience(self) -> None:
        from selva_workers.prompts import build_implement_prompt

        prompt = build_implement_prompt(
            step="Create API endpoint",
            iteration=1,
            experience_ctx="## Past Approaches\n- Used FastAPI router pattern",
        )

        assert "Past Approaches" in prompt
        assert "FastAPI router" in prompt
