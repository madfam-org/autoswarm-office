"""Add hitl_decisions + hitl_confidence for HITL Sprint 1 (observe-only).

Feature: HITL autonomy-confidence ladder, Sprint 1. Records every HITL
approve/deny/modify decision and rolls a Beta(α,β) posterior per
(agent, action_category, org, context_signature) bucket. Sprint 1 is
observe-only — the permission engine still returns ASK for every bucket.

- ``hitl_decisions`` — append-only event log. Never updated. Downstream
  signals (revert / complaint) land as new rows that reference the
  original via ``parent_decision_id``. Payloads are NEVER stored — only
  8-char hash prefixes for post-hoc audit correlation.
- ``hitl_confidence`` — rolling per-bucket state, derived from the
  decision log. Primary key is ``bucket_key`` (sha256 of
  agent_id:action_category:org_id:context_signature). Can be rebuilt
  at any time by replaying the decision log. ``locked_until`` is unused
  in Sprint 1 but present on the schema so Sprint 2's demotion path
  doesn't need another migration.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


HITL_OUTCOMES = (
    "approved_clean",
    "approved_modified",
    "rejected",
    "timeout",
    "downstream_reverted",
)

HITL_TIERS = (
    "ask",
    "ask_quiet",
    "allow_shadow",
    "allow",
)


def upgrade() -> None:
    hitl_outcome = sa.dialects.postgresql.ENUM(
        *HITL_OUTCOMES,
        name="hitloutcome",
        create_type=False,
    )
    hitl_tier = sa.dialects.postgresql.ENUM(
        *HITL_TIERS,
        name="hitlconfidencetier",
        create_type=False,
    )
    hitl_outcome.create(op.get_bind(), checkfirst=True)
    hitl_tier.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "hitl_decisions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("bucket_key", sa.String(64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("action_category", sa.String(50), nullable=False),
        sa.Column("org_id", sa.String(255), nullable=False, index=True),
        sa.Column("context_signature", sa.String(64), nullable=False),
        sa.Column(
            "context_signature_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("approver_id", sa.String(255), nullable=True),
        sa.Column("outcome", hitl_outcome, nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("diff_hash", sa.String(64), nullable=True),
        sa.Column(
            "parent_decision_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hitl_decisions.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_hitl_decisions_bucket_decided",
        "hitl_decisions",
        ["bucket_key", "decided_at"],
    )
    op.create_index(
        "ix_hitl_decisions_agent_cat",
        "hitl_decisions",
        ["agent_id", "action_category"],
    )

    op.create_table(
        "hitl_confidence",
        sa.Column("bucket_key", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("action_category", sa.String(50), nullable=False),
        sa.Column("org_id", sa.String(255), nullable=False, index=True),
        sa.Column("context_signature", sa.String(64), nullable=False),
        sa.Column(
            "context_signature_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("n_observed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_approved_clean", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_approved_modified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_timeout", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_reverted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("beta_alpha", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("beta_beta", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("tier", hitl_tier, nullable=False, server_default="ask"),
        sa.Column("last_promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_hitl_confidence_agent_cat",
        "hitl_confidence",
        ["agent_id", "action_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_hitl_confidence_agent_cat", table_name="hitl_confidence")
    op.drop_table("hitl_confidence")
    op.drop_index("ix_hitl_decisions_agent_cat", table_name="hitl_decisions")
    op.drop_index("ix_hitl_decisions_bucket_decided", table_name="hitl_decisions")
    op.drop_table("hitl_decisions")

    sa.Enum(name="hitlconfidencetier").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="hitloutcome").drop(op.get_bind(), checkfirst=True)
