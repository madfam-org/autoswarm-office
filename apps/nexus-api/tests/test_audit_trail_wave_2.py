"""Tests for Phase 3 audit-trail wave 2: workflows, marketplace, maps.

Each mutation endpoint that previously did not emit a TaskEvent now MUST
emit one. These tests pin (1) the exact ``event_type`` lands, (2) the
``org_id`` matches the caller's JWT, (3) no PII (email, name, phone)
leaks into the payload.

Mirrors the test pattern from ``test_stripe_webhook_handlers.py`` —
exercises the endpoints through the FastAPI client (CSRF + auth headers
included via fixtures), then asserts on rows in the ``task_events``
table directly.

Reference: ``docs/AUDIT_TRAIL_GAP_ANALYSIS.md`` and the canonical
emit-pattern in ``apps/nexus-api/nexus_api/routers/stripe_webhooks.py``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import Map, SkillMarketplaceEntry, TaskEvent, Workflow

# The dev-bypass auth dependency resolves the caller's org_id to this value
# (see ``nexus_api.auth.get_current_user`` and ``nexus_api.tenant.get_tenant``).
_CALLER_ORG_ID = "dev-org"

# Set of payload keys we MUST never leak. Mirrors the PII contract in the
# audit-trail gap analysis (events are returned by GET /api/v1/events to
# any caller in the same org).
_PII_KEYS = frozenset({"email", "name_email", "phone", "user_email", "author"})


# ---------------------------------------------------------------------------
# Test fixtures: minimal valid YAML / TMJ content
# ---------------------------------------------------------------------------


_VALID_WORKFLOW_YAML = """name: audit-trail-test-workflow
version: '1.0.0'
description: Minimal workflow for audit-trail tests

nodes:
  - id: only_node
    type: passthrough

