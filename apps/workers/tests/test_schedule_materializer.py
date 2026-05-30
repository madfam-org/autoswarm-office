"""Tests for schedules → scheduled_actions materializer."""

from __future__ import annotations

from datetime import UTC, datetime

from selva_workers.jobs.schedule_materializer import cron_matches, is_schedule_due


class TestCronMatching:
    def test_daily_at_nine(self) -> None:
        dt = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
        assert cron_matches(dt, "0 9 * * *")

    def test_wrong_minute(self) -> None:
        dt = datetime(2026, 5, 29, 9, 15, tzinfo=UTC)
        assert not cron_matches(dt, "0 9 * * *")

    def test_monday_only(self) -> None:
        # 2026-06-01 is a Monday
        monday = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        tuesday = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
        assert cron_matches(monday, "0 9 * * 1")
        assert not cron_matches(tuesday, "0 9 * * 1")


class TestScheduleDue:
    def test_first_run_when_cron_matches(self) -> None:
        now = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
        assert is_schedule_due("0 9 * * *", None, now)

    def test_not_due_same_minute_twice(self) -> None:
        now = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
        assert not is_schedule_due("0 9 * * *", now, now)

    def test_due_again_next_matching_minute(self) -> None:
        first = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
        next_day = datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
        assert is_schedule_due("0 9 * * *", first, next_day)
