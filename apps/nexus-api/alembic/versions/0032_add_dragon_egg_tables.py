"""Add ``social_account_eggs`` + ``social_account_warmup_actions`` —
the data backbone for the Phase 1 dragon-egg hatching feature.

The "dragon egg" metaphor models a new social-media account as an egg
that progresses through a deterministic 7-day warmup curve before it
graduates into autonomous-posting tier. The canonical curve is in
``internal-devops/runbooks/2026-05-04-first-autonomous-campaign-launch.md``
§4.2; this migration creates the per-egg state row and the per-day
action plan rows the worker drains alongside the existing
``scheduled_actions`` queue.

Why two tables, not one
-----------------------

Eggs are long-lived (laid → matured spans weeks); warmup actions are
short-lived rows the worker scans every minute. Splitting them keeps
the hot-path ``WHERE scheduled_for <= NOW()`` index narrow and lets
the egg row carry the fat metadata (display name, persona handle,
instance URL, owner_org_id) without bloating the dispatch query.

Tables
------

``social_account_eggs``
    The egg/account itself. One row per (platform, persona_id) pair
    (UNIQUE). Phase 1 scope: ``mastodon`` | ``bluesky`` | ``reddit``.
    Lifecycle: ``laid`` → ``incubating`` → ``hatching`` → ``hatched``
    → ``matured``. ``progress`` is a computed convenience field
    (0.0..1.0, completed warmup actions / total) that the UI polls
    for the egg-crack animation.

``social_account_warmup_actions``
    The per-day action plan generated when the egg is laid. Each row
    represents one warmup action (e.g. day-1 ``profile_setup``,
    day-7 ``promotional_post``). Status: ``planned`` (default) →
    ``pending_human`` (HITL queued) | ``in_flight`` → ``completed``
    | ``failed`` | ``skipped``. ``day_offset`` is relative to the
    egg's ``laid_at`` so the action plan is a pure function of the
    egg row + the canonical 7-day curve.

Phase 2 forward-compat
----------------------

- ``owner_org_id`` defaults to ``'madfam'`` so Phase 1 rows carry the
  founder-org tag without needing a multi-tenant context. Phase 2
  scopes by tenant via Janua claims; the column already exists +
  is indexed.
- ``metadata`` JSONB on each egg lets new platforms tack on
  platform-specific fields (TikTok caption defaults, YouTube
  channel id, etc.) without an ALTER TABLE.
- ``content_brief`` field is reserved on the action row for the
  Phase 2 content-generator service that will pre-populate copy.

Idempotency: ``IF NOT EXISTS`` short-circuit via
``inspector.get_table_names()`` so partial-apply or hand-applied
environments don't blow up.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-04
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


_EGGS = "social_account_eggs"
_ACTIONS = "social_account_warmup_actions"


def _has_table(name: str) -> bool:
    """Idempotency helper — same shape as 0029/0031."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type: Any = JSONB() if is_postgres else sa.JSON()
    uuid_type: Any = UUID(as_uuid=True) if is_postgres else sa.String(length=36)

    if not _has_table(_EGGS):
        op.create_table(
            _EGGS,
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("persona_id", sa.String(length=64), nullable=False),
            # Phase 1 scope: 'mastodon' | 'bluesky' | 'reddit'. Stored as
            # plain VARCHAR (not a DB enum) so adding a Phase 2 platform
            # never requires an ALTER TYPE.
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("handle", sa.String(length=255), nullable=False),
            # NULL for non-federated platforms (Bluesky, Reddit). Required
            # for Mastodon-style federation so the worker knows which
            # instance to authenticate against.
            sa.Column("instance_url", sa.String(length=512), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'laid'"),
            ),
            sa.Column(
                "progress",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "laid_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text(
                    "NOW()" if is_postgres else "CURRENT_TIMESTAMP"
                ),
            ),
            sa.Column("hatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("matured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "owner_org_id",
                sa.String(length=255),
                nullable=False,
                server_default=sa.text("'madfam'"),
            ),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column(
                "metadata_",
                json_type,
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text(
                    "NOW()" if is_postgres else "CURRENT_TIMESTAMP"
                ),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text(
                    "NOW()" if is_postgres else "CURRENT_TIMESTAMP"
                ),
            ),
            sa.CheckConstraint(
                "status IN ('laid', 'incubating', 'hatching', "
                "'hatched', 'matured')",
                name="ck_social_account_eggs_status",
            ),
            sa.CheckConstraint(
                "platform IN ('mastodon', 'bluesky', 'reddit')",
                name="ck_social_account_eggs_platform",
            ),
            sa.CheckConstraint(
                "progress >= 0.0 AND progress <= 1.0",
                name="ck_social_account_eggs_progress_bounds",
            ),
            sa.UniqueConstraint(
                "platform",
                "persona_id",
                name="uq_social_account_eggs_platform_persona",
            ),
        )

    if not _has_table(_ACTIONS):
        op.create_table(
            _ACTIONS,
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "egg_id",
                uuid_type,
                sa.ForeignKey(
                    f"{_EGGS}.id",
                    ondelete="CASCADE",
                    name="fk_warmup_actions_egg_id",
                ),
                nullable=False,
            ),
            # 7 action types lifted from the runbook §4.2 curve.
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'planned'"),
            ),
            sa.Column(
                "scheduled_for",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "executed_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column("result", json_type, nullable=True),
            sa.Column("day_offset", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            # Reserved for Phase 2's content-generator service. NULL in
            # Phase 1 — operator composes copy at execute time.
            sa.Column("content_brief", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text(
                    "NOW()" if is_postgres else "CURRENT_TIMESTAMP"
                ),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text(
                    "NOW()" if is_postgres else "CURRENT_TIMESTAMP"
                ),
            ),
            sa.CheckConstraint(
                "status IN ('planned', 'pending_human', 'in_flight', "
                "'completed', 'failed', 'skipped')",
                name="ck_warmup_actions_status",
            ),
            sa.CheckConstraint(
                "action_type IN ('profile_setup', 'follow_curated', "
                "'boost_high_signal', 'reply_substantive', "
                "'original_post_no_link', 'original_post_with_link', "
                "'promotional_post')",
                name="ck_warmup_actions_action_type",
            ),
            sa.CheckConstraint(
                "day_offset >= 1 AND day_offset <= 14",
                name="ck_warmup_actions_day_offset_bounds",
            ),
        )

    inspector = sa.inspect(bind)

    if _has_table(_EGGS):
        existing = {ix["name"] for ix in inspector.get_indexes(_EGGS)}
        # Owner-org filter is the hot path for the Phase 2 multi-tenant
        # listing query and the Phase 1 admin grid.
        if "ix_social_account_eggs_owner_org_id" not in existing:
            op.create_index(
                "ix_social_account_eggs_owner_org_id",
                _EGGS,
                ["owner_org_id"],
            )
        # Status grid filter (e.g. "show me all hatching eggs").
        if "ix_social_account_eggs_status" not in existing:
            op.create_index(
                "ix_social_account_eggs_status",
                _EGGS,
                ["status"],
            )

    if _has_table(_ACTIONS):
        existing = {ix["name"] for ix in inspector.get_indexes(_ACTIONS)}
        # Per-egg timeline — UI loads the action grid for one egg.
        if "ix_warmup_actions_egg_id" not in existing:
            op.create_index(
                "ix_warmup_actions_egg_id",
                _ACTIONS,
                ["egg_id"],
            )
        # Hot-path drain query: ``WHERE status='planned'
        # AND scheduled_for <= NOW()``. Composite ordered for ordered
        # range scan + LIMIT.
        if "ix_warmup_actions_drain" not in existing:
            op.create_index(
                "ix_warmup_actions_drain",
                _ACTIONS,
                ["status", "scheduled_for"],
            )


def downgrade() -> None:
    """Drop indexes + tables. Tolerant of missing objects so a partial
    upgrade can be unwound without a manual SQL fix."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _ACTIONS in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes(_ACTIONS)}
        for ix_name in ("ix_warmup_actions_egg_id", "ix_warmup_actions_drain"):
            if ix_name in existing:
                op.drop_index(ix_name, table_name=_ACTIONS)
        op.drop_table(_ACTIONS)

    if _EGGS in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes(_EGGS)}
        for ix_name in (
            "ix_social_account_eggs_owner_org_id",
            "ix_social_account_eggs_status",
        ):
            if ix_name in existing:
                op.drop_index(ix_name, table_name=_EGGS)
        op.drop_table(_EGGS)
