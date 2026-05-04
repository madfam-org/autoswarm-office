"""Test that ScheduledAction.SOCIAL_POST is wired in for the Reddit MVP."""

from __future__ import annotations

from nexus_api.models import ScheduledAction


class TestScheduledActionSocialPost:
    def test_social_post_enum_value(self) -> None:
        """Stable string value — Celery Beat reads this from the schedules
        table; renaming would orphan existing schedules."""
        assert ScheduledAction.SOCIAL_POST.value == "social_post"

    def test_social_post_is_distinct_from_existing_actions(self) -> None:
        existing = {
            ScheduledAction.ACP_INITIATE,
            ScheduledAction.SKILL_REFINE,
            ScheduledAction.MEMORY_COMPACT,
        }
        assert ScheduledAction.SOCIAL_POST not in existing

    def test_can_be_constructed_from_string_value(self) -> None:
        """Schedule API deserializes from the JSON string literal."""
        assert ScheduledAction("social_post") is ScheduledAction.SOCIAL_POST
