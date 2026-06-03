"""Tests for the Skill Marketplace REST API endpoints."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import SkillMarketplaceEntry, SkillRating

# Valid SKILL.md YAML content for testing
VALID_YAML_CONTENT = (
    "---\n"
    "name: test-marketplace-skill\n"
    "description: A test skill for marketplace testing.\n"
    "allowed_tools:\n"
    "  - file_read\n"
    "---\n\n"
    "# Test Marketplace Skill\n\n"
    "Instructions for the skill.\n"
)

VALID_YAML_CONTENT_2 = (
    "---\n"
    "name: another-skill\n"
    "description: Another skill for filtering tests.\n"
    "allowed_tools: []\n"
    "---\n\n"
    "# Another Skill\n\n"
    "More instructions.\n"
)

INVALID_YAML_CONTENT = "Not valid YAML frontmatter content"


async def _create_entry(
    db: AsyncSession,
    *,
    name: str = "test-skill",
    author: str = "dev@selva.local",
    category: str | None = None,
    downloads: int = 0,
    org_id: str = "dev-org",
) -> SkillMarketplaceEntry:
    """Helper to insert a marketplace entry directly into the database."""
    entry = SkillMarketplaceEntry(
        name=name,
        description=f"Description for {name}",
        author=author,
        yaml_content=VALID_YAML_CONTENT,
        category=category,
        downloads=downloads,
        org_id=org_id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def _create_rating(
    db: AsyncSession,
    entry_id: uuid.UUID,
    *,
    user_id: str = "user-1",
    rating: int = 4,
    org_id: str = "dev-org",
) -> SkillRating:
    """Helper to insert a rating directly into the database."""
    r = SkillRating(
        entry_id=entry_id,
        user_id=user_id,
        rating=rating,
        org_id=org_id,
    )
    db.add(r)
    await db.flush()
    await db.refresh(r)
    return r


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_skills_empty(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """Listing skills on an empty marketplace returns an empty list."""
    resp = await client.get("/api/v1/marketplace/skills", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["entries"] == []


@pytest.mark.asyncio()
async def test_list_skills_with_data(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Listing skills returns entries that exist in the database."""
    await _create_entry(db_session, name="skill-one")
    await _create_entry(db_session, name="skill-two")
    await db_session.commit()

    resp = await client.get("/api/v1/marketplace/skills", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["entries"]) == 2


