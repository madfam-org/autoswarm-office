"""Add org_id column to all tables for multi-tenancy.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("departments", "agents", "approval_requests", "swarm_tasks", "compute_token_ledger"):
        op.add_column(
            table,
            sa.Column("org_id", sa.String(255), nullable=False, server_default="default"),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def downgrade() -> None:
    for table in ("departments", "agents", "approval_requests", "swarm_tasks", "compute_token_ledger"):
        op.drop_index(f"ix_{table}_org_id", table)
        op.drop_column(table, "org_id")
