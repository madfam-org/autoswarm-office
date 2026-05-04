"""Tests for the built-in mastodon_promo_v1 playbook (mirror of the
reddit_promo_v1 tests). SOCIAL_POST enum coverage already lives in
test_reddit_promo_playbook.py — this file focuses on the Mastodon-
specific PlaybookDefinition + registration."""

from __future__ import annotations

from selva_permissions.playbook import (
    BUILTIN_PLAYBOOKS,
    MASTODON_PROMO_V1,
    PlaybookExecutionState,
    PlaybookGuard,
    get_builtin_playbook,
)
from selva_permissions.types import ActionCategory, PermissionLevel


class TestMastodonPromoV1Definition:
    def test_id_is_mastodon_promo_v1(self) -> None:
        assert MASTODON_PROMO_V1.id == "mastodon_promo_v1"

    def test_only_social_post_allowed(self) -> None:
        """The playbook MUST NOT allow file_write / email_send / etc. —
        a Mastodon-promo flow is single-action by design (same shape as
        Reddit)."""
        assert MASTODON_PROMO_V1.allowed_actions == {
            ActionCategory.SOCIAL_POST.value
        }

    def test_token_budget_is_20k(self) -> None:
        """20K tokens covers draft + revise + format + tag without
        runaway spending."""
        assert MASTODON_PROMO_V1.token_budget == 20_000

    def test_zero_financial_cap(self) -> None:
        """Posting itself is free. Ad-spend is a separate playbook to
        keep the trust boundaries clean."""
        assert MASTODON_PROMO_V1.financial_cap_cents == 0

    def test_require_approval_is_true(self) -> None:
        """HITL is the default for public-social posting. Mastodon posts
        are functionally permanent across the federation; one human
        approval per post is the cheapest insurance against reputational
        damage."""
        assert MASTODON_PROMO_V1.require_approval is True


class TestPlaybookGuardWithMastodonPromo:
    def test_guard_returns_ask_due_to_require_approval(self) -> None:
        """require_approval=True forces ASK regardless of allowed_actions —
        matches the existing PlaybookGuard contract."""
        state = PlaybookExecutionState(playbook=MASTODON_PROMO_V1)
        guard = PlaybookGuard(state)
        decision = guard.evaluate(ActionCategory.SOCIAL_POST)
        assert decision == PermissionLevel.ASK

    def test_guard_denies_email_send_inside_mastodon_promo(self) -> None:
        """Override require_approval to test the deny path; in production
        both gates fire."""
        state = PlaybookExecutionState(
            playbook=MASTODON_PROMO_V1.__class__(
                id=MASTODON_PROMO_V1.id,
                name=MASTODON_PROMO_V1.name,
                trigger_event=MASTODON_PROMO_V1.trigger_event,
                allowed_actions=MASTODON_PROMO_V1.allowed_actions,
                token_budget=MASTODON_PROMO_V1.token_budget,
                financial_cap_cents=MASTODON_PROMO_V1.financial_cap_cents,
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
    def test_get_builtin_playbook_finds_mastodon_promo(self) -> None:
        pb = get_builtin_playbook("mastodon_promo_v1")
        assert pb is not None
        assert pb is MASTODON_PROMO_V1

    def test_mastodon_promo_in_builtin_playbooks_dict(self) -> None:
        assert MASTODON_PROMO_V1.id in BUILTIN_PLAYBOOKS
        assert BUILTIN_PLAYBOOKS[MASTODON_PROMO_V1.id] is MASTODON_PROMO_V1
