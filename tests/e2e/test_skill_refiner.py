"""
Tests for Gap 1: Skill Self-Improvement Loop (SkillRefiner).
"""

from __future__ import annotations

import textwrap
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_refine_all_skips_healthy_fresh_skill(skills_dir):
    """A passing, fresh skill should be reported as 'skipped'."""
    from datetime import datetime

    fresh_skill = VALID_SKILL.replace(
        '"2020-01-01T00:00:00+00:00"',
        f'"{datetime.now(tz=UTC).isoformat()}"',
    )
    _write(skills_dir, "healthy_skill", fresh_skill)

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir), refine_interval_days=7)
    results = refiner.refine_all()

    assert results.get("healthy_skill") == "skipped"


def test_refine_all_flags_stale_skill(skills_dir):
    """A passing skill with stale last_validated should be reported as 'refined'."""
    _write(skills_dir, "stale_skill", VALID_SKILL)  # last_validated=2020

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir), refine_interval_days=7)

    with patch.object(refiner, "_llm_refine", return_value="refined") as mock_refine:
        results = refiner.refine_all()

    assert results.get("stale_skill") == "refined"
    mock_refine.assert_called_once()


def test_refine_all_flags_broken_skill(skills_dir):
    """A skill whose SKILL_ENTRYPOINT raises should be marked 'refined'."""
    _write(skills_dir, "broken_skill", BROKEN_SKILL)

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir), refine_interval_days=7)

    with patch.object(refiner, "_llm_refine", return_value="refined"):
        results = refiner.refine_all()

    assert results.get("broken_skill") == "refined"


def test_refine_one_force(skills_dir):
    """refine_one(force=True) should refine regardless of freshness."""
    from datetime import datetime

    fresh_skill = VALID_SKILL.replace(
        '"2020-01-01T00:00:00+00:00"',
        f'"{datetime.now(tz=UTC).isoformat()}"',
    )
    _write(skills_dir, "forced_skill", fresh_skill)

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir))

    with patch.object(refiner, "_llm_refine", return_value="refined") as mock_refine:
        result = refiner.refine_one("forced_skill")

    assert result == "refined"
    mock_refine.assert_called_once()


def test_sandbox_execute_passes_valid_skill(skills_dir):
    path = _write(skills_dir, "sandbox_pass", VALID_SKILL)

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir))
    stderr, passed = refiner._sandbox_execute(path)
    assert passed is True


def test_sandbox_execute_fails_broken_skill(skills_dir):
    path = _write(skills_dir, "sandbox_fail", BROKEN_SKILL)

    from selva_skills.refiner import SkillRefiner

    refiner = SkillRefiner(skills_dir=str(skills_dir))
    stderr, passed = refiner._sandbox_execute(path)
    assert passed is False
    assert stderr  # should contain the traceback
