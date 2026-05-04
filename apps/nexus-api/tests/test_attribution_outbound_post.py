"""Tests for the outbound_post.* attribution events (Reddit MVP)."""

from __future__ import annotations

from unittest.mock import patch

from nexus_api.attribution import (
    EVENT_OUTBOUND_POST_CREATED,
    EVENT_OUTBOUND_POST_ENGAGED,
    emit_outbound_post_created,
    emit_outbound_post_engaged,
)


class TestEmitOutboundPostCreated:
    def test_track_called_with_post_id_as_distinct_id(self) -> None:
        """post_id is the distinct_id at this stage — no lead exists yet
        and no auth has happened. Dhanam aliases later on conversion."""
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_created(
                "abc123",
                subreddit="SaaS",
                persona_id="growth-1",
                disclosure_applied=True,
            )

        mock_track.assert_called_once()
        distinct_id, event_name, props = mock_track.call_args.args
        assert distinct_id == "abc123"
        assert event_name == EVENT_OUTBOUND_POST_CREATED
        assert props["subreddit"] == "SaaS"
        assert props["persona_id"] == "growth-1"
        assert props["disclosure_applied"] is True
        assert props["platform"] == "reddit"

    def test_empty_post_id_skips_track(self) -> None:
        """Defensive: never emit a noise event with an empty distinct_id —
        PostHog would silently merge into a sentinel persona."""
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_created(
                "",
                subreddit="SaaS",
                persona_id="x",
                disclosure_applied=True,
            )
        mock_track.assert_not_called()

    def test_extra_props_merged(self) -> None:
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_created(
                "abc",
                subreddit="SaaS",
                persona_id="x",
                disclosure_applied=True,
                extra={"flair": "AMA"},
            )
        props = mock_track.call_args.args[2]
        assert props["flair"] == "AMA"


class TestEmitOutboundPostEngaged:
    def test_click_only_engagement(self) -> None:
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_engaged(
                "abc",
                click_count=4,
            )
        props = mock_track.call_args.args[2]
        assert props["click_count"] == 4
        assert props["converted"] is False
        assert "subscription_id" not in props
        assert mock_track.call_args.args[1] == EVENT_OUTBOUND_POST_ENGAGED

    def test_engagement_with_conversion_records_subscription_id(self) -> None:
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_engaged(
                "abc",
                click_count=10,
                subscription_id_if_converted="sub_123",
            )
        props = mock_track.call_args.args[2]
        assert props["converted"] is True
        assert props["subscription_id"] == "sub_123"

    def test_empty_post_id_skips_track(self) -> None:
        with patch("nexus_api.attribution.track") as mock_track:
            emit_outbound_post_engaged("", click_count=1)
        mock_track.assert_not_called()
