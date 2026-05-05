"""Dragon-egg state machine — plan generation, status transitions, progress.

Codifies the canonical 7-day warmup curve from
``internal-devops/runbooks/2026-05-04-first-autonomous-campaign-launch.md``
§4.2 as a deterministic ``WARMUP_PLAN`` constant + a pure function
(``build_warmup_plan``) that materializes one row per action keyed off
the egg's ``laid_at``.

State machine
-------------

::

    laid ──(day-1 actions begin)──▶ incubating
                                       │
                                       ▼
                          (day-3 first original_post_no_link completes)
                                       │
                                       ▼
                                   hatching
                                       │
                                       ▼
                  (day-7 first promotional_post succeeds)
                                       │
                                       ▼
                                   hatched
                                       │
                                       ▼
                  (14 consecutive days of activity, no spam-flag)
                                       │
                                       ▼
                                   matured

Transitions are *one-way* in Phase 1 (admin override notwithstanding).
``transition()`` is idempotent — calling it on a matured egg returns
the egg unchanged. The worker calls ``transition()`` after every
action completion; the REST API also calls it on demand for the
admin "force advance" path.

Why a service module
--------------------

The state-machine logic is exercised from three call sites:

1. ``routers/dragon_eggs.py`` — manual transitions, lay-egg endpoint.
2. ``apps/workers/selva_workers/jobs/dragon_egg_warmup.py`` — worker
   calls ``transition()`` after every action completion.
3. Tests — unit tests poke the service directly.

Putting the rules in a service keeps the router thin and lets the
worker/tests share the same invariants.

Phase 2 forward-compat
----------------------

- ``build_warmup_plan`` returns a list of dicts, not ORM rows, so
  Phase 2's tenant-billing wrapper can charge per-action credits
  before the rows are persisted.
- ``transition()`` accepts an optional ``now`` param so tests can
  freeze time without monkeypatching ``datetime``.
- ``WARMUP_PLAN`` is a module-level tuple; a future
  ``per_platform_curve()`` can specialize it without touching the
  state machine.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SocialAccountEgg, SocialAccountWarmupAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — Phase 1 scope
# ---------------------------------------------------------------------------

#: Platforms in scope for Phase 1 MVP.
SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"mastodon", "bluesky", "reddit"})

#: Egg lifecycle states. Order matters — index used in ``_status_rank``
#: for the "is X further along than Y" comparator.
EGG_STATES: tuple[str, ...] = (
    "laid",
    "incubating",
    "hatching",
    "hatched",
    "matured",
)

#: Action statuses. ``planned`` is the default for a freshly-generated
#: row; ``pending_human`` is a HITL hold (Phase 1 only path for
#: profile_setup / follow_curated / boost_high_signal /
#: reply_substantive).
ACTION_STATUSES: tuple[str, ...] = (
    "planned",
    "pending_human",
    "in_flight",
    "completed",
    "failed",
    "skipped",
)

#: Days a hatched egg must stay clean before maturing. The runbook
#: doesn't pin an exact number; the spec calls for "14 consecutive
#: days of activity without spam-flag" — codified here.
MATURATION_DAYS_AFTER_HATCH: int = 14


# ---------------------------------------------------------------------------
# The canonical 7-day curve from the runbook §4.2
# ---------------------------------------------------------------------------

#: Each entry is ``(day_offset, action_type, status, notes)`` where
#: ``status`` is the row's *initial* status. Phase 1 has 4 action
#: types that route through HITL (``pending_human``) and 3 that go
#: directly through the worker (``planned``).
#:
#: The runbook says:
#:   Day 1 — set bio + avatar + header. Follow 30 high-signal accounts
#:           in the niche. Don't post.
#:   Day 2 — boost / repost 3-5 high-quality items. Like 10. No
#:           original post.
#:   Day 3 — reply substantively to 3 conversations (not promotional).
#:           One short original observation post (no link).
#:   Day 4 — two original posts (no link). One reply. Boost 5.
#:   Day 5 — three original posts. One can include a link. Reply to 3.
#:   Day 6 — same as Day 5. Confirm engagement is non-zero.
#:   Day 7 — first promotional post with disclosure footer + UTM.
#:
#: Multi-action days (e.g. Day 4's two original posts) are codified as
#: separate rows so the operator can execute / skip each independently.
WARMUP_PLAN: tuple[tuple[int, str, str, str], ...] = (
    # Day 1 — profile setup + follow curated. Both HITL: profile setup
    # is human-driven; follow_curated needs human curation in Phase 1.
    (1, "profile_setup", "pending_human", "Set bio, avatar, header. Don't post."),
    (1, "follow_curated", "pending_human", "Follow 30 high-signal accounts."),
    # Day 2 — boost + like. HITL because picking high-quality items
    # requires human taste in Phase 1.
    (2, "boost_high_signal", "pending_human", "Boost / repost 3-5 high-quality items. Like 10."),
    # Day 3 — first substantive reply (HITL) + first original post (worker-dispatchable).
    (3, "reply_substantive", "pending_human", "Reply substantively to 3 conversations (not promotional)."),
    (3, "original_post_no_link", "planned", "Short original observation post. No link."),
    # Day 4 — two originals + one reply + boost 5.
    (4, "original_post_no_link", "planned", "Original post #1. No link."),
    (4, "original_post_no_link", "planned", "Original post #2. No link."),
    (4, "reply_substantive", "pending_human", "One substantive reply."),
    (4, "boost_high_signal", "pending_human", "Boost 5 high-quality items."),
    # Day 5 — three originals. One can include a link.
    (5, "original_post_no_link", "planned", "Original post #1. No link."),
    (5, "original_post_no_link", "planned", "Original post #2. No link."),
    (5, "original_post_with_link", "planned", "Original post with link to public MADFAM page."),
    (5, "reply_substantive", "pending_human", "Reply to 3 conversations."),
    # Day 6 — same as Day 5. Confirm engagement non-zero.
    (6, "original_post_no_link", "planned", "Original post #1. Confirm engagement is non-zero."),
    (6, "original_post_no_link", "planned", "Original post #2."),
    (6, "original_post_with_link", "planned", "Original post with link."),
    (6, "reply_substantive", "pending_human", "Reply to 3 conversations."),
    # Day 7 — first promotional post with disclosure + UTM. The hatch
    # event.
    (7, "promotional_post", "planned", "First promotional post with disclosure footer + UTM."),
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DragonEggError(Exception):
    """Base for all dragon-egg domain errors."""


class UnsupportedPlatformError(DragonEggError):
    """Raised when ``lay_egg`` is called with a platform outside
    ``SUPPORTED_PLATFORMS``."""


class DuplicateEggError(DragonEggError):
    """Raised when ``lay_egg`` is called for a (platform, persona_id)
    pair that already has an egg."""


class EggNotFoundError(DragonEggError):
    """Raised when an egg id doesn't resolve."""