edges: []
"""


_VALID_TMJ = """{
  "width": 4,
  "height": 4,
  "tilewidth": 32,
  "tileheight": 32,
  "layers": [
    {
      "id": 1,
      "name": "floor",
      "type": "tilelayer",
      "width": 4,
      "height": 4,
      "data": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
      "visible": true,
      "opacity": 1,
      "x": 0,
      "y": 0
    }
  ],
  "tilesets": [],
  "orientation": "orthogonal",
  "renderorder": "right-down",
  "type": "map",
  "version": "1.10"
}
"""


_VALID_SKILL_YAML = (
    "---\n"
    "name: audit-trail-test-skill\n"
    "description: Minimal skill for audit-trail tests.\n"
    "allowed_tools:\n"
    "  - file_read\n"
    "---\n\n"
    "# Audit-Trail Test Skill\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_event_types_for_org(db: AsyncSession, org_id: str) -> list[TaskEvent]:
    """Return all TaskEvent rows for ``org_id``, in insertion order."""
    result = await db.execute(
        select(TaskEvent).where(TaskEvent.org_id == org_id).order_by(TaskEvent.created_at)
    )
    return list(result.scalars().all())


def _assert_no_pii(payload: dict | None) -> None:
    """Pin the PII contract — no email / name-email / phone / author keys."""
    assert payload is not None, "event payload should not be None"
    for key in payload.keys():
        assert key.lower() not in _PII_KEYS, (
            f"PII key '{key}' leaked into event payload: {payload}"
        )
        # Also reject email-shaped values regardless of key name
        value = payload[key]
        if isinstance(value, str):
            assert "@" not in value or value.endswith(".local"), (
                f"Suspicious email-shaped value in payload[{key!r}]: {value!r}"
            )


# ===========================================================================
# Workflows
# ===========================================================================


@pytest.mark.asyncio()
async def test_create_workflow_emits_workflow_created(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/workflows → emits ``workflow.created``."""
    resp = await client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={
            "name": "wf-create",
            "description": "Created in test",
            "yaml_content": _VALID_WORKFLOW_YAML,
        },
    )
    assert resp.status_code == 201, resp.text
    workflow_id = resp.json()["id"]

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    matching = [e for e in events if e.event_type == "workflow.created"]
    assert len(matching) == 1, f"expected 1 workflow.created event, got {[e.event_type for e in events]}"
    event = matching[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.event_category == "workflow"
    assert event.payload is not None
    assert event.payload["workflow_id"] == workflow_id
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_update_workflow_emits_workflow_updated(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """PUT /api/v1/workflows/{id} → emits ``workflow.updated`` with fields list."""
    create_resp = await client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={"name": "wf-update", "yaml_content": _VALID_WORKFLOW_YAML},
    )
    assert create_resp.status_code == 201, create_resp.text
    workflow_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/workflows/{workflow_id}",
        headers=auth_headers,
        json={"name": "wf-update-renamed", "description": "new description"},
    )
    assert update_resp.status_code == 200, update_resp.text

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    update_events = [e for e in events if e.event_type == "workflow.updated"]
    assert len(update_events) == 1, f"got events={[e.event_type for e in events]}"
    event = update_events[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload is not None
    assert event.payload["workflow_id"] == workflow_id
    assert set(event.payload["fields_updated"]) == {"name", "description"}
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_delete_workflow_emits_workflow_deleted(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """DELETE /api/v1/workflows/{id} → emits ``workflow.deleted``."""
    create_resp = await client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={"name": "wf-delete", "yaml_content": _VALID_WORKFLOW_YAML},
    )
    workflow_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/workflows/{workflow_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204, del_resp.text

    # Confirm the workflow row is actually gone (sanity check)
    remaining = (
        await db_session.execute(select(Workflow).where(Workflow.name == "wf-delete"))
    ).scalar_one_or_none()
    assert remaining is None

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    delete_events = [e for e in events if e.event_type == "workflow.deleted"]
    assert len(delete_events) == 1, f"got events={[e.event_type for e in events]}"
    event = delete_events[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["workflow_id"] == workflow_id
    assert event.payload["name"] == "wf-delete"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_import_workflow_emits_workflow_imported(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/workflows/import → emits ``workflow.imported``."""
    resp = await client.post(
        "/api/v1/workflows/import",
        headers=auth_headers,
        json={"yaml_content": _VALID_WORKFLOW_YAML},
    )
    assert resp.status_code == 201, resp.text
    workflow_id = resp.json()["id"]

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    imported = [e for e in events if e.event_type == "workflow.imported"]
    assert len(imported) == 1
    event = imported[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["workflow_id"] == workflow_id
    _assert_no_pii(event.payload)


# ===========================================================================
# Marketplace
# ===========================================================================


@pytest.mark.asyncio()
async def test_publish_skill_emits_marketplace_published(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/marketplace/skills → emits ``marketplace.published``."""
    resp = await client.post(
        "/api/v1/marketplace/skills",
        headers=auth_headers,
        json={
            "name": "audit-trail-skill",
            "description": "Audit trail test",
            "yaml_content": _VALID_SKILL_YAML,
            "category": "testing",
            "tags": ["audit", "test"],
        },
    )
    assert resp.status_code == 201, resp.text
    entry_id = resp.json()["id"]

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    published = [e for e in events if e.event_type == "marketplace.published"]
    assert len(published) == 1
    event = published[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.event_category == "marketplace"
    assert event.payload["entry_id"] == entry_id
    assert event.payload["name"] == "audit-trail-skill"
    assert event.payload["category"] == "testing"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_install_skill_emits_marketplace_installed(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/v1/marketplace/skills/{id}/install → emits ``marketplace.installed``."""
    # Seed a marketplace entry directly so the install endpoint has a target.
    entry = SkillMarketplaceEntry(
        name="install-target",
        description="for install test",
        author="dev@autoswarm.local",
        yaml_content=_VALID_SKILL_YAML,
        org_id=_CALLER_ORG_ID,
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    monkeypatch.setattr(
        "nexus_api.routers.marketplace._COMMUNITY_SKILLS_DIR", tmp_path
    )

    resp = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/install", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    installed = [e for e in events if e.event_type == "marketplace.installed"]
    assert len(installed) == 1
    event = installed[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["entry_id"] == str(entry.id)
    assert event.payload["skill_name"] == "audit-trail-test-skill"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_rate_skill_emits_marketplace_rated(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/marketplace/skills/{id}/rate → emits ``marketplace.rated``.

    The review free-text MUST NOT appear in the event payload (PII risk).
    """
    entry = SkillMarketplaceEntry(
        name="rate-target",
        description="for rate test",
        author="dev@autoswarm.local",
        yaml_content=_VALID_SKILL_YAML,
        org_id=_CALLER_ORG_ID,
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    resp = await client.post(
        f"/api/v1/marketplace/skills/{entry.id}/rate",
        headers=auth_headers,
        json={"rating": 5, "review": "Reviewer dropped their phone +1-555-0100 here"},
    )
    assert resp.status_code == 200, resp.text

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    rated = [e for e in events if e.event_type == "marketplace.rated"]
    assert len(rated) == 1
    event = rated[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["entry_id"] == str(entry.id)
    assert event.payload["rating"] == 5
    assert event.payload["is_update"] is False
    # Critical: review free-text must NOT be in the payload.
    assert "review" not in event.payload
    assert "555" not in str(event.payload), "phone-shaped digits leaked into payload"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_unpublish_skill_emits_marketplace_deleted(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """DELETE /api/v1/marketplace/skills/{id} → emits ``marketplace.deleted``."""
    # Author must match the dev-bypass user's email for delete to be allowed.
    entry = SkillMarketplaceEntry(
        name="delete-target",
        description="for delete test",
        author="dev@autoswarm.local",
        yaml_content=_VALID_SKILL_YAML,
        org_id=_CALLER_ORG_ID,
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    entry_id = str(entry.id)

    resp = await client.delete(
        f"/api/v1/marketplace/skills/{entry_id}", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    deleted = [e for e in events if e.event_type == "marketplace.deleted"]
    assert len(deleted) == 1
    event = deleted[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["entry_id"] == entry_id
    assert event.payload["name"] == "delete-target"
    # The entry's ``author`` field is dev@autoswarm.local — the event
    # payload MUST NOT carry that PII.
    assert "author" not in event.payload
    _assert_no_pii(event.payload)


# ===========================================================================
# Maps
# ===========================================================================


@pytest.mark.asyncio()
async def test_create_map_emits_map_created(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/maps → emits ``map.created``."""
    resp = await client.post(
        "/api/v1/maps",
        headers=auth_headers,
        json={
            "name": "map-create",
            "description": "map for audit-trail test",
            "tmj_content": _VALID_TMJ,
        },
    )
    assert resp.status_code == 201, resp.text
    map_id = resp.json()["id"]

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    created = [e for e in events if e.event_type == "map.created"]
    assert len(created) == 1
    event = created[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.event_category == "map"
    assert event.payload["map_id"] == map_id
    assert event.payload["name"] == "map-create"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_update_map_emits_map_updated(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """PUT /api/v1/maps/{id} → emits ``map.updated`` with fields_updated list."""
    create_resp = await client.post(
        "/api/v1/maps",
        headers=auth_headers,
        json={"name": "map-update", "tmj_content": _VALID_TMJ},
    )
    assert create_resp.status_code == 201, create_resp.text
    map_id = create_resp.json()["id"]

    upd_resp = await client.put(
        f"/api/v1/maps/{map_id}",
        headers=auth_headers,
        json={"name": "map-update-renamed"},
    )
    assert upd_resp.status_code == 200, upd_resp.text

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    updated = [e for e in events if e.event_type == "map.updated"]
    assert len(updated) == 1
    event = updated[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["map_id"] == map_id
    assert event.payload["fields_updated"] == ["name"]
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_delete_map_emits_map_deleted(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """DELETE /api/v1/maps/{id} → emits ``map.deleted``."""
    create_resp = await client.post(
        "/api/v1/maps",
        headers=auth_headers,
        json={"name": "map-delete", "tmj_content": _VALID_TMJ},
    )
    map_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/maps/{map_id}", headers=auth_headers)
    assert del_resp.status_code == 204, del_resp.text

    # Confirm row gone
    remaining = (
        await db_session.execute(select(Map).where(Map.name == "map-delete"))
    ).scalar_one_or_none()
    assert remaining is None

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    deleted = [e for e in events if e.event_type == "map.deleted"]
    assert len(deleted) == 1
    event = deleted[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["map_id"] == map_id
    assert event.payload["name"] == "map-delete"
    _assert_no_pii(event.payload)


@pytest.mark.asyncio()
async def test_import_map_emits_map_imported(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST /api/v1/maps/import → emits ``map.imported``."""
    resp = await client.post(
        "/api/v1/maps/import",
        headers=auth_headers,
        json={"tmj_content": _VALID_TMJ},
    )
    assert resp.status_code == 201, resp.text
    map_id = resp.json()["id"]

    events = await _fetch_event_types_for_org(db_session, _CALLER_ORG_ID)
    imported = [e for e in events if e.event_type == "map.imported"]
    assert len(imported) == 1
    event = imported[0]
    assert event.org_id == _CALLER_ORG_ID
    assert event.payload["map_id"] == map_id
    _assert_no_pii(event.payload)
