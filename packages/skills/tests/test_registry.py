"""Tests for the SkillRegistry."""

from __future__ import annotations

from pathlib import Path

import pytest

from autoswarm_skills.defaults import DEFAULT_ROLE_SKILLS
from autoswarm_skills.registry import SkillRegistry

# Resolve to the real skill-definitions directory
SKILL_DEFS_DIR = Path(__file__).resolve().parent.parent / "skill-definitions"


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry(skills_dir=SKILL_DEFS_DIR)


def test_registry_discovers_all_skills(registry: SkillRegistry) -> None:
    skills = registry.list_skills()
    names = {s.name for s in skills}
    expected = {
        "coding",
        "code-review",
        "research",
        "strategic-planning",
        "crm-outreach",
        "customer-support",
        "madfam-api",
        "webapp-testing",
        "mcp-builder",
        "doc-coauthoring",
        "skill-creator",
    }
    assert expected.issubset(names), f"Missing skills: {expected - names}"
    assert len(skills) >= 11


def test_registry_get_metadata(registry: SkillRegistry) -> None:
    meta = registry.get_metadata("coding")
    assert meta is not None
    assert meta.name == "coding"
    assert "file_read" in meta.allowed_tools


def test_registry_get_metadata_unknown(registry: SkillRegistry) -> None:
    assert registry.get_metadata("nonexistent-skill") is None


def test_registry_activate_caches(registry: SkillRegistry) -> None:
    defn1 = registry.activate("coding")
    defn2 = registry.activate("coding")
    assert defn1 is defn2  # Same object, not re-parsed


def test_registry_activate_loads_body(registry: SkillRegistry) -> None:
    defn = registry.activate("coding")
    assert defn.meta.name == "coding"
    assert len(defn.instructions) > 0
    assert "MADFAM" in defn.instructions


def test_registry_activate_unknown_raises(registry: SkillRegistry) -> None:
    with pytest.raises(KeyError, match="not found"):
        registry.activate("nonexistent-skill")


def test_build_system_prompt_concatenates(registry: SkillRegistry) -> None:
    prompt = registry.build_system_prompt(["coding", "code-review"])
    assert "## Skill: coding" in prompt
    assert "## Skill: code-review" in prompt
    assert "---" in prompt  # separator between skills


def test_build_system_prompt_skips_unknown(registry: SkillRegistry) -> None:
    prompt = registry.build_system_prompt(["coding", "nonexistent"])
    assert "## Skill: coding" in prompt
    assert "nonexistent" not in prompt


def test_get_skills_for_role_defaults(registry: SkillRegistry) -> None:
    for role, expected_skills in DEFAULT_ROLE_SKILLS.items():
        result = registry.get_skills_for_role(role)
        assert result == expected_skills, f"Mismatch for role '{role}'"


def test_get_skills_for_role_unknown(registry: SkillRegistry) -> None:
    assert registry.get_skills_for_role("unknown_role") == []


def test_get_allowed_tools_union(registry: SkillRegistry) -> None:
    tools = registry.get_allowed_tools(["coding", "madfam-api"])
    # coding has file_read, file_write, bash_execute, git_commit
    # madfam-api has api_call, file_read
    assert "file_read" in tools
    assert "file_write" in tools
    assert "api_call" in tools
    assert "bash_execute" in tools
    assert "git_commit" in tools


def test_get_allowed_tools_empty(registry: SkillRegistry) -> None:
    assert registry.get_allowed_tools([]) == []


def test_get_allowed_tools_unknown_skill(registry: SkillRegistry) -> None:
    # Unknown skills are silently skipped
    tools = registry.get_allowed_tools(["nonexistent"])
    assert tools == []


def test_registry_empty_dir(tmp_path: Path) -> None:
    """Registry with empty skills dir discovers nothing."""
    reg = SkillRegistry(skills_dir=tmp_path)
    assert reg.list_skills() == []
