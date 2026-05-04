"""Tests for the built-in reddit_promo_v1 playbook + SOCIAL_POST enum."""

from __future__ import annotations

from selva_permissions.playbook import (
    BUILTIN_PLAYBOOKS,
    REDDIT_PROMO_V1,
    PlaybookExecutionState,
    PlaybookGuard,
    get_builtin_playbook,
)
from selva_permissions.types import ActionCategory, PermissionLevel


class TestSocialPostEnum:
    def test_social_post_value_is_stable(self) -> None:
        """Schedules + audit + analytics consume this string — keep it stable."""
        assert ActionCategory.SOCIAL_POST.value == "social_post"

    def test_social_post_distinct_from_marketing_send(self) -> None:
        """SOCIAL_POST ≠ MARKETING_SEND. Email and public-social have very
        different reversibility profiles + audit shapes."""
        assert ActionCategory.SOCIAL_POST != ActionCategory.MARKETING_SEND


class TestRedditPromoV1Definition:
    def test_id_is_reddit_promo_v1(self) -> None:
        assert REDDIT_PROMO_V1.id == "reddit_promo_v1"

    def test_only_social_post_allowed(self) -> None:
        """The playbook MUST NOT allow file_write / email_send / etc. —
        a Reddit-promo flow is single-action by design."""
        assert REDDIT_PROMO_V1.allowed_actions == {ActionCategory.SOCIAL_POST.value}

    def test_token_budget_is_20k(self) -> None:
        """20K tokens covers draft + revise + format + tag without
        runaway spending."""
        assert REDDIT_PROMO_V1.token_budget == 20_000

    def test_zero_financial_cap(self) -> None:
        """Posting itself is free. Ad-spend is a separate playbook to
        keep the trust boundaries clean."""
        assert REDDIT_PROMO_V1.financial_cap_cents == 0

    def test_require_approval_is_true(self) -> None:
        """HITL is the default for public-social posting. Reddit posts
        are functionally permanent; one human approval per post is the
        cheapest insurance against reputational damage."""
        assert REDDIT_PROMO_V1.require_approval is True


class TestPlaybookGuardWithRedditPromo:
    def test_guard_returns_ask_due_to_require_approval(self) -> None:
        """require_approval=True forces ASK regardless of allowed_actions —
        matches the existing PlaybookGuard contract."""
        state = PlaybookExecutionState(playbook=REDDIT_PROMO_V1)
        guard = PlaybookGuard(state)
        decision = guard.evaluate(ActionCategory.SOCIAL_POST)
        assert decision == PermissionLevel.ASK

    def test_guard_denies_email_send_inside_reddit_promo(self) -> None:
        """The agent is bounded — no smuggling EMAIL_SEND inside a
        SOCIAL_POST playbook. Override require_approval to test the
        deny path; in production both gates fire."""
        state = PlaybookExecutionState(
            playbook=REDDIT_PROMO_V1.__class__(
                id=REDDIT_PROMO_V1.id,
                name=REDDIT_PROMO_V1.name,
                trigger_event=REDDIT_PROMO_V1.trigger_event,
                allowed_actions=REDDIT_PROMO_V1.allowed_actions,
                token_budget=REDDIT_PROMO_V1.token_budget,
                financial_cap_cents=REDDIT_PROMO_V1.financial_cap_cents,
                require_approval=False,  # bypass HITL to test deny path
            )
        )
        guard = PlaybookGuard(state)
        # SOCIAL_POST allowed
        assert guard.evaluate(ActionCategory.SOCIAL_POST) == PermissionLevel.ALLOW
        # EMAIL_SEND denied (not in allowed_actions)
        assert guard.evaluate(ActionCategory.EMAIL_SEND) == PermissionLevel.DENY
        # FILE_WRITE denied
        assert guard.evaluate(ActionCategory.FILE_WRITE) == PermissionLevel.DENY


class TestBuiltinRegistry:
    def test_get_builtin_playbook_finds_reddit_promo(self) -> None:
        pb = get_builtin_playbook("reddit_promo_v1")
        assert pb is not None
        assert pb is REDDIT_PROMO_V1

    def test_get_builtin_playbook_unknown_returns_none(self) -> None:
        assert get_builtin_playbook("never_seen_this_id") is None

    def test_builtin_playbooks_dict_keyed_by_id(self) -> None:
        for pb_id, pb in BUILTIN_PLAYBOOKS.items():
            assert pb.id == pb_id, f"BUILTIN_PLAYBOOKS[{pb_id!r}].id = {pb.id!r}"
