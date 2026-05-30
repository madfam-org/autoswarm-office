"""Alembic migration: add session_checkpoints table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-14

Note: approval_requests table already exists from migration 0000.
Only session_checkpoints (used by checkpoints.py) was missing.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── session_checkpoints (Checkpoint/Rollback support) ───────────────
    op.create_table(
        "session_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(255), nullable=False, index=True),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("phase_index", sa.Integer, nullable=False),
        sa.Column("state_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_index("ix_session_checkpoints_run_id", table_name="session_checkpoints")
    op.drop_table("session_checkpoints")