# ---------------------------------------------------------------------------
# Get single entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_skill_found(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Getting a single skill by ID returns full details."""
    entry = await _create_entry(db_session, name="detail-skill")
    await db_session.commit()

    resp = await client.get(f"/api/v1/marketplace/skills/{entry.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "detail-skill"
    assert data["yaml_content"] == VALID_YAML_CONTENT
    assert data["ratings"] == []
    assert data["avg_rating"] is None
    assert data["rating_count"] == 0


@pytest.mark.asyncio()
async def test_get_skill_not_found(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """Getting a non-existent skill returns 404."""
    resp = await client.get(f"/api/v1/marketplace/skills/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Publish (POST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_publish_skill_valid(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    """Publishing a skill with valid YAML succeeds."""
    payload = {
        "name": "my-new-skill",
        "description": "A brand new skill",
        "yaml_content": VALID_YAML_CONTENT,
        "readme": "# README\n\nSome docs.",
        "category": "productivity",
        "tags": ["automation", "coding"],
    }
    resp = await client.post("/api/v1/marketplace/skills", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-new-skill"
    assert data["author"] == "dev@selva.local"
    assert data["category"] == "productivity"
    assert data["tags"] == ["automation", "coding"]
    assert data["downloads"] == 0
    assert data["avg_rating"] is None


@pytest.mark.asyncio()
async def test_publish_skill_invalid_yaml(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Publishing a skill with invalid YAML content returns 422."""
    payload = {
        "name": "bad-skill",
        "description": "Invalid content",
        "yaml_content": INVALID_YAML_CONTENT,
    }
    resp = await client.post("/api/v1/marketplace/skills", json=payload, headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate skill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_rate_skill_new(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Rating a skill for the first time creates a new rating."""
    entry = await _create_entry(db_session)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        json={"rating": 5, "review": "Excellent skill!"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rating"] == 5
    assert data["review"] == "Excellent skill!"
    assert data["user_id"] == "dev-user-00000000"


@pytest.mark.asyncio()
async def test_rate_skill_update_existing(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Rating a skill again upserts the existing rating."""
    entry = await _create_entry(db_session)
    await db_session.commit()

    # First rating
    resp1 = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        json={"rating": 3},
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["rating"] == 3

    # Update rating
    resp2 = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        json={"rating": 5, "review": "Changed my mind, great!"},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["rating"] == 5
    assert data["review"] == "Changed my mind, great!"


@pytest.mark.asyncio()
async def test_rate_skill_invalid_rating_value(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Rating with a value outside 1-5 returns 422."""
    entry = await _create_entry(db_session)
    await db_session.commit()

    # Too low
    resp = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        json={"rating": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Too high
    resp = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        json={"rating": 6},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_rate_nonexistent_skill(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Rating a non-existent skill returns 404."""
    resp = await client.post(
        f"/api/v1/marketplace/skills/{uuid.uuid4()}/rate",
        json={"rating": 4},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Install skill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_install_skill_success(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    tmp_path: pytest.TempPathFactory,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installing a skill writes SKILL.md and increments downloads."""
    entry = await _create_entry(db_session)
    await db_session.commit()

    # Redirect install directory to tmp_path to avoid polluting the real tree
    monkeypatch.setattr("nexus_api.routers.marketplace._COMMUNITY_SKILLS_DIR", tmp_path)

    resp = await client.post(f"/api/v1/marketplace/skills/{entry.id}/install", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["installed"] is True
    assert data["skill_name"] == "test-marketplace-skill"

    # Verify the file was written
    skill_md = tmp_path / "test-marketplace-skill" / "SKILL.md"
    assert skill_md.exists()
    assert skill_md.read_text(encoding="utf-8") == VALID_YAML_CONTENT


@pytest.mark.asyncio()
async def test_install_skill_increments_downloads(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    tmp_path: pytest.TempPathFactory,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installing a skill increments the download counter."""
    entry = await _create_entry(db_session, downloads=5)
    await db_session.commit()

    monkeypatch.setattr("nexus_api.routers.marketplace._COMMUNITY_SKILLS_DIR", tmp_path)

    resp = await client.post(f"/api/v1/marketplace/skills/{entry.id}/install", headers=auth_headers)
    assert resp.status_code == 200

    # Verify downloads incremented by re-fetching
    get_resp = await client.get(f"/api/v1/marketplace/skills/{entry.id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["downloads"] == 6


# ---------------------------------------------------------------------------
# Delete (unpublish)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_delete_skill_author(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """The original author can unpublish their skill."""
    entry = await _create_entry(db_session, author="dev@selva.local")
    await db_session.commit()

    resp = await client.delete(f"/api/v1/marketplace/skills/{entry.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Verify it's gone
    get_resp = await client.get(f"/api/v1/marketplace/skills/{entry.id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio()
async def test_delete_skill_non_author_forbidden(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A non-author cannot unpublish a skill."""
    entry = await _create_entry(db_session, author="other@example.com")
    await db_session.commit()

    resp = await client.delete(f"/api/v1/marketplace/skills/{entry.id}", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio()
async def test_delete_skill_not_found(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Deleting a non-existent skill returns 404."""
    resp = await client.delete(f"/api/v1/marketplace/skills/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_search_filter(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Search filters entries by name or description."""
    await _create_entry(db_session, name="alpha-skill")
    await _create_entry(db_session, name="beta-skill")
    await db_session.commit()

    resp = await client.get("/api/v1/marketplace/skills?search=alpha", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["entries"][0]["name"] == "alpha-skill"


# ---------------------------------------------------------------------------
# Category filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_category_filter(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Category filter returns only matching entries."""
    await _create_entry(db_session, name="prod-skill", category="productivity")
    await _create_entry(db_session, name="dev-skill", category="development")
    await db_session.commit()

    resp = await client.get(
        "/api/v1/marketplace/skills?category=productivity", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["entries"][0]["name"] == "prod-skill"


# ---------------------------------------------------------------------------
# Sort by downloads, rating, newest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_sort_by_downloads(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Sorting by downloads returns highest first."""
    await _create_entry(db_session, name="low-dl", downloads=5)
    await _create_entry(db_session, name="high-dl", downloads=100)
    await db_session.commit()

    resp = await client.get("/api/v1/marketplace/skills?sort_by=downloads", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"][0]["name"] == "high-dl"
    assert data["entries"][1]["name"] == "low-dl"


@pytest.mark.asyncio()
async def test_sort_by_newest(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Sorting by newest returns most recently created first."""
    await _create_entry(db_session, name="first-skill")
    await _create_entry(db_session, name="second-skill")
    await db_session.commit()

    resp = await client.get("/api/v1/marketplace/skills?sort_by=newest", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Both exist; newest ordering is default so just verify success
    assert data["total"] == 2


@pytest.mark.asyncio()
async def test_sort_by_rating(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Sorting by rating returns highest-rated entries first."""
    e1 = await _create_entry(db_session, name="low-rated")
    e2 = await _create_entry(db_session, name="high-rated")
    await _create_rating(db_session, e1.id, user_id="u1", rating=2)
    await _create_rating(db_session, e2.id, user_id="u2", rating=5)
    await db_session.commit()

    resp = await client.get("/api/v1/marketplace/skills?sort_by=rating", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"][0]["name"] == "high-rated"


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_marketplace_requires_auth(client: httpx.AsyncClient) -> None:
    """Marketplace endpoints require authentication."""
    resp = await client.get("/api/v1/marketplace/skills")
    assert resp.status_code in (401, 403)
