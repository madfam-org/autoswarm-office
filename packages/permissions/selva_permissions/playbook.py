"""Playbook system for bounded autonomous agent execution.

A Playbook is a pre-approved sequence of actions that agents can execute
without human-in-the-loop approval, within strict boundaries:
- Only declared action categories are allowed
- Token budget caps compute spending per execution
- Financial cap limits dollar exposure per execution

Playbooks can relax ASK→ALLOW but NEVER override DENY.

See docs/SWARM_MANIFESTO.md Axiom IV for architectural context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .types import ActionCategory, PermissionLevel

logger = logging.getLogger(__name__)


@dataclass
class PlaybookDefinition:
    """Defines the boundaries of an autonomous execution playbook."""

    id: str
    name: str
    trigger_event: str
    allowed_actions: set[str]  # ActionCategory values that can be auto-approved
    token_budget: int  # max compute tokens per execution
    financial_cap_cents: int  # max USD cents exposure per execution (0 = no financial actions)
    require_approval: bool = False  # if True, playbook still requires HITL (but tracks the intent)


@dataclass
class PlaybookExecutionState:
    """Tracks the running state of a playbook during execution."""

    playbook: PlaybookDefinition
    tokens_used: int = 0
    dollars_exposed_cents: int = 0
    actions_taken: list[str] = field(default_factory=list)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.playbook.token_budget - self.tokens_used)

    @property
    def dollars_remaining_cents(self) -> int:
        return max(0, self.playbook.financial_cap_cents - self.dollars_exposed_cents)

    @property
    def is_budget_exhausted(self) -> bool:
        return self.tokens_used >= self.playbook.token_budget


class PlaybookGuard:
    """Evaluates whether an action is permitted within a playbook's boundaries.

    The guard performs three checks:
    1. Is the action category in the playbook's allowed_actions?
    2. Is there sufficient token budget remaining?
    3. Is there sufficient financial cap remaining (for billing actions)?

    Returns ALLOW if all checks pass, DENY if any fails.
    NEVER returns ASK — playbooks are deterministic (either autonomous or blocked).
    """

    def __init__(self, state: PlaybookExecutionState) -> None:
        self.state = state

    def evaluate(
        self,
        category: ActionCategory,
        token_cost: int = 0,
        financial_exposure_cents: int = 0,
    ) -> PermissionLevel:
        """Evaluate whether the action is allowed within the playbook boundaries.

        Args:
            category: The action category being requested.
            token_cost: The compute token cost of this action.
            financial_exposure_cents: The dollar exposure in cents (0 for non-financial actions).

        Returns:
            PermissionLevel.ALLOW if all checks pass.
            PermissionLevel.DENY if any check fails (with logging).
        """
        playbook = self.state.playbook

        # Check 1: is the playbook set to require approval regardless?
        if playbook.require_approval:
            logger.debug(
                "Playbook '%s' requires approval (override), returning ASK for %s",
                playbook.name,
                category.value,
            )
            # Return None to signal "fall through to default matrix"
            return PermissionLevel.ASK

        # Check 2: is the action in the allowed set?
        if category.value not in playbook.allowed_actions:
            logger.info(
                "Playbook '%s' does not allow action '%s' (allowed: %s)",
                playbook.name,
                category.value,
                playbook.allowed_actions,
            )
            return PermissionLevel.DENY

        # Check 3: token budget
        if token_cost > 0 and self.state.tokens_used + token_cost > playbook.token_budget:
            logger.info(
                "Playbook '%s' token budget exhausted: used=%d, cost=%d, limit=%d",
                playbook.name,
                self.state.tokens_used,
                token_cost,
                playbook.token_budget,
            )
            return PermissionLevel.DENY

        # Check 4: financial cap
        if financial_exposure_cents > 0:
            if playbook.financial_cap_cents == 0:
                logger.info(
                    "Playbook '%s' has $0 financial cap, denying financial action",
                    playbook.name,
                )
                return PermissionLevel.DENY
            if (
                self.state.dollars_exposed_cents + financial_exposure_cents
                > playbook.financial_cap_cents
            ):
                logger.info(
                    "Playbook '%s' financial cap exceeded: exposed=%d, request=%d, limit=%d cents",
                    playbook.name,
                    self.state.dollars_exposed_cents,
                    financial_exposure_cents,
                    playbook.financial_cap_cents,
                )
                return PermissionLevel.DENY

        # All checks pass — autonomous execution allowed
        logger.debug(
            "Playbook '%s' allows autonomous execution of '%s' (tokens: %d/%d, $: %d/%d cents)",
            playbook.name,
            category.value,
            self.state.tokens_used + token_cost,
            playbook.token_budget,
            self.state.dollars_exposed_cents + financial_exposure_cents,
            playbook.financial_cap_cents,
        )
        return PermissionLevel.ALLOW

    def record_action(
        self, category: ActionCategory, token_cost: int = 0, financial_cents: int = 0
    ) -> None:
        """Record that an action was executed, deducting from budgets."""
        self.state.tokens_used += token_cost
        self.state.dollars_exposed_cents += financial_cents
        self.state.actions_taken.append(category.value)


# ---------------------------------------------------------------------------
# Built-in playbooks
# ---------------------------------------------------------------------------
#
# Built-ins are PlaybookDefinitions that ship with the package and are
# always available regardless of org-level configuration. They cover the
# load-bearing autonomous flows; tenant-specific playbooks layer on top
# via the org config / runtime registration.
#
# IMPORTANT: built-in playbooks intentionally set `require_approval=True`
# when the action carries irreversible reputational or PII consequences.
# Reddit posts CANNOT be unsent in any meaningful sense — the platform
# preserves them via Pushshift and other archives even after deletion —
# so the playbook's job is to enforce that "build → review → approve →
# post" is the default path, not "build → post".


REDDIT_PROMO_V1 = PlaybookDefinition(
    id="reddit_promo_v1",
    name="Reddit Promo (MVP)",
    trigger_event="manual_dispatch",
    allowed_actions={ActionCategory.SOCIAL_POST.value},
    token_budget=20_000,
    financial_cap_cents=0,  # Posting itself costs nothing; ad-spend is a separate playbook.
    require_approval=True,  # HITL gate — one approval per post (defence in depth alongside
                            # subreddit policy disclosure + 30-min Redis rate-limit).
)


# Mastodon (fediverse) promo playbook. Same shape as the Reddit MVP —
# Mastodon's federation model means a published toot is replicated to
# every following instance and survives local deletion via cached copies
# elsewhere in the network. Posts are FUNCTIONALLY PERMANENT across the
# fediverse, so HITL stays on by default — agents draft, humans approve.
# Defence in depth alongside the per-instance disclosure footer +
# visibility allow-list (default 'unlisted' to avoid public-timeline
# spam complaints) + Redis 30-min per-instance rate-limit.
MASTODON_PROMO_V1 = PlaybookDefinition(
    id="mastodon_promo_v1",
    name="Mastodon Promo (MVP)",
    trigger_event="manual_dispatch",
    allowed_actions={ActionCategory.SOCIAL_POST.value},
    token_budget=20_000,
    financial_cap_cents=0,  # Posting itself costs nothing; ad-spend is a separate playbook.
    require_approval=True,  # HITL gate — one approval per post.
)


# Bluesky / AT Protocol promo playbook. Same shape as the Reddit MVP —
# Bluesky's tech-leaning audience fits Selva (B2B founders/CTOs) and
# Yantra4D (technical maker community); rounds out the v1 social-channel
# set after Reddit (#149) and Mastodon. AT Protocol posts are replicated
# across the network and survive local deletion via cached copies
# elsewhere, so HITL stays on by default — agents draft, humans approve.
# Defence in depth alongside the mandatory ~36-char disclosure footer
# (within Bluesky's 300-char hard limit) + per-persona Redis 30-min
# rate-limit.
BLUESKY_PROMO_V1 = PlaybookDefinition(
    id="bluesky_promo_v1",
    name="Bluesky Promo (MVP)",
    trigger_event="manual_dispatch",
    allowed_actions={ActionCategory.SOCIAL_POST.value},
    token_budget=20_000,
    financial_cap_cents=0,  # Posting itself costs nothing; ad-spend is a separate playbook.
    require_approval=True,  # HITL gate — one approval per post (defence in depth).
)


# X (Twitter) promo playbook. Same shape as the Reddit/Mastodon/Bluesky MVPs.
# The ``x_post`` tool SHIPS DARK (disabled unless SELVA_X_POST_ENABLED is set
# + credentials provisioned), but the HITL playbook is registered up front so
# that the moment the channel is armed, "build → review → approve → post"
# is the default path — not "build → post". X posts are effectively permanent
# (indexed + archived across the network), so HITL stays on by default.
# Defence in depth alongside the mandatory ~36-char disclosure footer (within
# X's 280-char hard limit) + per-persona Redis 30-min rate-limit.
X_PROMO_V1 = PlaybookDefinition(
    id="x_promo_v1",
    name="X (Twitter) Promo (MVP)",
    trigger_event="manual_dispatch",
    allowed_actions={ActionCategory.SOCIAL_POST.value},
    token_budget=20_000,
    financial_cap_cents=0,  # Posting itself costs nothing; ad-spend is a separate playbook.
    require_approval=True,  # HITL gate — one approval per post.
)


# LinkedIn promo playbook (automated ``linkedin_post`` path). Same shape as
# the others. The tool SHIPS DARK (disabled unless SELVA_LINKEDIN_POST_ENABLED
# is set + credentials provisioned); drafts via ``linkedin_draft_create``
# remain the zero-config default. HITL stays on by default — LinkedIn posts
# reach a professional audience and are hard to unsend cleanly. Defence in
# depth alongside the mandatory disclosure footer (automated posts must
# disclose) + per-persona Redis 30-min rate-limit.
LINKEDIN_PROMO_V1 = PlaybookDefinition(
    id="linkedin_promo_v1",
    name="LinkedIn Promo (MVP)",
    trigger_event="manual_dispatch",
    allowed_actions={ActionCategory.SOCIAL_POST.value},
    token_budget=20_000,
    financial_cap_cents=0,  # Posting itself costs nothing; ad-spend is a separate playbook.
    require_approval=True,  # HITL gate — one approval per post.
)


BUILTIN_PLAYBOOKS: dict[str, PlaybookDefinition] = {
    REDDIT_PROMO_V1.id: REDDIT_PROMO_V1,
    MASTODON_PROMO_V1.id: MASTODON_PROMO_V1,
    BLUESKY_PROMO_V1.id: BLUESKY_PROMO_V1,
    X_PROMO_V1.id: X_PROMO_V1,
    LINKEDIN_PROMO_V1.id: LINKEDIN_PROMO_V1,
}


def get_builtin_playbook(playbook_id: str) -> PlaybookDefinition | None:
    """Return the built-in PlaybookDefinition for ``playbook_id``, or None.

    Tenant-specific overrides (loaded from org config) take precedence
    over built-ins; this helper is the lookup-of-last-resort the
    PermissionEngine consults when an unknown playbook id is dispatched.
    """
    return BUILTIN_PLAYBOOKS.get(playbook_id)
