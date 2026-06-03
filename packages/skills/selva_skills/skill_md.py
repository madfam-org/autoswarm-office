"""
Gap 4: SKILL.md — Progressive Disclosure Format

Defines the SkillDocument dataclass and SkillMDRegistry, which extends
the existing SkillRegistry to also scan for SKILL.md directory-based skills
and exposes the 3-level progressive disclosure API used by Hermes Agent:

  Level 0: list_skills_compact()  → [{name, description, category}]  ~3k tokens
  Level 1: get_skill_full(name)   → full SKILL.md content
  Level 2: get_skill_reference(name, ref_path) → specific reference file
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FRONTMATTER_SEP = "---"


@dataclass
class SkillDocument:
    """Parsed representation of a SKILL.md skill."""

    name: str
    description: str
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    category: str = "general"
    platforms: list[str] = field(default_factory=list)
    requires_toolsets: list[str] = field(default_factory=list)
    fallback_for_toolsets: list[str] = field(default_factory=list)
    raw_content: str = ""
    skill_dir: Path | None = None

    @property
    def compact(self) -> dict[str, str]:
        """Level-0 representation — name, description, category only."""
        return {"name": self.name, "description": self.description, "category": self.category}


def _parse_skill_md(path: Path) -> SkillDocument | None:
    """Parse a SKILL.md file, extracting YAML frontmatter metadata."""
    try:
        import yaml
    except ImportError:
        yaml = None

    raw = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}

    # Extract YAML frontmatter if present
    if raw.startswith(_FRONTMATTER_SEP):
        parts = raw.split(_FRONTMATTER_SEP, 2)
        if len(parts) >= 3:
            frontmatter_str = parts[1].strip()
            try:
                meta = yaml.safe_load(frontmatter_str) if yaml else {}
            except Exception:
                meta = {}
            raw = parts[2].strip()

    hermes_meta: dict = (meta.get("metadata") or {}).get("hermes") or {}

    return SkillDocument(
        name=meta.get("name", path.parent.name),
        description=meta.get("description", ""),
        version=meta.get("version", "1.0.0"),
        tags=meta.get("tags") or hermes_meta.get("tags") or [],
        category=hermes_meta.get("category", "general"),
        platforms=meta.get("platforms") or [],
        requires_toolsets=hermes_meta.get("requires_toolsets") or [],
        fallback_for_toolsets=hermes_meta.get("fallback_for_toolsets") or [],
        raw_content=raw,
        skill_dir=path.parent,
    )


class SkillMDRegistry:
    """
    Skills registry supporting both .py skills (existing) and SKILL.md
    directory-based skills, with 3-level progressive disclosure.
    """

    def __init__(self, skills_dir: str | None = None) -> None:
        import os

        self._skills_dir = Path(
            skills_dir or os.environ.get("SELVA_SKILLS_DIR", "/var/lib/selva/skills")
        )
        self._md_skills: dict[str, SkillDocument] = {}

    def load_md_skills(self) -> None:
        """Scan skills_dir for SKILL.md files and load them."""
        if not self._skills_dir.exists():
            logger.debug("SkillMDRegistry: directory %s does not exist.", self._skills_dir)
            return

        for skill_md in self._skills_dir.rglob("SKILL.md"):
            doc = _parse_skill_md(skill_md)
            if doc:
                logger.info("SkillMDRegistry: loaded %s (category=%s)", doc.name, doc.category)
                self._md_skills[doc.name] = doc

    # ------------------------------------------------------------------
    # Progressive disclosure API
    # ------------------------------------------------------------------

    def list_skills_compact(self) -> list[dict[str, str]]:
        """
        Level 0 — returns [{name, description, category}] for all loaded skills.
        Approximately 3k tokens for a typical skill set.
        """
        return [doc.compact for doc in self._md_skills.values()]

    def get_skill_full(self, name: str) -> str | None:
        """Level 1 — returns the full SKILL.md content for *name*."""
        doc = self._md_skills.get(name)
        if not doc:
            return None
        return doc.raw_content

    def get_skill_reference(self, name: str, ref_path: str) -> str | None:
        """Level 2 — returns the content of a reference file inside the skill directory."""
        doc = self._md_skills.get(name)
        if not doc or not doc.skill_dir:
            return None
        full_path = doc.skill_dir / "references" / ref_path
        if not full_path.exists() or not full_path.is_file():
            logger.warning("SkillMDRegistry: reference %s not found for skill %s.", ref_path, name)
            return None
        return full_path.read_text(encoding="utf-8", errors="replace")

    def get_all_md_skills(self) -> dict[str, SkillDocument]:
        return dict(self._md_skills)
