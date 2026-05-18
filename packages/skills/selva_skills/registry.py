"""Skill registry: discovery, caching, and prompt assembly."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .defaults import DEFAULT_ROLE_SKILLS
from .parser import parse_skill_md
from .types import SkillAudience, SkillDefinition, SkillMetadata, SkillTier

logger = logging.getLogger(__name__)

_SKILL_DEFINITIONS_DIR = Path(__file__).resolve().parent.parent / "skill-definitions"
_COMMUNITY_SKILLS_DIR = Path(__file__).resolve().parent.parent / "community-skills"

# Feature flag env var — kept as a string check here so selva_skills
# doesn't take a hard dep on selva_permissions. Matches the env var
# declared in selva_permissions.audience.AUDIENCE_FILTER_ENABLED_ENV.
_AUDIENCE_FILTER_ENABLED_ENV = "AUDIENCE_FILTER_ENABLED"


def _enforcement_enabled() -> bool:
    import os

    return os.environ.get(_AUDIENCE_FILTER_ENABLED_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class SkillAudienceMismatch(RuntimeError):  # noqa: N818 — "mismatch" is semantic
    """Raised when a skill is activated by a swarm that lacks audience access."""


def _can_access_skill(skill_audience: SkillAudience, swarm_audience: SkillAudience | None) -> bool:
    """Mirror of ``selva_tools.can_access`` for skills.

    Platform swarms see everything; tenant swarms see only tenant-tagged
    skills. Unbound swarm_audience is permissive (backward compat).
    """
    if swarm_audience is None:
        return True
    if swarm_audience is SkillAudience.PLATFORM:
        return True
    return skill_audience is SkillAudience.TENANT


def _audience_violation(
    name: str, skill_audience: SkillAudience, swarm_audience: SkillAudience
) -> None:
    """Raise or shadow-log depending on the feature flag."""
    if _enforcement_enabled():
        raise SkillAudienceMismatch(
            f"skill '{name}' requires audience={skill_audience.value}, "
            f"swarm audience={swarm_audience.value}"
        )
    logger.warning(
        "audience_shadow_block skill=%s required=%s swarm=%s (permitting — "
        "AUDIENCE_FILTER_ENABLED off)",
        name,
        skill_audience.value,
        swarm_audience.value,
    )


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
                        logger.info("Skipping community skill '%s': overridden by core", meta.name)
                        continue
                meta.tier = tier
                self._metadata[meta.name] = meta
                self._skill_source[meta.name] = skill_md.parent
            except Exception:
                logger.warning("Failed to parse %s", skill_md, exc_info=True)

    # -- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        """Re-discover all skills, clearing caches.

        Useful after installing a new community skill at runtime so that
        the registry picks up newly added ``SKILL.md`` files.
        """
        self._metadata.clear()
        self._definitions.clear()
        self._skill_source.clear()
        self._discover()

    # -- Queries ---------------------------------------------------------------

    def list_skills(
        self,
        tier: SkillTier | None = None,
        *,
        audience: SkillAudience | None = None,
    ) -> list[SkillMetadata]:
        """Return metadata for discovered skills, optionally filtered.

        Args:
            tier: ``CORE`` or ``COMMUNITY`` filter.
            audience: ``PLATFORM`` sees all; ``TENANT`` sees only
                tenant-audience skills; ``None`` applies no filter.
        """
        results = list(self._metadata.values())
        if tier is not None:
            results = [m for m in results if m.tier == tier]
        if audience is not None:
            results = [m for m in results if _can_access_skill(m.audience, audience)]
        return results

    def get_metadata(self, name: str) -> SkillMetadata | None:
        """Return metadata for a single skill, or None if not found."""
        return self._metadata.get(name)

    def activate(
        self,
        name: str,
        *,
        audience: SkillAudience | None = None,
    ) -> SkillDefinition:
        """Load full SKILL.md body on demand. Cache after first load.

        Args:
            name: Skill identifier (must match discovered skill directory).
            audience: Optional swarm audience to enforce. If set and the
                skill's declared audience exceeds the swarm's, raises
                ``SkillAudienceMismatch`` before loading the body.

        Raises:
            KeyError: If the skill name is not discovered.
            SkillAudienceMismatch: If ``audience`` is set and incompatible.
        """
        if name in self._definitions:
            defn = self._definitions[name]
            if audience is not None and not _can_access_skill(defn.meta.audience, audience):
                _audience_violation(name, defn.meta.audience, audience)
            return defn

        meta = self._metadata.get(name)
        if meta is None:
            raise KeyError(f"Skill '{name}' not found in registry")

        if audience is not None and not _can_access_skill(meta.audience, audience):
            _audience_violation(name, meta.audience, audience)

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

    def build_system_prompt(
        self,
        skill_names: list[str],
        locale: str = "en",
        *,
        audience: SkillAudience | None = None,
    ) -> str:
        """Activate each skill, concatenate instructions with headers.

        When *locale* is not ``"en"``, the registry looks for a locale-specific
        ``SKILL.{locale}.md`` file alongside the canonical ``SKILL.md``.  If
        found, its body replaces the default English instructions.

        If *audience* is provided, platform-audience skills are omitted for
        tenant callers by the same activation guard used elsewhere.
        """
        sections: list[str] = []
        for name in skill_names:
            try:
                defn = self.activate(name, audience=audience)
                locale_body = self._load_locale_body(name, locale)
                body = locale_body or defn.instructions
                sections.append(f"## Skill: {defn.meta.name}\n\n{body}")
            except (KeyError, Exception):
                logger.warning("Could not activate skill '%s' for prompt", name)
        return "\n\n---\n\n".join(sections)

    def _load_locale_body(self, skill_id: str, locale: str) -> str | None:
        """Load ``SKILL.{locale}.md`` if it exists alongside ``SKILL.md``.

        Returns only the markdown body (after YAML frontmatter), or ``None``
        when no locale-specific file is available.
        """
        if locale == "en":
            return None
        for skills_dir in (self._skills_dir, self._community_skills_dir):
            locale_path = skills_dir / skill_id / f"SKILL.{locale}.md"
            if locale_path.exists():
                try:
                    content = locale_path.read_text(encoding="utf-8")
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            return parts[2].strip()
                except OSError:
                    logger.warning("Failed to read locale file %s", locale_path)
        return None

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
        community_names = [n for n, m in self._metadata.items() if m.tier == SkillTier.COMMUNITY]
        for name in community_names:
            del self._metadata[name]
            self._definitions.pop(name, None)
            self._skill_source.pop(name, None)


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Return (or create) the global SkillRegistry singleton."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        community_enabled = os.getenv("AUTOSWARM_COMMUNITY_SKILLS_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        _registry = SkillRegistry(community_enabled=community_enabled)
    return _registry
