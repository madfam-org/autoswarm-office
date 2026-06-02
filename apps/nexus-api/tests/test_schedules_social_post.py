"""Validation tests for SOCIAL_POST schedules → materializer contract."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from nexus_api.services.scheduled_actions import prepare_social_post_schedule_payload


class TestPrepareSocialPostSchedulePayload:
    def test_injects_org_id_when_missing(self) -> None:
        payload = prepare_social_post_schedule_payload(
            {
                "platform": "reddit",
                "subreddit": "selva",
                "title": "Hello",
                "body": "Proof-backed copy",
            },
            org_id="org-abc",
        )
        assert payload["org_id"] == "org-abc"
        assert payload["platform"] == "reddit"

    def test_rejects_missing_platform(self) -> None:
        with pytest.raises(HTTPException) as exc:
            prepare_social_post_schedule_payload({"org_id": "org-abc"}, org_id="org-abc")
        assert exc.value.status_code == 422

    def test_rejects_incomplete_reddit_payload(self) -> None:
        with pytest.raises(HTTPException) as exc:
            prepare_social_post_schedule_payload(
                {"platform": "reddit", "subreddit": "selva"},
                org_id="org-abc",
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_schedule_injects_org_for_social_post(db_session) -> None:
    from sqlalchemy import select

    from nexus_api.models import Schedule
    from nexus_api.routers.schedules import ScheduleCreate, create_schedule

    body = ScheduleCreate(
        cron_expr="0 9 * * 1",
        action="social_post",
        payload={
            "platform": "bluesky",
            "text": "Campaign post from schedule",
        },
        description="weekly promo",
    )
    user = {
        "sub": "user-schedule-social",
        "roles": ["tactician"],
        "org_id": "dev-org",
        "email": "u@example.com",
    }
    resp = await create_schedule(body=body, user=user, db=db_session)

    result = await db_session.execute(select(Schedule).where(Schedule.id == resp.id))
    row = result.scalar_one()
    assert row.payload["org_id"] == "dev-org"
    assert row.payload["platform"] == "bluesky"
