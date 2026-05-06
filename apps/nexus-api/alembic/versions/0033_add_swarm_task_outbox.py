"""Add durable outbox for swarm task Redis publication.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


_TABLE = "swarm_task_outbox"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type: Any = JSONB() if is_postgres else sa.JSON()
    uuid_type: Any = UUID(as_uuid=True) if is_postgres else sa.String(length=36)
    now = sa.text("NOW()" if is_postgres else "CURRENT_TIMESTAMP")

    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "task_id",
                uuid_type,
                sa.ForeignKey("swarm_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("org_id", sa.String(length=255), nullable=False),
            sa.Column(
                "stream_name",
                sa.String(length=255),
                nullable=False,
                server_default=sa.text("'autoswarm:task-stream'"),
            ),
            sa.Column("payload", json_type, nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("stream_message_id", sa.String(length=100), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
            sa.CheckConstraint(
                "status IN ('pending', 'retryable', 'sent')",
                name="ck_swarm_task_outbox_status",
            ),
        )

    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if "ix_swarm_task_outbox_due" not in existing:
        op.create_index(
            "ix_swarm_task_outbox_due",
            _TABLE,
            ["status", "next_attempt_at", "created_at"],
        )
    if "ix_swarm_task_outbox_task_id" not in existing:
        op.create_index("ix_swarm_task_outbox_task_id", _TABLE, ["task_id"])


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_index("ix_swarm_task_outbox_task_id", table_name=_TABLE)
        op.drop_index("ix_swarm_task_outbox_due", table_name=_TABLE)
        op.drop_table(_TABLE)
