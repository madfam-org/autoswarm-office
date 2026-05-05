"""Add ``scheduled_actions`` — instance-level due-row queue for the
scheduled action executor (initially the SOCIAL_POST executor).

The existing ``schedules`` table (migration 0001-era) holds *recurring
templates* keyed by cron expression. It does not carry a ``status``,
``scheduled_for``, or ``retry_count``, and a single row represents the
schedule itself, not a single fire of it. The audit at
``docs/...`` flagged that ``ScheduledAction.SOCIAL_POST`` had no
executor draining due rows — the missing piece was a per-fire instance
table the executor can ``SELECT ... FOR UPDATE SKIP LOCKED`` against.

This migration adds that table. The relationship is
``schedules`` (template) ──fires──▶ ``scheduled_actions`` (instances).
The recurring scheduler that materializes cron rows into
``scheduled_actions`` rows lives outside this PR — for the SOCIAL_POST
MVP, callers (campaign code, manual ops) will INSERT directly. A
follow-up will wire the cron-to-instance materializer.

Columns:

- ``id`` UUID PK.
- ``action_type`` VARCHAR(64) NOT NULL — matches the
  ``ScheduledAction`` enum string value (e.g. ``"social_post"``,
  ``"acp_initiate"``, ...). Stored as plain VARCHAR rather than a DB
  enum so adding a new ``ScheduledAction`` value never requires a DB
  migration to ALTER the type.
- ``scheduled_for`` TIMESTAMPTZ NOT NULL — earliest UTC instant the
  executor may dispatch this row. Indexed for the hot-path
  ``WHERE scheduled_for <= NOW()`` scan.
- ``status`` VARCHAR(16) NOT NULL DEFAULT ``'pending'`` — one of
  ``pending`` | ``in_flight`` | ``completed`` | ``failed`` |
  ``dead_letter``. CHECK-constrained at the DB layer; the executor
  also validates app-side (defense in depth). ``in_flight`` is the
  claim state used by ``FOR UPDATE SKIP LOCKED`` — multiple worker
  pods racing the same drain will each claim a disjoint slice.
- ``payload`` JSONB NOT NULL DEFAULT ``'{}'`` — action-specific
  parameters. For SOCIAL_POST: ``{platform: "mastodon"|"bluesky"|
  "reddit"|"email", instance/subreddit/persona_id, status/title/body, ...}``.
- ``retry_count`` INTEGER NOT NULL DEFAULT 0 — incremented on each
  transient failure (non-rate-limit). ``max_retries`` defaults to 3;
  once ``retry_count >= max_retries`` the row transitions to
  ``dead_letter`` so ops can inspect via a follow-up dashboard.
- ``max_retries`` INTEGER NOT NULL DEFAULT 3.
- ``last_error`` TEXT NULL — last failure message, truncated to 1024
  chars by the executor before write. Useful for ops triage; never
  carries credentials because the underlying tools sanitize their
  errors before returning them.
- ``playbook_id`` VARCHAR(255) NULL — when set, the executor checks
  ``hitl_status`` BEFORE dispatch. NULL means "no playbook gate" —
  the executor proceeds (the underlying social tool's HITL
  ASK-level gate still fires per its own policy).
- ``hitl_status`` VARCHAR(16) NULL — one of ``approved`` | ``denied``
  | ``pending``. Only inspected when ``playbook_id`` is set. The
  executor SKIPS rows with ``playbook_id IS NOT NULL AND hitl_status
  != 'approved'`` — they stay ``pending`` until an approver flips
  ``hitl_status`` to ``approved`` (or ``denied``, in which case a
  follow-up admin path will mark the row ``failed``).
- ``persona_id`` VARCHAR(64) NULL — Selva persona id used for
  PostHog attribution + per-persona rate-limit keys in the
  bluesky/reddit tools. NULL falls back to ``"default"``.
- ``org_id`` VARCHAR(255) NOT NULL — tenant scope. Indexed so a
  per-tenant drain query (``WHERE org_id = $1 AND ...``) is cheap.
- ``created_at`` TIMESTAMPTZ NOT NULL DEFAULT NOW().
- ``updated_at`` TIMESTAMPTZ NOT NULL DEFAULT NOW() — touched on
  every state transition.
- ``started_at`` / ``completed_at`` TIMESTAMPTZ NULL — observability
  timestamps for the dispatch latency histogram.

Indexes:

- ``ix_scheduled_actions_drain`` ``(action_type, status, scheduled_for)``
  — composite for the executor's drain query. Orders by the
  ``scheduled_for`` tail of the index so the planner can do an
  ordered range scan + LIMIT 50 without a separate sort.
- ``ix_scheduled_actions_org_id`` ``(org_id)``.

Idempotency: ``IF NOT EXISTS`` short-circuit via ``inspector.get_table_names()``
so partial-apply or hand-applied environments don't blow up.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-04
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


_TABLE = "scheduled_actions"


def _has_table(name: str) -> bool:
    """Idempotency helper — same shape as 0029."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table(_TABLE):
        # ``JSONB`` on Postgres, ``JSON`` on SQLite (test runners).
        # ``op.get_context().dialect.name`` lets us pick the right type
        # without a noisy try/except — SQLite doesn't have JSONB and
        # silently downcasting to TEXT would lose round-trip semantics.
        bind = op.get_bind()
        is_postgres = bind.dialect.name == "postgresql"
        # The TypeEngine union widens to ``object`` under mypy without an
        # explicit annotation; we don't actually need full type fidelity
        # here — Alembic only invokes ``compile()`` on the engine — so an
        # ``Any`` cast at the binding line keeps the column declarations
        # readable.
        json_type: Any = JSONB() if is_postgres else sa.JSON()
        uuid_type: Any = UUID(as_uuid=True) if is_postgres else sa.String(length=36)

        op.create_table(
            _TABLE,
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("action_type", sa.String(length=64), nullable=False),
            sa.Column(
                "scheduled_for",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column(
                "payload",
                json_type,
                nullable=False,
                server_default=sa.text("'{}'") if is_postgres else sa.text("'{}'"),
            ),
            sa.Column(
                "retry_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "max_retries",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("3"),
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("playbook_id", sa.String(length=255), nullable=True),
            sa.Column("hitl_status", sa.String(length=16), nullable=True),
            sa.Column("persona_id", sa.String(length=64), nullable=True),
            sa.Column("org_id", sa.String(length=255), nullable=False),
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
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'in_flight', 'completed', "
                "'failed', 'dead_letter')",
                name="ck_scheduled_actions_status",
            ),
            sa.CheckConstraint(
                "hitl_status IS NULL OR hitl_status IN "
                "('approved', 'denied', 'pending')",
                name="ck_scheduled_actions_hitl_status",
            ),
            sa.CheckConstraint(
                "retry_count >= 0",
                name="ck_scheduled_actions_retry_count_non_negative",
            ),
            sa.CheckConstraint(
                "max_retries >= 0",
                name="ck_scheduled_actions_max_retries_non_negative",
            ),
        )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}

    # Composite index ordered for the executor's drain query:
    # ``WHERE action_type = $1 AND status = 'pending'
    #   AND scheduled_for <= NOW() ORDER BY scheduled_for LIMIT 50``.
    # Equality on the prefix columns + range on the tail is exactly
    # what a B-tree composite excels at.
    if "ix_scheduled_actions_drain" not in existing_indexes:
        op.create_index(
            "ix_scheduled_actions_drain",
            _TABLE,
            ["action_type", "status", "scheduled_for"],
        )

    if "ix_scheduled_actions_org_id" not in existing_indexes:
        op.create_index(
            "ix_scheduled_actions_org_id",
            _TABLE,
            ["org_id"],
        )


def downgrade() -> None:
    """Drop indexes + table. Tolerant of missing objects so a partial
    upgrade can be unwound without a manual SQL fix."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE in inspector.get_table_names():
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        for ix_name in ("ix_scheduled_actions_drain", "ix_scheduled_actions_org_id"):
            if ix_name in existing_indexes:
                op.drop_index(ix_name, table_name=_TABLE)
        op.drop_table(_TABLE)
