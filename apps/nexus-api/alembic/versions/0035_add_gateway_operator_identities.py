"""Add Harness gateway operator identities.

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


_TABLE = "gateway_operator_identities"
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
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO selva_app;
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
    uuid_type: Any = UUID(as_uuid=True) if is_postgres else sa.String(length=36)
    now = sa.text("NOW()" if is_postgres else "CURRENT_TIMESTAMP")

    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("org_id", sa.String(length=255), nullable=False),
            sa.Column("channel", sa.String(length=80), nullable=False),
            sa.Column("external_subject", sa.String(length=255), nullable=False),
            sa.Column("user_sub", sa.String(length=255), nullable=False),
            sa.Column("user_email", sa.String(length=320), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
            sa.UniqueConstraint(
                "channel",
                "external_subject",
                name="uq_gateway_operator_identities_channel_subject",
            ),
        )

    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if "ix_gateway_operator_identities_org_id" not in existing:
        op.create_index("ix_gateway_operator_identities_org_id", _TABLE, ["org_id"])
    if "ix_gateway_operator_identities_channel" not in existing:
        op.create_index("ix_gateway_operator_identities_channel", _TABLE, ["channel"])
    if "ix_gateway_operator_identities_org_channel" not in existing:
        op.create_index(
            "ix_gateway_operator_identities_org_channel",
            _TABLE,
            ["org_id", "channel"],
        )

    _grant_roles()
    _enable_rls()


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_index("ix_gateway_operator_identities_org_channel", table_name=_TABLE)
        op.drop_index("ix_gateway_operator_identities_channel", table_name=_TABLE)
        op.drop_index("ix_gateway_operator_identities_org_id", table_name=_TABLE)
        op.drop_table(_TABLE)
