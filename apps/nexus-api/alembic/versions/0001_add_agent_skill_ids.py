"""Add skill_ids column to agents table.

Revision ID: 0001
Revises:
Create Date: 2026-03-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("skill_ids", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "skill_ids")
