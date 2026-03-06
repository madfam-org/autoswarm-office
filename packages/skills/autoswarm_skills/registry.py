"""Skill registry: discovery, caching, and prompt assembly."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .defaults import DEFAULT_ROLE_SKILLS
from .parser import parse_skill_md
from .types import SkillDefinition, SkillMetadata, SkillTier

logger = logging.getLogger(__name__)

_SKILL_DEFINITIONS_DIR = Path(__file__).resolve().parent.parent / "skill-definitions"
_COMMUNITY_SKILLS_DIR = Path(__file__).resolve().parent.parent / "community-skills"


class SkillRegistry:
    """Discovers, caches, and serves AgentSkills-standard skill definitions.

    On construction the registry walks ``skills_dir`` and parses YAML
    frontmatter from each ``SKILL.md`` into a lightweight metadata cache.
    Full instruction bodies are loaded lazily on first ``activate()`` call.

    Community skills are discovered from a separate directory and are
    disabled by default. Use ``enable_community_skills()`` /
    ``disable_community_skills()`` for runtime control.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        community_skills_dir: Path | None = None,
        community_enabled: bool = False,
    ) -> None:
        self._skills_dir = skills_dir or _SKILL_DEFINITIONS_DIR
        self._community_skills_dir = community_skills_dir or _COMMUNITY_SKILLS_DIR
        self._community_enabled = community_enabled
        self._metadata: dict[str, SkillMetadata] = {}
        self._definitions: dict[str, SkillDefinition] = {}
        self._skill_source: dict[str, Path] = {}
        self._discover()

    # -- Discovery -------------------------------------------------------------

    def _discover(self) -> None:
        """Walk skill directories and populate metadata cache."""
        self._discover_from_dir(self._skills_dir, tier=SkillTier.CORE)
        if self._community_enabled:
            self._discover_from_dir(self._community_skills_dir, tier=SkillTier.COMMUNITY)

    def _discover_from_dir(self, directory: Path, tier: SkillTier) -> None:
        """Parse all SKILL.md files under *directory*, assigning *tier*."""
        if not directory.is_dir():
            logger.warning("Skills directory not found: %s", directory)
            return
        for skill_md in directory.rglob("SKILL.md"):
            try:
                meta, _ = parse_skill_md(skill_md)
                # Core skills take precedence on name collision.
                if meta.name in self._metadata:
                    existing_tier = self._metadata[meta.name].tier
                    if existing_tier == SkillTier.CORE and tier == SkillTier.COMMUNITY:
                        logger.info(
                            "Skipping community skill '%s': overridden by core", meta.name
                        )
                        continue
                meta.tier = tier
                self._metadata[meta.name] = meta
                self._skill_source[meta.name] = skill_md.parent
            except Exception:
                logger.warning("Failed to parse %s", skill_md, exc_info=True)

    # -- Queries ---------------------------------------------------------------

    def list_skills(self, tier: SkillTier | None = None) -> list[SkillMetadata]:
        """Return metadata for discovered skills, optionally filtered by tier."""
        if tier is None:
            return list(self._metadata.values())
        return [m for m in self._metadata.values() if m.tier == tier]

    def get_metadata(self, name: str) -> SkillMetadata | None:
        """Return metadata for a single skill, or None if not found."""
        return self._metadata.get(name)

    def activate(self, name: str) -> SkillDefinition:
        """Load full SKILL.md body on demand. Cache after first load.

        Raises:
            KeyError: If the skill name is not discovered.
        """
        if name in self._definitions:
            return self._definitions[name]

        meta = self._metadata.get(name)
        if meta is None:
            raise KeyError(f"Skill '{name}' not found in registry")

        skill_dir = self._skill_source[name]
        skill_md_path = skill_dir / "SKILL.md"
        _, body = parse_skill_md(skill_md_path)

        definition = SkillDefinition(
            meta=meta,
            instructions=body,
            skill_dir=skill_dir,
        )
        self._definitions[name] = definition
        return definition

    def get_skills_for_role(self, role: str) -> list[str]:
        """Return DEFAULT_ROLE_SKILLS[role], or empty list for unknown roles."""
        return list(DEFAULT_ROLE_SKILLS.get(role, []))

    def build_system_prompt(self, skill_names: list[str]) -> str:
        """Activate each skill, concatenate instructions with headers."""
        sections: list[str] = []
        for name in skill_names:
            try:
                defn = self.activate(name)
                sections.append(f"## Skill: {defn.meta.name}\n\n{defn.instructions}")
            except (KeyError, Exception):
                logger.warning("Could not activate skill '%s' for prompt", name)
        return "\n\n---\n\n".join(sections)

    def get_allowed_tools(self, skill_names: list[str]) -> list[str]:
        """Union of allowed-tools from named skills."""
        tools: set[str] = set()
        for name in skill_names:
            meta = self._metadata.get(name)
            if meta:
                tools.update(meta.allowed_tools)
        return sorted(tools)

    # -- Community skill control -----------------------------------------------

    @property
    def community_enabled(self) -> bool:
        """Whether community skills are currently loaded."""
        return self._community_enabled

    def enable_community_skills(self) -> None:
        """Discover and load community skills at runtime."""
        if self._community_enabled:
            return
        self._community_enabled = True
        self._discover_from_dir(self._community_skills_dir, tier=SkillTier.COMMUNITY)

    def disable_community_skills(self) -> None:
        """Remove all community skills from the registry."""
        if not self._community_enabled:
            return
        self._community_enabled = False
        community_names = [
            n for n, m in self._metadata.items() if m.tier == SkillTier.COMMUNITY
        ]
        for name in community_names:
            del self._metadata[name]
            self._definitions.pop(name, None)
            self._skill_source.pop(name, None)


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Return (or create) the global SkillRegistry singleton."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        community_enabled = os.getenv(
            "AUTOSWARM_COMMUNITY_SKILLS_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        _registry = SkillRegistry(community_enabled=community_enabled)
    return _registry
