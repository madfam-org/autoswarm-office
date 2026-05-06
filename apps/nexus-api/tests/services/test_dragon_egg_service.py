"""Unit tests for the dragon-egg state machine + plan generator.

Covers the contract documented in
``nexus_api.services.dragon_egg_service``:

- ``WARMUP_PLAN`` faithfully encodes the runbook §4.2 7-day curve.
- ``build_warmup_plan`` materializes one row per plan entry with
  ``scheduled_for = laid_at + day_offset``.
- ``lay_egg`` validates platform + required fields + (platform,
  persona_id) uniqueness.
- Status transitions: laid → incubating → hatching → hatched →
  matured. Forward-only; ``release_egg`` is the only path backwards.
- Progress = (completed + skipped) / total.
- ``release_egg`` supports both delete and force-status modes.

Tests use the SQLite-backed ``db_session`` fixture from conftest.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.services import dragon_egg_service as svc

# ---------------------------------------------------------------------------
# Plan generation — pure unit tests (no DB)
# ---------------------------------------------------------------------------


class TestWarmupPlanShape:
    """Lock-in tests against the runbook §4.2 curve.

    Renaming an action_type or moving a day_offset would silently
    change the runbook contract. These tests fail loudly if anyone
    drifts the curve without updating the runbook in lockstep.
    """

    def test_curve_has_18_rows(self) -> None:
        """The runbook has multi-action days; the curve materializes
        18 separate planned/HITL rows across 7 days."""
        assert len(svc.WARMUP_PLAN) == 18

    def test_curve_covers_days_1_through_7(self) -> None:
        days = {row[0] for row in svc.WARMUP_PLAN}
        assert days == {1, 2, 3, 4, 5, 6, 7}

    def test_day_1_has_profile_setup_and_follow_curated(self) -> None:
        day_1_actions = {row[1] for row in svc.WARMUP_PLAN if row[0] == 1}
        assert day_1_actions == {"profile_setup", "follow_curated"}

    def test_day_2_has_only_boost(self) -> None:
        """Runbook: 'Day 2 — boost / repost ... No original post.' """
        day_2_actions = {row[1] for row in svc.WARMUP_PLAN if row[0] == 2}
        assert day_2_actions == {"boost_high_signal"}

    def test_day_3_introduces_first_original_post(self) -> None:
        day_3 = [row for row in svc.WARMUP_PLAN if row[0] == 3]
        action_types = {row[1] for row in day_3}
        assert "reply_substantive" in action_types
        assert "original_post_no_link" in action_types

    def test_day_7_is_first_promotional_post(self) -> None:
        """The hatch event — first promotional post with disclosure."""
        day_7 = [row for row in svc.WARMUP_PLAN if row[0] == 7]
        assert len(day_7) == 1
        assert day_7[0][1] == "promotional_post"

    def test_day_5_and_6_have_with_link_post(self) -> None:
        """Days 5-6 introduce links; days 1-4 forbid them."""
        for day in (5, 6):
            day_rows = [row for row in svc.WARMUP_PLAN if row[0] == day]
            with_link = [r for r in day_rows if r[1] == "original_post_with_link"]
            assert len(with_link) >= 1, f"day {day} should have a link post"

        for day in (1, 2, 3, 4):
            day_rows = [row for row in svc.WARMUP_PLAN if row[0] == day]
            with_link = [r for r in day_rows if r[1] == "original_post_with_link"]
            assert len(with_link) == 0, f"day {day} must not have a link post"

    def test_hitl_actions_marked_pending_human(self) -> None:
        """profile_setup, follow_curated, boost, reply are all HITL in P1."""
        hitl_types = {
            "profile_setup",
            "follow_curated",
            "boost_high_signal",
            "reply_substantive",
        }
        for row in svc.WARMUP_PLAN:
            day_offset, action_type, status, _notes = row
            if action_type in hitl_types:
                assert status == "pending_human", (
                    f"day {day_offset} {action_type} should be HITL"
                )

    def test_post_actions_marked_planned(self) -> None:
        """original_post_*, promotional_post → worker-dispatchable."""
        worker_types = {
            "original_post_no_link",
            "original_post_with_link",
            "promotional_post",
        }
        for row in svc.WARMUP_PLAN:
            day_offset, action_type, status, _notes = row
            if action_type in worker_types:
                assert status == "planned", (
                    f"day {day_offset} {action_type} should be worker-dispatchable"
                )


class TestBuildWarmupPlan:
    def test_scheduled_for_increments_by_day(self) -> None:
        laid_at = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
        rows = svc.build_warmup_plan(laid_at=laid_at)
        # Sorted by day_offset (the canonical order).
        for row in rows:
            expected = laid_at + timedelta(days=row.day_offset)
            assert row.scheduled_for == expected

    def test_naive_laid_at_gets_utc_stamped(self) -> None:
        laid_at_naive = datetime(2026, 5, 4, 12, 0, 0)
        rows = svc.build_warmup_plan(laid_at=laid_at_naive)
        # All scheduled_for should still come back tz-aware.
        for row in rows:
            assert row.scheduled_for.tzinfo is not None

    def test_returns_one_row_per_plan_entry(self) -> None:
        rows = svc.build_warmup_plan(laid_at=datetime.now(UTC))
        assert len(rows) == len(svc.WARMUP_PLAN)


# ---------------------------------------------------------------------------
# DB-backed tests — lay_egg, transitions, progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLayEgg:
    async def test_lay_mastodon_egg_creates_egg_and_actions(
        self, db_session: AsyncSession
    ) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="mx_compliance_voice",
            platform="mastodon",
            handle="@mx_compliance@fosstodon.org",
            display_name="MX Compliance Voice",
            instance_url="https://fosstodon.org",
            created_by="admin-sub-1",
        )
        await db_session.commit()

        assert egg.id is not None
        assert egg.status == "laid"
        assert egg.progress == 0.0
        assert egg.owner_org_id == "madfam"

        actions = await svc.list_actions_for_egg(db_session, egg.id)
        assert len(actions) == len(svc.WARMUP_PLAN)
        # All actions reference the egg.
        assert all(a.egg_id == egg.id for a in actions)

    async def test_lay_bluesky_egg_no_instance_url_required(
        self, db_session: AsyncSession
    ) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="latam_finance_voice",
            platform="bluesky",
            handle="@latamfinance.bsky.social",
            display_name="LATAM Finance Voice",
            created_by="admin-sub-1",
        )
        await db_session.commit()
        assert egg.platform == "bluesky"
        assert egg.instance_url is None

    async def test_lay_mastodon_egg_without_instance_url_raises(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(svc.InvalidPayloadError):
            await svc.lay_egg(
                db_session,
                persona_id="x",
                platform="mastodon",
                handle="@x@y",
                display_name="X",
                created_by="admin-sub-1",
            )

    async def test_lay_egg_unsupported_platform_raises(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(svc.UnsupportedPlatformError):
            await svc.lay_egg(
                db_session,
                persona_id="x",
                platform="tiktok",  # Phase 2 — out of scope
                handle="@x",
                display_name="X",
                created_by="admin-sub-1",
            )

    async def test_lay_egg_duplicate_persona_platform_raises(
        self, db_session: AsyncSession
    ) -> None:
        await svc.lay_egg(
            db_session,
            persona_id="dup_persona",
            platform="bluesky",
            handle="@a",
            display_name="A",
            created_by="admin-sub-1",
        )
        await db_session.commit()

        with pytest.raises(svc.DuplicateEggError):
            await svc.lay_egg(
                db_session,
                persona_id="dup_persona",
                platform="bluesky",
                handle="@b",
                display_name="B",
                created_by="admin-sub-1",
            )

    async def test_same_persona_different_platform_ok(
        self, db_session: AsyncSession
    ) -> None:
        """The unique constraint is (platform, persona_id) — same
        persona on a different platform is fine."""
        await svc.lay_egg(
            db_session,
            persona_id="cross_platform",
            platform="bluesky",
            handle="@a",
            display_name="A",
            created_by="admin-sub-1",
        )
        egg2 = await svc.lay_egg(
            db_session,
            persona_id="cross_platform",
            platform="reddit",
            handle="u/a",
            display_name="A",
            created_by="admin-sub-1",
        )
        await db_session.commit()
        assert egg2.platform == "reddit"

    async def test_owner_org_id_defaults_to_madfam(
        self, db_session: AsyncSession
    ) -> None:
        """Phase 1 single-tenant guard: any new egg lands in 'madfam'
        unless a Phase 2 caller explicitly overrides."""
        egg = await svc.lay_egg(
            db_session,
            persona_id="default_org",
            platform="reddit",
            handle="u/x",
            display_name="X",
            created_by="admin-sub-1",
        )
        await db_session.commit()
        assert egg.owner_org_id == "madfam"


@pytest.mark.asyncio
class TestTransitions:
    async def _lay(self, db: AsyncSession, persona: str = "p1") -> svc.SocialAccountEgg:
        egg = await svc.lay_egg(
            db,
            persona_id=persona,
            platform="bluesky",
            handle="@x",
            display_name="X",
            created_by="admin",
        )
        await db.commit()
        return egg

    async def test_no_actions_completed_stays_laid(
        self, db_session: AsyncSession
    ) -> None:
        egg = await self._lay(db_session)
        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "laid"
        assert egg.progress == 0.0

    async def test_day_1_action_started_advances_to_incubating(
        self, db_session: AsyncSession
    ) -> None:
        egg = await self._lay(db_session, "p_inc")
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        day_1 = next(a for a in actions if a.day_offset == 1)
        await svc.mark_action_in_flight(db_session, day_1)

        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "incubating"

    async def test_day_3_original_post_completed_advances_to_hatching(
        self, db_session: AsyncSession
    ) -> None:
        egg = await self._lay(db_session, "p_hatch")
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        day_3_original = next(
            a for a in actions
            if a.day_offset == 3 and a.action_type == "original_post_no_link"
        )
        await svc.mark_action_completed(db_session, day_3_original)
        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "hatching"

    async def test_day_7_promotional_completed_advances_to_hatched(
        self, db_session: AsyncSession
    ) -> None:
        egg = await self._lay(db_session, "p_hatched")
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        day_7 = next(a for a in actions if a.day_offset == 7)
        await svc.mark_action_completed(db_session, day_7)
        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "hatched"
        assert egg.hatched_at is not None

    async def test_matured_after_14_days_clean(
        self, db_session: AsyncSession
    ) -> None:
        """Hatched + 14 elapsed days + transition() = matured."""
        egg = await self._lay(db_session, "p_matured")
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        day_7 = next(a for a in actions if a.day_offset == 7)
        await svc.mark_action_completed(db_session, day_7)
        # First transition: hatched.
        egg = await svc.transition(db_session, egg.id)
        # Now simulate 14 days passing.
        future = datetime.now(UTC) + timedelta(days=15)
        egg = await svc.transition(db_session, egg.id, now=future)
        await db_session.commit()
        assert egg.status == "matured"
        assert egg.matured_at is not None

    async def test_transition_is_idempotent_on_matured(
        self, db_session: AsyncSession
    ) -> None:
        egg = await self._lay(db_session, "p_idem")
        egg = await svc.release_egg(db_session, egg.id, force_status="matured")
        await db_session.commit()
        # Calling transition again on a matured egg is a no-op.
        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "matured"

    async def test_transitions_are_forward_only(
        self, db_session: AsyncSession
    ) -> None:
        """Once hatched, stays hatched even if no future action triggers."""
        egg = await self._lay(db_session, "p_forward")
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        day_7 = next(a for a in actions if a.day_offset == 7)
        await svc.mark_action_completed(db_session, day_7)
        egg = await svc.transition(db_session, egg.id)
        assert egg.status == "hatched"
        # No further completion — transition should leave status alone.
        egg = await svc.transition(db_session, egg.id)
        await db_session.commit()
        assert egg.status == "hatched"


@pytest.mark.asyncio
class TestProgress:
    async def test_zero_when_nothing_done(self, db_session: AsyncSession) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="prog_0",
            platform="reddit",
            handle="u/p",
            display_name="P",
            created_by="admin",
        )
        await db_session.commit()
        assert await svc.progress(db_session, egg.id) == 0.0

    async def test_full_when_everything_done(self, db_session: AsyncSession) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="prog_1",
            platform="reddit",
            handle="u/p",
            display_name="P",
            created_by="admin",
        )
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        for a in actions:
            await svc.mark_action_completed(db_session, a)
        await db_session.commit()
        assert await svc.progress(db_session, egg.id) == 1.0

    async def test_skipped_counts_toward_progress(
        self, db_session: AsyncSession
    ) -> None:
        """Skipped = explicit operator decision; counted as done."""
        egg = await svc.lay_egg(
            db_session,
            persona_id="prog_skip",
            platform="reddit",
            handle="u/p",
            display_name="P",
            created_by="admin",
        )
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        await svc.skip_action(db_session, actions[0])
        await db_session.commit()
        prog = await svc.progress(db_session, egg.id)
        assert prog == round(1 / len(actions), 4)

    async def test_failed_does_not_count(self, db_session: AsyncSession) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="prog_fail",
            platform="reddit",
            handle="u/p",
            display_name="P",
            created_by="admin",
        )
        actions = await svc.list_actions_for_egg(db_session, egg.id)
        await svc.mark_action_failed(db_session, actions[0], error="boom")
        await db_session.commit()
        # Failed actions don't count.
        assert await svc.progress(db_session, egg.id) == 0.0


@pytest.mark.asyncio
class TestReleaseEgg:
    async def test_release_with_no_force_status_deletes(
        self, db_session: AsyncSession
    ) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="rel_del",
            platform="bluesky",
            handle="@x",
            display_name="X",
            created_by="admin",
        )
        await db_session.commit()
        egg_id = egg.id
        await svc.release_egg(db_session, egg_id)
        await db_session.commit()
        with pytest.raises(svc.EggNotFoundError):
            await svc.get_egg(db_session, egg_id)

    async def test_release_with_force_status_advances(
        self, db_session: AsyncSession
    ) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="rel_force",
            platform="bluesky",
            handle="@x",
            display_name="X",
            created_by="admin",
        )
        await db_session.commit()

        egg = await svc.release_egg(db_session, egg.id, force_status="matured")
        await db_session.commit()
        assert egg.status == "matured"
        assert egg.progress == 1.0
        assert egg.matured_at is not None

    async def test_release_with_invalid_status_raises(
        self, db_session: AsyncSession
    ) -> None:
        egg = await svc.lay_egg(
            db_session,
            persona_id="rel_bad",
            platform="bluesky",
            handle="@x",
            display_name="X",
            created_by="admin",
        )
        await db_session.commit()
        with pytest.raises(svc.DragonEggError):
            await svc.release_egg(db_session, egg.id, force_status="bogus")


@pytest.mark.asyncio
class TestGetAction:
    async def test_get_action_wrong_egg_raises_not_found(
        self, db_session: AsyncSession
    ) -> None:
        """Cross-egg action lookup is treated as 'not found' so the
        API can't be used to enumerate actions across eggs."""
        egg_a = await svc.lay_egg(
            db_session,
            persona_id="x_a",
            platform="bluesky",
            handle="@a",
            display_name="A",
            created_by="admin",
        )
        egg_b = await svc.lay_egg(
            db_session,
            persona_id="x_b",
            platform="reddit",
            handle="u/b",
            display_name="B",
            created_by="admin",
        )
        await db_session.commit()

        b_actions = await svc.list_actions_for_egg(db_session, egg_b.id)
        # Looking up an action of egg_b but claiming it's egg_a's:
        with pytest.raises(svc.ActionNotFoundError):
            await svc.get_action(db_session, egg_a.id, b_actions[0].id)
