"""Add minimal deployment evidence ledger.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


_TABLE = "deployment_evidence_records"
_PLATFORM_BYPASS_MARKER = "platform"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _grant_roles() -> None:
    if not _is_postgres():
        return

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO autoswarm_app;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO app_admin;
                END IF;
            END
            $$;
            """
        )
    )


def _enable_rls() -> None:
    if not _is_postgres():
        return

    op.execute(sa.text(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{_TABLE} ON {_TABLE}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY tenant_isolation_{_TABLE} ON {_TABLE}
            FOR ALL
            USING (
                current_setting('app.current_org_id', true) = '{_PLATFORM_BYPASS_MARKER}'
                OR org_id = current_setting('app.current_org_id', true)
            )
            WITH CHECK (
                current_setting('app.current_org_id', true) = '{_PLATFORM_BYPASS_MARKER}'
                OR org_id = current_setting('app.current_org_id', true)
            )
            """
        )
    )


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
            sa.Column("graph_type", sa.String(length=50), nullable=False),
            sa.Column("deployment_status", sa.String(length=50), nullable=False),
            sa.Column("evidence", json_type, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        )

    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if "ix_deployment_evidence_records_task_created" not in existing:
        op.create_index(
            "ix_deployment_evidence_records_task_created",
            _TABLE,
            ["task_id", "created_at"],
        )
    if "ix_deployment_evidence_records_org_created" not in existing:
        op.create_index(
            "ix_deployment_evidence_records_org_created",
            _TABLE,
            ["org_id", "created_at"],
        )

    _grant_roles()
    _enable_rls()


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_index("ix_deployment_evidence_records_org_created", table_name=_TABLE)
        op.drop_index("ix_deployment_evidence_records_task_created", table_name=_TABLE)
        op.drop_table(_TABLE)
