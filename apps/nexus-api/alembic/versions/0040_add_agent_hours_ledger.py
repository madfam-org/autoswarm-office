"""Add agent_hours_ledger — Selva's metered agent-hours SKU (Tulana packs).

One immutable row per completed task capturing billable agent-hours
(agent_count * duration / 3600). Dhanam reads this at invoice time for the
Maker/Studio/Enterprise hourly packs. Separate from compute_token_ledger
because the two SKUs bill on different units (tokens vs. agent-hours).

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_TABLE = "agent_hours_ledger"


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("swarm_tasks.id"),
            nullable=True,
        ),
        sa.Column("graph_type", sa.String(50), nullable=True),
        sa.Column("agent_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agent_hours", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("task_id", name="uq_agent_hours_task"),
    )
    op.create_index("ix_agent_hours_ledger_org_id", _TABLE, ["org_id"])
    op.create_index("ix_agent_hours_ledger_task_id", _TABLE, ["task_id"])
    op.create_index("ix_agent_hours_org_created", _TABLE, ["org_id", "created_at"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    op.drop_index("ix_agent_hours_org_created", table_name=_TABLE)
    op.drop_index("ix_agent_hours_ledger_task_id", table_name=_TABLE)
    op.drop_index("ix_agent_hours_ledger_org_id", table_name=_TABLE)
    op.drop_table(_TABLE)
