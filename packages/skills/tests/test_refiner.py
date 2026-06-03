"""Tests for the SkillRefiner iterative refinement and metrics."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from selva_skills.refiner import RefinerMetrics, SkillRefiner

VALID_SKILL = textwrap.dedent("""\
    SKILL_SCHEMA_VERSION = "agentskills/v1"
    SKILL_VERSION = "1.0.0"
    SKILL_AUTHOR = "selva-qa-oracle"
    SKILL_TAGS = ["test"]
    SKILL_DESCRIPTION = "A test skill that always passes."
    SKILL_METADATA = {"run_id": "test-run", "last_validated": "2020-01-01T00:00:00+00:00"}

    def SKILL_ENTRYPOINT(*args, **kwargs):
        return "ok"
""")

BROKEN_SKILL = textwrap.dedent("""\
    SKILL_SCHEMA_VERSION = "agentskills/v1"
    SKILL_VERSION = "1.0.0"
    SKILL_AUTHOR = "selva-qa-oracle"
    SKILL_TAGS = ["broken"]
    SKILL_DESCRIPTION = "Broken skill."
    SKILL_METADATA = {"run_id": "broken-run", "last_validated": "2020-01-01T00:00:00+00:00"}

    def SKILL_ENTRYPOINT(*args, **kwargs):
        raise RuntimeError("intentional failure")
