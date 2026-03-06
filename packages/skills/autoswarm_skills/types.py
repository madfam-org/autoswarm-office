"""Core types for AgentSkills-standard skill definitions."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class SkillTier(StrEnum):
    """Classification tier for skills."""

    CORE = "core"
    COMMUNITY = "community"


class SkillMetadata(BaseModel):
    """Lightweight metadata from SKILL.md YAML frontmatter (~100 tokens)."""

    name: str = Field(..., max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str = Field(..., max_length=1024)
    tier: SkillTier = SkillTier.CORE
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class SkillDefinition(BaseModel):
    """Full skill: metadata + markdown body (loaded on activation)."""

    meta: SkillMetadata
    instructions: str
    skill_dir: Path

    model_config = {"arbitrary_types_allowed": True}
