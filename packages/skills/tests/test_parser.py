"""Tests for the AgentSkills SKILL.md parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autoswarm_skills.parser import parse_skill_md


@pytest.fixture()
def tmp_skill(tmp_path: Path):
    """Create a temporary skill directory with a valid SKILL.md."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill for unit testing.\n"
        "allowed_tools:\n"
        "  - file_read\n"
        "  - api_call\n"
        "metadata:\n"
        "  category: testing\n"
        "---\n\n"
        "# Test Skill\n\n"
        "These are the instructions.\n"
    )
    return skill_md


def test_parse_valid_skill_md(tmp_skill: Path) -> None:
    meta, body = parse_skill_md(tmp_skill)

    assert meta.name == "test-skill"
    assert meta.description == "A test skill for unit testing."
    assert meta.allowed_tools == ["file_read", "api_call"]
    assert meta.metadata == {"category": "testing"}
    assert "# Test Skill" in body
    assert "These are the instructions." in body


def test_parse_invalid_name_raises(tmp_path: Path) -> None:
    """Uppercase names should fail pydantic validation."""
    skill_dir = tmp_path / "Bad-Skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: Bad-Skill\n"
        "description: Invalid name.\n"
        "---\n\n"
        "Body.\n"
    )
    with pytest.raises((ValueError, ValidationError)):
        parse_skill_md(skill_md)


def test_parse_name_mismatch_raises(tmp_path: Path) -> None:
    """Skill name must match parent directory name."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: other-skill\n"
        "description: Mismatched name.\n"
        "---\n\n"
        "Body.\n"
    )
    with pytest.raises(ValueError, match="does not match"):
        parse_skill_md(skill_md)


def test_parse_missing_frontmatter_raises(tmp_path: Path) -> None:
    """Files without YAML frontmatter should fail."""
    skill_dir = tmp_path / "no-front"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# No frontmatter\n\nJust markdown.\n")
    with pytest.raises(ValueError, match="must start with"):
        parse_skill_md(skill_md)


def test_parse_skill_with_optional_fields(tmp_path: Path) -> None:
    """Optional fields like license and compatibility should parse."""
    skill_dir = tmp_path / "full-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: full-skill\n"
        "description: Skill with all optional fields.\n"
        "license: MIT\n"
        "compatibility: '>=0.1.0'\n"
        "allowed_tools: []\n"
        "---\n\n"
        "Instructions.\n"
    )
    meta, body = parse_skill_md(skill_md)
    assert meta.license == "MIT"
    assert meta.compatibility == ">=0.1.0"
    assert meta.allowed_tools == []