""")


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    return tmp_path


def _write(skills_dir: Path, name: str, code: str) -> Path:
    p = skills_dir / f"{name}.py"
    p.write_text(code)
    return p


class TestIterativeRefinement:
    """Tests for the iterative sandbox-validate-retry loop in _llm_refine."""

    def test_iterative_refinement_succeeds_on_second_try(self, skills_dir: Path) -> None:
        """LLM produces bad code first, then good code -- should succeed on iteration 2."""
        _write(skills_dir, "retry_skill", BROKEN_SKILL)
        refiner = SkillRefiner(skills_dir=str(skills_dir), max_iterations=3)

        # First _call_llm returns broken code, second returns valid code
        broken_output = BROKEN_SKILL  # Still raises RuntimeError
        valid_output = VALID_SKILL

        call_count = 0

        def mock_call_llm(original_code: str, failure_details: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return broken_output
            return valid_output

        with patch.object(refiner, "_call_llm", side_effect=mock_call_llm):
            result = refiner._llm_refine(
                skills_dir / "retry_skill.py",
                BROKEN_SKILL,
                "intentional failure",
            )

        assert result == "refined"
        assert call_count == 2
        # The file should now contain the valid code
        final_code = (skills_dir / "retry_skill.py").read_text()
        assert 'return "ok"' in final_code
        # Metrics should reflect 2 iterations used
        assert refiner._metrics.total_iterations == 2

    def test_iterative_refinement_gives_up_after_max_iterations(self, skills_dir: Path) -> None:
        """When all iterations fail sandbox validation, return 'failed' and restore original."""
        _write(skills_dir, "hopeless_skill", BROKEN_SKILL)
        refiner = SkillRefiner(skills_dir=str(skills_dir), max_iterations=3)

        # _call_llm always returns broken code
        def mock_call_llm(original_code: str, failure_details: str) -> str:
            return BROKEN_SKILL

        with patch.object(refiner, "_call_llm", side_effect=mock_call_llm):
            result = refiner._llm_refine(
                skills_dir / "hopeless_skill.py",
                BROKEN_SKILL,
                "intentional failure",
            )

        assert result == "failed"
        # Original code should be restored after exhausting all iterations
        final_code = (skills_dir / "hopeless_skill.py").read_text()
        assert final_code == BROKEN_SKILL
        # All 3 iterations should have been attempted
        assert refiner._metrics.total_iterations == 3

    def test_iterative_refinement_succeeds_on_first_try(self, skills_dir: Path) -> None:
        """When the first LLM attempt passes sandbox, no retry needed."""
        _write(skills_dir, "easy_skill", BROKEN_SKILL)
        refiner = SkillRefiner(skills_dir=str(skills_dir), max_iterations=3)

        call_count = 0

        def mock_call_llm(original_code: str, failure_details: str) -> str:
            nonlocal call_count
            call_count += 1
            return VALID_SKILL

        with patch.object(refiner, "_call_llm", side_effect=mock_call_llm):
            result = refiner._llm_refine(
                skills_dir / "easy_skill.py",
                BROKEN_SKILL,
                "intentional failure",
            )

        assert result == "refined"
        assert call_count == 1
        assert refiner._metrics.total_iterations == 1


class TestRefinerMetrics:
    """Tests for RefinerMetrics accumulation during refine_all()."""

    def test_metrics_accumulate_during_refine_all(self, skills_dir: Path) -> None:
        """Verify that metrics counters are correctly updated across multiple skills."""
        from datetime import UTC, datetime

        # Create 3 skills: one fresh (skip), one stale (refine), one broken (refine)
        fresh_skill = VALID_SKILL.replace(
            '"2020-01-01T00:00:00+00:00"',
            f'"{datetime.now(tz=UTC).isoformat()}"',
        )
        _write(skills_dir, "fresh_skill", fresh_skill)
        _write(skills_dir, "stale_skill", VALID_SKILL)  # last_validated=2020
        _write(skills_dir, "broken_skill", BROKEN_SKILL)

        refiner = SkillRefiner(skills_dir=str(skills_dir), max_iterations=3)

        # Mock _call_llm: returns valid code for stale, broken code for broken
        def mock_call_llm(original_code: str, failure_details: str) -> str:
            if "always passes" in original_code:
                # Stale but valid skill -- return valid refinement
                return fresh_skill
            # Broken skill -- always return broken code (will exhaust iterations)
            return BROKEN_SKILL

        with patch.object(refiner, "_call_llm", side_effect=mock_call_llm):
            results = refiner.refine_all()

        metrics = refiner.get_metrics()

        # All 3 skills were checked
        assert metrics.skills_checked == 3
        # fresh_skill skipped, stale_skill refined, broken_skill failed
        assert results["fresh_skill"] == "skipped"
        assert results["stale_skill"] == "refined"
        assert results["broken_skill"] == "failed"
        # stale_skill refined successfully
        assert metrics.skills_refined == 1
        # broken_skill exhausted all iterations
        assert metrics.skills_failed == 1
        # stale_skill: 1 iteration, broken_skill: 3 iterations = 4 total
        assert metrics.total_iterations == 4
        # avg_refinement_ms should be > 0 (two skills went through _llm_refine)
        assert metrics.avg_refinement_ms > 0.0

    def test_metrics_reset_on_each_refine_all(self, skills_dir: Path) -> None:
        """Each call to refine_all() starts with fresh metrics."""
        from datetime import UTC, datetime

        fresh_skill = VALID_SKILL.replace(
            '"2020-01-01T00:00:00+00:00"',
            f'"{datetime.now(tz=UTC).isoformat()}"',
        )
        _write(skills_dir, "skill_a", fresh_skill)

        refiner = SkillRefiner(skills_dir=str(skills_dir))

        # First run
        refiner.refine_all()
        assert refiner.get_metrics().skills_checked == 1

        # Second run should reset
        refiner.refine_all()
        assert refiner.get_metrics().skills_checked == 1  # Not 2

    def test_metrics_dataclass_defaults(self) -> None:
        """RefinerMetrics initializes with zero values."""
        metrics = RefinerMetrics()
        assert metrics.skills_checked == 0
        assert metrics.skills_refined == 0
        assert metrics.skills_failed == 0
        assert metrics.total_iterations == 0
        assert metrics.avg_refinement_ms == 0.0

    def test_metrics_record_refinement_averaging(self) -> None:
        """record_refinement correctly maintains a running average."""
        metrics = RefinerMetrics()
        metrics.record_refinement(100.0)
        assert metrics.avg_refinement_ms == 100.0

        metrics.record_refinement(200.0)
        assert metrics.avg_refinement_ms == 150.0

        metrics.record_refinement(300.0)
        assert metrics.avg_refinement_ms == 200.0
