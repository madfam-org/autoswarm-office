"""Tests for community skill discovery, enable/disable, and tier filtering."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from autoswarm_skills.registry import SkillRegistry, get_skill_registry
from autoswarm_skills.types import SkillTier

SKILL_DEFS_DIR = Path(__file__).resolve().parent.parent / "skill-definitions"
COMMUNITY_DIR = Path(__file__).resolve().parent.parent / "community-skills"

CORE_SKILL_COUNT = 11


@pytest.fixture()
def registry() -> SkillRegistry:
    """Registry with community disabled (default)."""
    return SkillRegistry(skills_dir=SKILL_DEFS_DIR, community_skills_dir=COMMUNITY_DIR)


@pytest.fixture()
def registry_with_community() -> SkillRegistry:
    """Registry with community enabled from the start."""
    return SkillRegistry(
        skills_dir=SKILL_DEFS_DIR,
        community_skills_dir=COMMUNITY_DIR,
        community_enabled=True,
    )


# -- Basic discovery ----------------------------------------------------------


def test_community_disabled_by_default(registry: SkillRegistry) -> None:
    assert not registry.community_enabled
    skills = registry.list_skills()
    assert len(skills) == CORE_SKILL_COUNT


def test_community_enabled_discovers_all(registry_with_community: SkillRegistry) -> None:
    assert registry_with_community.community_enabled
    all_skills = registry_with_community.list_skills()
    assert len(all_skills) > CORE_SKILL_COUNT


# -- Tier assignment ----------------------------------------------------------


def test_community_skill_tier_is_community(registry_with_community: SkillRegistry) -> None:
    community = registry_with_community.list_skills(tier=SkillTier.COMMUNITY)
    assert len(community) > 0
    for m in community:
        assert m.tier == SkillTier.COMMUNITY


def test_core_skill_tier_is_core(registry_with_community: SkillRegistry) -> None:
    core = registry_with_community.list_skills(tier=SkillTier.CORE)
    assert len(core) == CORE_SKILL_COUNT
    for m in core:
        assert m.tier == SkillTier.CORE


# -- Tier filtering -----------------------------------------------------------


def test_list_skills_filter_by_tier(registry_with_community: SkillRegistry) -> None:
    core = registry_with_community.list_skills(tier=SkillTier.CORE)
    community = registry_with_community.list_skills(tier=SkillTier.COMMUNITY)
    all_skills = registry_with_community.list_skills()
    assert len(core) + len(community) == len(all_skills)


# -- Name collision -----------------------------------------------------------


def test_name_collision_core_wins(tmp_path: Path) -> None:
    """If a community skill has the same name as a core skill, core wins."""
    # Create a fake community dir with a skill named "coding" (a core skill name)
    fake_community = tmp_path / "community"
    skill_dir = fake_community / "coding"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: coding\ndescription: Fake community coding\n---\nFake body\n"
    )
    reg = SkillRegistry(
        skills_dir=SKILL_DEFS_DIR,
        community_skills_dir=fake_community,
        community_enabled=True,
    )
    meta = reg.get_metadata("coding")
    assert meta is not None
    assert meta.tier == SkillTier.CORE
    assert "MADFAM" not in meta.description.lower() or "Fake" not in meta.description


# -- Enable / disable at runtime ---------------------------------------------


def test_enable_community_runtime(registry: SkillRegistry) -> None:
    assert len(registry.list_skills()) == CORE_SKILL_COUNT
    registry.enable_community_skills()
    assert registry.community_enabled
    assert len(registry.list_skills()) > CORE_SKILL_COUNT
    assert len(registry.list_skills(tier=SkillTier.COMMUNITY)) > 0


def test_disable_community_runtime(registry_with_community: SkillRegistry) -> None:
    assert len(registry_with_community.list_skills()) > CORE_SKILL_COUNT
    registry_with_community.disable_community_skills()
    assert not registry_with_community.community_enabled
    assert len(registry_with_community.list_skills()) == CORE_SKILL_COUNT
    assert len(registry_with_community.list_skills(tier=SkillTier.COMMUNITY)) == 0


def test_enable_idempotent(registry: SkillRegistry) -> None:
    registry.enable_community_skills()
    count_after_first = len(registry.list_skills())
    registry.enable_community_skills()
    count_after_second = len(registry.list_skills())
    assert count_after_first == count_after_second


def test_disable_idempotent(registry: SkillRegistry) -> None:
    registry.disable_community_skills()
    assert len(registry.list_skills()) == CORE_SKILL_COUNT
    registry.disable_community_skills()
    assert len(registry.list_skills()) == CORE_SKILL_COUNT


# -- Activation ---------------------------------------------------------------


def test_activate_community_skill(registry_with_community: SkillRegistry) -> None:
    community = registry_with_community.list_skills(tier=SkillTier.COMMUNITY)
    assert len(community) > 0
    first = community[0]
    defn = registry_with_community.activate(first.name)
    assert defn.meta.name == first.name
    assert len(defn.instructions) > 0


def test_build_prompt_with_community(registry_with_community: SkillRegistry) -> None:
    community = registry_with_community.list_skills(tier=SkillTier.COMMUNITY)
    assert len(community) > 0
    first_name = community[0].name
    prompt = registry_with_community.build_system_prompt(["coding", first_name])
    assert "## Skill: coding" in prompt
    assert f"## Skill: {first_name}" in prompt


# -- Property -----------------------------------------------------------------


def test_community_enabled_property(registry: SkillRegistry) -> None:
    assert not registry.community_enabled
    registry.enable_community_skills()
    assert registry.community_enabled
    registry.disable_community_skills()
    assert not registry.community_enabled


# -- Singleton env var --------------------------------------------------------


def test_env_var_controls_singleton() -> None:
    import autoswarm_skills.registry as reg_mod

    # Reset singleton
    reg_mod._registry = None
    with mock.patch.dict(os.environ, {"AUTOSWARM_COMMUNITY_SKILLS_ENABLED": "true"}):
        reg = get_skill_registry()
        assert reg.community_enabled
        assert len(reg.list_skills(tier=SkillTier.COMMUNITY)) > 0
    # Reset for other tests
    reg_mod._registry = None
