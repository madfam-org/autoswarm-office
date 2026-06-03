"""
Track D1: Skills Hub REST router
Exposes agentskills.io browse/search/install endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from selva_skills.hub import SkillsHubClient

from ..auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/skills/hub",
    tags=["Skills Hub"],
    dependencies=[Depends(get_current_user)],
)


class HubSkillResponse(BaseModel):
    name: str
    description: str
    author: str
    version: str
    category: str
    downloads: int
    url: str
    tags: list[str]


class InstallRequest(BaseModel):
    skill_name: str
    target_dir: str | None = None


@router.get("/", response_model=list[HubSkillResponse])
async def browse_hub(category: str | None = None, page: int = 1) -> list[HubSkillResponse]:
    """Browse community skills on agentskills.io."""
    client = SkillsHubClient()
    skills = await client.browse(category=category, page=page)
    return [HubSkillResponse(**s.__dict__) for s in skills]


@router.get("/search", response_model=list[HubSkillResponse])
async def search_hub(q: str) -> list[HubSkillResponse]:
    """Full-text search the agentskills.io hub."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="Search query cannot be empty")
    client = SkillsHubClient()
    skills = await client.search(q)
    return [HubSkillResponse(**s.__dict__) for s in skills]


@router.post("/install", status_code=status.HTTP_201_CREATED)
async def install_skill(body: InstallRequest) -> dict:
    """Download and install a skill from agentskills.io."""
    import os

    target_dir = body.target_dir or os.environ.get(
        "SELVA_SKILLS_DIR",
        "/var/lib/selva/skills",
    )
    client = SkillsHubClient()
    try:
        path = await client.install(body.skill_name, target_dir)
        return {"status": "installed", "skill": body.skill_name, "path": str(path)}
    except Exception as exc:
        logger.error("Skill install failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Install failed: {exc}",
        ) from exc