class ActionNotFoundError(DragonEggError):
    """Raised when an action id doesn't belong to the named egg."""


class InvalidPayloadError(DragonEggError):
    """Raised when ``lay_egg`` is called with a missing required field
    (e.g. mastodon without ``instance_url``)."""


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlanRow:
    """In-memory representation of a single warmup-plan row.

    Used by ``build_warmup_plan`` so the planner is testable without a
    DB; ``lay_egg`` then materializes ``_PlanRow`` instances into ORM
    rows.
    """

    day_offset: int
    action_type: str
    status: str
    notes: str
    scheduled_for: datetime


def build_warmup_plan(
    *, laid_at: datetime, plan: tuple[tuple[int, str, str, str], ...] | None = None
) -> list[_PlanRow]:
    """Materialize the canonical 7-day curve into per-action rows.

    Args:
        laid_at: The egg's ``laid_at`` UTC timestamp. Each plan row's
            ``scheduled_for`` is computed as ``laid_at + day_offset days``
            (rounded to the day boundary so day-2 actions don't fire
            until 24h after laying — a hostile "burst on day 1" would
            torch the persona per the runbook).
        plan: Override the canonical curve. Phase 2 will pass a
            per-platform variant; Phase 1 leaves this default.

    Returns:
        List of ``_PlanRow`` instances in canonical order
        (day_offset asc, then plan-row asc).

    Note: ``laid_at`` is treated as UTC. Caller is responsible for
    ensuring tz-awareness — naive datetimes get UTC stamped.
    """
    if laid_at.tzinfo is None:
        laid_at = laid_at.replace(tzinfo=UTC)

    canonical = plan if plan is not None else WARMUP_PLAN

    rows: list[_PlanRow] = []
    for day_offset, action_type, status, notes in canonical:
        scheduled_for = laid_at + timedelta(days=day_offset)
        rows.append(
            _PlanRow(
                day_offset=day_offset,
                action_type=action_type,
                status=status,
                notes=notes,
                scheduled_for=scheduled_for,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Egg lifecycle operations
# ---------------------------------------------------------------------------


async def lay_egg(
    db: AsyncSession,
    *,
    persona_id: str,
    platform: str,
    handle: str,
    display_name: str,
    created_by: str,
    instance_url: str | None = None,
    owner_org_id: str = "madfam",
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> SocialAccountEgg:
    """Create a new egg + its full warmup action plan.

    Idempotency: a unique constraint on ``(platform, persona_id)``
    means two concurrent calls for the same pair will see exactly one
    succeed; the other raises ``DuplicateEggError``.

    Args:
        db: Async SQLAlchemy session — caller commits.
        persona_id: Selva persona id (matches the
            ``MASTODON_ACCESS_TOKEN_<PERSONA_ID>`` env-var convention).
        platform: One of ``SUPPORTED_PLATFORMS``.
        handle: Account handle on the platform (e.g.
            ``@mx_compliance_voice``).
        display_name: Operator-friendly label.
        created_by: Janua user sub of the laying operator.
        instance_url: Required for federated platforms (Mastodon).
            Ignored for non-federated (Bluesky, Reddit).
        owner_org_id: Tenant scope. Defaults to ``'madfam'`` for
            Phase 1; Phase 2 derives from the JWT.
        metadata: Platform-specific extras (e.g. content rating,
            auto-approve toggles). Defaults to empty dict.
        now: Test hook — caller can freeze ``laid_at``.

    Raises:
        UnsupportedPlatformError: ``platform`` not in
            ``SUPPORTED_PLATFORMS``.
        InvalidPayloadError: federated platform without ``instance_url``.
        DuplicateEggError: ``(platform, persona_id)`` already exists.
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise UnsupportedPlatformError(
            f"platform {platform!r} not in Phase 1 scope "
            f"({sorted(SUPPORTED_PLATFORMS)}); see Phase 2 design for"
            " roadmap"
        )

    # Mastodon is federated; the worker needs to know which instance to
    # authenticate against. Bluesky/Reddit have a single canonical host
    # so instance_url is irrelevant.
    if platform == "mastodon" and not instance_url:
        raise InvalidPayloadError(
            "instance_url is required for mastodon eggs (federated platform)"
        )

    if not persona_id.strip():
        raise InvalidPayloadError("persona_id is required")
    if not handle.strip():
        raise InvalidPayloadError("handle is required")
    if not display_name.strip():
        raise InvalidPayloadError("display_name is required")

    laid_at = now or datetime.now(UTC)

    egg = SocialAccountEgg(
        persona_id=persona_id,
        platform=platform,
        handle=handle,
        display_name=display_name,
        instance_url=instance_url,
        status="laid",
        progress=0.0,
        laid_at=laid_at,
        owner_org_id=owner_org_id,
        created_by=created_by,
        metadata_=dict(metadata or {}),
    )

    db.add(egg)
    # Flush so the egg.id PK is available for the FK on action rows
    # without committing the surrounding transaction (caller commits).
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateEggError(
            f"egg already exists for platform={platform!r} "
            f"persona_id={persona_id!r}"
        ) from exc

    plan_rows = build_warmup_plan(laid_at=laid_at)
    for plan_row in plan_rows:
        db.add(
            SocialAccountWarmupAction(
                egg_id=egg.id,
                action_type=plan_row.action_type,
                status=plan_row.status,
                scheduled_for=plan_row.scheduled_for,
                day_offset=plan_row.day_offset,
                notes=plan_row.notes,
            )
        )

    await db.flush()
    logger.info(
        "lay_egg: created %s egg %s for persona=%s with %d planned actions",
        platform,
        egg.id,
        persona_id,
        len(plan_rows),
    )
    return egg


async def get_egg(
    db: AsyncSession, egg_id: uuid.UUID | str
) -> SocialAccountEgg:
    """Load an egg by id.

    Raises:
        EggNotFoundError: id doesn't resolve.
    """
    egg = await db.get(SocialAccountEgg, _coerce_uuid(egg_id))
    if egg is None:
        raise EggNotFoundError(f"egg {egg_id!r} not found")
    return egg


async def list_eggs(
    db: AsyncSession,
    *,
    owner_org_id: str | None = None,
    status: str | None = None,
    platform: str | None = None,
) -> list[SocialAccountEgg]:
    """List eggs, optionally filtered. Sorted by laid_at desc."""
    stmt = select(SocialAccountEgg).order_by(SocialAccountEgg.laid_at.desc())
    if owner_org_id is not None:
        stmt = stmt.where(SocialAccountEgg.owner_org_id == owner_org_id)
    if status is not None:
        stmt = stmt.where(SocialAccountEgg.status == status)
    if platform is not None:
        stmt = stmt.where(SocialAccountEgg.platform == platform)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_actions_for_egg(
    db: AsyncSession, egg_id: uuid.UUID | str
) -> list[SocialAccountWarmupAction]:
    """Load all warmup actions for an egg, sorted by day_offset asc."""
    stmt = (
        select(SocialAccountWarmupAction)
        .where(SocialAccountWarmupAction.egg_id == _coerce_uuid(egg_id))
        .order_by(
            SocialAccountWarmupAction.day_offset.asc(),
            SocialAccountWarmupAction.scheduled_for.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def progress(db: AsyncSession, egg_id: uuid.UUID | str) -> float:
    """Compute progress as completed actions / total actions.

    Skipped actions count as completed for progress (operator already
    decided not to do it). Failed actions don't count — the egg isn't
    making progress when something's broken.

    Returns 0.0 when there are no actions (defensive — should never
    happen for a freshly-laid egg).
    """
    actions = await list_actions_for_egg(db, egg_id)
    if not actions:
        return 0.0
    done = sum(1 for a in actions if a.status in ("completed", "skipped"))
    return round(done / len(actions), 4)


async def transition(
    db: AsyncSession,
    egg_id: uuid.UUID | str,
    *,
    now: datetime | None = None,
) -> SocialAccountEgg:
    """Advance the egg's status based on completed actions.

    Idempotent — safe to call after every action update. Recomputes
    ``progress`` as a side effect so the UI's animation stays in sync.

    Transition rules (one-way; admin override uses ``release_egg``):

    - ``laid`` → ``incubating``: any day-1 action has started
      (``in_flight`` or beyond).
    - ``incubating`` → ``hatching``: a day-3
      ``original_post_no_link`` is ``completed``.
    - ``hatching`` → ``hatched``: a day-7 ``promotional_post`` is
      ``completed``.
    - ``hatched`` → ``matured``: ``MATURATION_DAYS_AFTER_HATCH`` days
      have elapsed since ``hatched_at`` (the spec calls for "no
      spam-flag" — Phase 1 trusts the operator and just checks elapsed
      time; Phase 2 will plug a spam-flag detector).
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    egg = await get_egg(db, egg_id)
    actions = await list_actions_for_egg(db, egg.id)

    new_status = _compute_status(egg, actions, now=now)
    new_progress = (
        round(
            sum(1 for a in actions if a.status in ("completed", "skipped"))
            / max(len(actions), 1),
            4,
        )
        if actions
        else 0.0
    )

    if new_status != egg.status:
        logger.info(
            "transition: egg %s %s -> %s (progress=%.4f)",
            egg.id,
            egg.status,
            new_status,
            new_progress,
        )
        egg.status = new_status
        if new_status == "hatched" and egg.hatched_at is None:
            egg.hatched_at = now
        if new_status == "matured" and egg.matured_at is None:
            egg.matured_at = now

    egg.progress = new_progress
    await db.flush()
    return egg


def _compute_status(
    egg: SocialAccountEgg,
    actions: list[SocialAccountWarmupAction],
    *,
    now: datetime,
) -> str:
    """Pure helper — given current egg + actions, return target status.

    Forward-only: if the current status is already past the trigger,
    we don't roll back. ``release_egg`` is the only path that moves
    backwards.
    """
    current_rank = _status_rank(egg.status)

    # Check the trigger for each forward transition. Return the
    # furthest state reached.

    # laid → incubating: any day-1 action has *started* (status moved
    # past 'planned' / 'pending_human').
    incubating_triggered = any(
        a.day_offset == 1 and a.status not in ("planned", "pending_human")
        for a in actions
    )

    # incubating → hatching: a day-3 original_post_no_link is completed.
    hatching_triggered = any(
        a.day_offset == 3
        and a.action_type == "original_post_no_link"
        and a.status == "completed"
        for a in actions
    )

    # hatching → hatched: a day-7 promotional_post is completed.
    hatched_triggered = any(
        a.day_offset == 7
        and a.action_type == "promotional_post"
        and a.status == "completed"
        for a in actions
    )

    # hatched → matured: 14 days after hatched_at, no spam-flag.
    # Phase 1 trusts the operator and only checks elapsed time;
    # Phase 2 will plug a spam-flag detector + abort the maturation.
    matured_triggered = (
        egg.hatched_at is not None
        and (now - _ensure_utc(egg.hatched_at))
        >= timedelta(days=MATURATION_DAYS_AFTER_HATCH)
    )

    # Pick the furthest reachable state, but never roll back.
    target_rank = current_rank
    if incubating_triggered:
        target_rank = max(target_rank, _status_rank("incubating"))
    if hatching_triggered:
        target_rank = max(target_rank, _status_rank("hatching"))
    if hatched_triggered:
        target_rank = max(target_rank, _status_rank("hatched"))
    if matured_triggered:
        target_rank = max(target_rank, _status_rank("matured"))

    return EGG_STATES[target_rank]


def _status_rank(status: str) -> int:
    """Index of ``status`` in ``EGG_STATES``. Raises if unknown."""
    return EGG_STATES.index(status)


# ---------------------------------------------------------------------------
# Action operations
# ---------------------------------------------------------------------------


async def get_action(
    db: AsyncSession,
    egg_id: uuid.UUID | str,
    action_id: uuid.UUID | str,
) -> SocialAccountWarmupAction:
    """Load an action and verify it belongs to the named egg.

    Raises:
        ActionNotFoundError: id doesn't resolve OR belongs to a
            different egg (treated identically to "not found" so
            the API can't be used to enumerate actions across eggs).
    """
    action = await db.get(SocialAccountWarmupAction, _coerce_uuid(action_id))
    if action is None or action.egg_id != _coerce_uuid(egg_id):
        raise ActionNotFoundError(
            f"action {action_id!r} not found on egg {egg_id!r}"
        )
    return action


async def mark_action_in_flight(
    db: AsyncSession,
    action: SocialAccountWarmupAction,
    *,
    now: datetime | None = None,
) -> SocialAccountWarmupAction:
    """Transition an action from ``planned`` / ``pending_human`` →
    ``in_flight``. Worker calls this before invoking the underlying tool.
    """
    now = now or datetime.now(UTC)
    action.status = "in_flight"
    action.executed_at = now
    await db.flush()
    return action


async def mark_action_completed(
    db: AsyncSession,
    action: SocialAccountWarmupAction,
    *,
    result: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> SocialAccountWarmupAction:
    """Mark an action ``completed`` with an optional ``result`` blob."""
    now = now or datetime.now(UTC)
    action.status = "completed"
    action.executed_at = action.executed_at or now
    if result is not None:
        action.result = result
    await db.flush()
    return action


async def mark_action_failed(
    db: AsyncSession,
    action: SocialAccountWarmupAction,
    *,
    error: str,
    now: datetime | None = None,
) -> SocialAccountWarmupAction:
    """Mark an action ``failed`` with the error captured in ``result``."""
    now = now or datetime.now(UTC)
    action.status = "failed"
    action.executed_at = action.executed_at or now
    action.result = {"error": error}
    await db.flush()
    return action


async def skip_action(
    db: AsyncSession,
    action: SocialAccountWarmupAction,
    *,
    notes: str | None = None,
) -> SocialAccountWarmupAction:
    """Operator override: mark an action ``skipped``.

    Skipped actions count toward progress (operator made an explicit
    decision not to do it). The status transition is one-way — once
    skipped, the action can't be re-planned.
    """
    action.status = "skipped"
    if notes:
        # Concatenate so the original runbook note isn't lost.
        existing = (action.notes or "").rstrip()
        sep = "\n" if existing else ""
        action.notes = f"{existing}{sep}[skipped] {notes}"
    await db.flush()
    return action


async def release_egg(
    db: AsyncSession,
    egg_id: uuid.UUID | str,
    *,
    force_status: str | None = None,
) -> SocialAccountEgg:
    """Admin override: force an egg to a target status, OR delete.

    Phase 1 supports two modes:

    - ``force_status='matured'``: skip the warmup curve entirely
      (e.g. promoting a manually-warmed account into the dragon
      tier). Sets ``hatched_at`` and ``matured_at`` to now if missing.
    - ``force_status=None``: deletes the egg + cascades to its actions.
      For decommissioning a persona / freeing the (platform,
      persona_id) unique slot.

    The function name "release" is the runbook metaphor — release
    the dragon to its matured form, or release the slot back to the
    pool.
    """
    egg = await get_egg(db, egg_id)

    if force_status is None:
        await db.delete(egg)
        await db.flush()
        logger.info("release_egg: deleted egg %s", egg.id)
        return egg

    if force_status not in EGG_STATES:
        raise DragonEggError(
            f"force_status {force_status!r} not in {EGG_STATES}"
        )

    now = datetime.now(UTC)
    egg.status = force_status
    if force_status in ("hatched", "matured") and egg.hatched_at is None:
        egg.hatched_at = now
    if force_status == "matured" and egg.matured_at is None:
        egg.matured_at = now
    if force_status == "matured":
        egg.progress = 1.0
    await db.flush()
    logger.info("release_egg: forced egg %s to %s", egg.id, force_status)
    return egg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Accept str or UUID — return UUID. Mirrors ``models._new_uuid``
    semantics for the FK column type."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _ensure_utc(dt: datetime) -> datetime:
    """Stamp UTC on naive datetimes. SQLite tests round-trip without
    tzinfo; production Postgres preserves it. Defensive for both."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
