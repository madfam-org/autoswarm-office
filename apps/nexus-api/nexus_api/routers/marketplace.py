"""Skill Marketplace REST API: publish, browse, rate, and install community skills."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from selva_skills import get_skill_registry, parse_skill_md_string

from ..auth import get_current_user, require_non_guest
from ..database import get_db
from ..models import SkillMarketplaceEntry, SkillRating
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["marketplace"], dependencies=[Depends(get_current_user)])  # noqa: B008

# Resolve community-skills directory relative to the selva_skills package.
_COMMUNITY_SKILLS_DIR = (
    Path(__file__).resolve().parents[4] / "packages" / "skills" / "community-skills"
)


# -- Request / Response schemas ------------------------------------------------


class PublishSkillRequest(BaseModel):
    """Request body for publishing a new skill to the marketplace."""

    name: str = Field(..., max_length=200)
    description: str
    yaml_content: str
    readme: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class RateSkillRequest(BaseModel):
    """Request body for rating a marketplace skill."""

    rating: int = Field(..., ge=1, le=5)
    review: str | None = None


class SkillRatingResponse(BaseModel):
    """Public representation of a skill rating."""

    id: str
    user_id: str
    rating: int
    review: str | None
    created_at: str

    model_config = {"from_attributes": True}


class MarketplaceEntryResponse(BaseModel):
    """Public representation of a marketplace skill entry."""

    id: str
    name: str
    description: str
    author: str
    version: str
    readme: str | None
    download_url: str | None
    category: str | None
    tags: list[str]
    downloads: int
    avg_rating: float | None
    rating_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MarketplaceEntryDetailResponse(MarketplaceEntryResponse):
    """Detailed representation including individual ratings."""

    yaml_content: str
    ratings: list[SkillRatingResponse]


class MarketplaceListResponse(BaseModel):
    """Paginated list of marketplace entries."""

    entries: list[MarketplaceEntryResponse]
    total: int
    limit: int
    offset: int


class InstallResponse(BaseModel):
    """Response after installing a skill from the marketplace."""

    installed: bool = True
    skill_name: str
    install_path: str


class DeleteResponse(BaseModel):
    """Response after unpublishing a skill."""

    deleted: bool = True


# -- Helpers -------------------------------------------------------------------


def _compute_avg_rating(ratings: list[SkillRating]) -> float | None:
    """Compute average rating from a list of SkillRating objects."""
    if not ratings:
        return None
    return round(sum(r.rating for r in ratings) / len(ratings), 2)


def _entry_to_response(entry: SkillMarketplaceEntry) -> MarketplaceEntryResponse:
    """Convert an ORM entry to a response schema."""
    return MarketplaceEntryResponse(
        id=str(entry.id),
        name=entry.name,
        description=entry.description,
        author=entry.author,
        version=entry.version,
        readme=entry.readme,
        download_url=entry.download_url,
        category=entry.category,
        tags=entry.tags or [],
        downloads=entry.downloads,
        avg_rating=_compute_avg_rating(entry.ratings),
        rating_count=len(entry.ratings),
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
    )


# -- Endpoints -----------------------------------------------------------------


@router.get("/skills", response_model=MarketplaceListResponse)
async def list_marketplace_skills(
    search: str | None = None,
    category: str | None = None,
    sort_by: str | None = None,
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> MarketplaceListResponse:
    """List marketplace skill entries with pagination, search, category filter, and sorting."""
    base_stmt = select(SkillMarketplaceEntry).where(SkillMarketplaceEntry.org_id == tenant.org_id)

    if search:
        pattern = f"%{search}%"
        base_stmt = base_stmt.where(
            SkillMarketplaceEntry.name.ilike(pattern)
            | SkillMarketplaceEntry.description.ilike(pattern)
        )

    if category:
        base_stmt = base_stmt.where(SkillMarketplaceEntry.category == category)

    # Total count (before sorting joins that may affect count)
    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    if sort_by == "downloads":
        base_stmt = base_stmt.order_by(SkillMarketplaceEntry.downloads.desc())
    elif sort_by == "newest":
        base_stmt = base_stmt.order_by(SkillMarketplaceEntry.created_at.desc())
    elif sort_by == "rating":
        # Sub-query for average rating to order by
        avg_sub = (
            select(
                SkillRating.entry_id,
                func.coalesce(func.avg(SkillRating.rating), 0).label("avg_r"),
            )
            .group_by(SkillRating.entry_id)
            .subquery()
        )
        base_stmt = base_stmt.outerjoin(
            avg_sub,
            SkillMarketplaceEntry.id == avg_sub.c.entry_id,
        ).order_by(avg_sub.c.avg_r.desc())
    else:
        base_stmt = base_stmt.order_by(SkillMarketplaceEntry.created_at.desc())

    # Paginated results
    result = await db.execute(base_stmt.limit(limit).offset(offset))
    rows = result.scalars().all()

    entries = [_entry_to_response(e) for e in rows]
    return MarketplaceListResponse(entries=entries, total=total, limit=limit, offset=offset)


@router.get("/skills/{entry_id}", response_model=MarketplaceEntryDetailResponse)
async def get_marketplace_skill(
    entry_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> MarketplaceEntryDetailResponse:
    """Get a single marketplace entry with full details including ratings."""
    stmt = (
        select(SkillMarketplaceEntry)
        .where(SkillMarketplaceEntry.id == uuid.UUID(entry_id))
        .where(SkillMarketplaceEntry.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace entry not found"
        )

    return MarketplaceEntryDetailResponse(
        id=str(entry.id),
        name=entry.name,
        description=entry.description,
        author=entry.author,
        version=entry.version,
        yaml_content=entry.yaml_content,
        readme=entry.readme,
        download_url=entry.download_url,
        category=entry.category,
        tags=entry.tags or [],
        downloads=entry.downloads,
        avg_rating=_compute_avg_rating(entry.ratings),
        rating_count=len(entry.ratings),
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
        ratings=[
            SkillRatingResponse(
                id=str(r.id),
                user_id=r.user_id,
                rating=r.rating,
                review=r.review,
                created_at=r.created_at.isoformat(),
            )
            for r in entry.ratings
        ],
    )


@router.post(
    "/skills",
    response_model=MarketplaceEntryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def publish_skill(
    body: PublishSkillRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> MarketplaceEntryResponse:
    """Publish a new skill to the marketplace.

    The ``yaml_content`` field must contain valid SKILL.md content with
    YAML frontmatter delimited by ``---`` fences.
    """
    # Validate YAML content is parseable.
    # NOTE: ``parse_skill_md_string`` can raise ``yaml.YAMLError`` (not a
    # ``ValueError`` subclass) on malformed YAML, and ``pydantic.ValidationError``
    # (which IS a ``ValueError`` subclass) on schema mismatch. ``Exception`` is
    # the smallest common ancestor that catches both.
    try:
        parse_skill_md_string(body.yaml_content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid YAML skill content: {exc}",
        ) from exc

    entry = SkillMarketplaceEntry(
        name=body.name,
        description=body.description,
        author=user.get("email", "unknown"),
        yaml_content=body.yaml_content,
        readme=body.readme,
        category=body.category,
        tags=body.tags,
        org_id=tenant.org_id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)

    return _entry_to_response(entry)


@router.post(
    "/skills/{entry_id}/rate",
    response_model=SkillRatingResponse,
    dependencies=[Depends(require_non_guest)],
)
async def rate_skill(
    entry_id: str,
    body: RateSkillRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> SkillRatingResponse:
    """Rate a marketplace skill. Upserts if the user already rated this entry."""
    # Verify entry exists
    entry_stmt = (
        select(SkillMarketplaceEntry)
        .where(SkillMarketplaceEntry.id == uuid.UUID(entry_id))
        .where(SkillMarketplaceEntry.org_id == tenant.org_id)
    )
    entry_result = await db.execute(entry_stmt)
    if not entry_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace entry not found"
        )

    user_id = user.get("sub", "unknown")

    # Check for existing rating by this user
    existing_stmt = (
        select(SkillRating)
        .where(SkillRating.entry_id == uuid.UUID(entry_id))
        .where(SkillRating.user_id == user_id)
    )
    existing_result = await db.execute(existing_stmt)
    existing_rating = existing_result.scalar_one_or_none()

    if existing_rating:
        existing_rating.rating = body.rating
        existing_rating.review = body.review
        await db.flush()
        await db.refresh(existing_rating)
        rating_obj = existing_rating
    else:
        rating_obj = SkillRating(
            entry_id=uuid.UUID(entry_id),
            user_id=user_id,
            rating=body.rating,
            review=body.review,
            org_id=tenant.org_id,
        )
        db.add(rating_obj)
        await db.flush()
        await db.refresh(rating_obj)

    return SkillRatingResponse(
        id=str(rating_obj.id),
        user_id=rating_obj.user_id,
        rating=rating_obj.rating,
        review=rating_obj.review,
        created_at=rating_obj.created_at.isoformat(),
    )


@router.post(
    "/skills/{entry_id}/install",
    response_model=InstallResponse,
    dependencies=[Depends(require_non_guest)],
)
async def install_skill(
    entry_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> InstallResponse:
    """Install a marketplace skill into the community-skills directory.

    Writes the YAML content as ``SKILL.md`` into
    ``packages/skills/community-skills/{name}/`` and increments the download
    counter.  After writing, the skill registry is refreshed so the new skill
    becomes discoverable immediately.
    """
    stmt = (
        select(SkillMarketplaceEntry)
        .where(SkillMarketplaceEntry.id == uuid.UUID(entry_id))
        .where(SkillMarketplaceEntry.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace entry not found"
        )

    # Parse the YAML to extract the skill name for the directory.
    # NOTE: see publish() for the rationale on the broad ``except Exception``
    # — ``parse_skill_md_string`` raises ``yaml.YAMLError`` (not a
    # ``ValueError`` subclass) plus ``pydantic.ValidationError``.
    try:
        meta, _ = parse_skill_md_string(entry.yaml_content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Stored YAML content is invalid: {exc}",
        ) from exc

    skill_dir = _COMMUNITY_SKILLS_DIR / meta.name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(entry.yaml_content, encoding="utf-8")

    # Increment download count
    entry.downloads = (entry.downloads or 0) + 1
    await db.flush()

    # Refresh registry to pick up the newly installed skill
    try:
        registry = get_skill_registry()
        registry.refresh()
    except Exception:
        logger.warning("Failed to refresh skill registry after install", exc_info=True)

    return InstallResponse(
        skill_name=meta.name,
        install_path=str(skill_md_path),
    )


@router.delete("/skills/{entry_id}", response_model=DeleteResponse)
async def unpublish_skill(
    entry_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> DeleteResponse:
    """Unpublish a marketplace skill. Only the original author may delete."""
    stmt = (
        select(SkillMarketplaceEntry)
        .where(SkillMarketplaceEntry.id == uuid.UUID(entry_id))
        .where(SkillMarketplaceEntry.org_id == tenant.org_id)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace entry not found"
        )

    user_email = user.get("email", "")
    if entry.author != user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the skill author may unpublish",
        )

    await db.delete(entry)
    await db.flush()
    return DeleteResponse()
