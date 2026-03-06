"""Skills listing and community-skills toggle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from autoswarm_skills import SkillTier, get_skill_registry

from ..auth import get_current_user

router = APIRouter(tags=["skills"], dependencies=[Depends(get_current_user)])


class SkillResponse(BaseModel):
    """Public representation of a skill."""

    name: str
    description: str
    tier: str
    allowed_tools: list[str]


@router.get("/", response_model=list[SkillResponse])
async def list_skills(tier: str | None = None) -> list[SkillResponse]:
    """Return all discovered skills, optionally filtered by tier."""
    registry = get_skill_registry()
    tier_filter = SkillTier(tier) if tier else None
    return [
        SkillResponse(
            name=m.name,
            description=m.description,
            tier=m.tier.value,
            allowed_tools=m.allowed_tools,
        )
        for m in registry.list_skills(tier=tier_filter)
    ]


@router.post("/community/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_community() -> None:
    """Enable community skills at runtime."""
    get_skill_registry().enable_community_skills()


@router.post("/community/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_community() -> None:
    """Disable community skills at runtime."""
    get_skill_registry().disable_community_skills()


@router.get("/community/status")
async def community_status() -> dict[str, bool]:
    """Return whether community skills are currently enabled."""
    return {"enabled": get_skill_registry().community_enabled}
