"""Tests for scheduled_actions enqueue API (Phase 2.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from nexus_api.models import ScheduledActionRow


@pytest.mark.asyncio
async def test_enqueue_social_post(client, auth_headers, db_session) -> None:
    scheduled_for = datetime.now(UTC) + timedelta(hours=1)
    payload = {
        "action_type": "social_post",
        "scheduled_for": scheduled_for.isoformat(),
        "payload": {
            "platform": "bluesky",
            "text": "Hello from Selva campaign lane",
        },
    }
    response = await client.post(
        "/api/v1/scheduled-actions/",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["payload"]["platform"] == "bluesky"

    result = await db_session.execute(select(ScheduledActionRow))
    row = result.scalar_one()
    assert row.org_id == "dev-org"
    assert row.action_type == "social_post"


@pytest.mark.asyncio
async def test_enqueue_rejects_missing_platform(client, auth_headers) -> None:
    response = await client.post(
        "/api/v1/scheduled-actions/",
        json={
            "action_type": "social_post",
            "scheduled_for": datetime.now(UTC).isoformat(),
            "payload": {"text": "no platform"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_campaign_schedule_social_with_hitl(client, auth_headers, db_session) -> None:
    when = datetime.now(UTC) + timedelta(minutes=30)
    response = await client.post(
        "/api/v1/campaigns/schedule-social",
        json={
            "sku_key": "avala__issuer",
            "platform": "reddit",
            "require_hitl": True,
            "posts": [
                {
                    "scheduled_for": when.isoformat(),
                    "payload": {
                        "subreddit": "test",
                        "title": "Campaign title",
                        "body": "Proof-backed copy only",
                    },
                }
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["count"] == 1
    assert body["created"][0]["playbook_id"] == "reddit_promo_v1"
    assert body["created"][0]["hitl_status"] == "pending"

    action_id = body["created"][0]["id"]
    approve = await client.patch(
        f"/api/v1/scheduled-actions/{action_id}/hitl",
        json={"decision": "approved"},
        headers=auth_headers,
    )
    assert approve.status_code == 200
    assert approve.json()["hitl_status"] == "approved"


@pytest.mark.asyncio
async def test_list_scheduled_actions(client, auth_headers) -> None:
    when = datetime.now(UTC) + timedelta(hours=2)
    await client.post(
        "/api/v1/scheduled-actions/",
        json={
            "action_type": "social_post",
            "scheduled_for": when.isoformat(),
            "payload": {"platform": "bluesky", "text": "listed post"},
        },
        headers=auth_headers,
    )
    listed = await client.get("/api/v1/scheduled-actions/", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
