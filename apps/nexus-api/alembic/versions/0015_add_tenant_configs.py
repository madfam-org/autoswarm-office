"""Add tenant_configs table for multi-tenant enterprise provisioning.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_configs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("org_id", sa.String(255), unique=True, nullable=False),
        # Business identity
        sa.Column("rfc", sa.String(13), nullable=True),
        sa.Column("razon_social", sa.String(500), nullable=True),
        sa.Column("regimen_fiscal", sa.String(10), nullable=True),
        # Localization
        sa.Column("locale", sa.String(10), nullable=False, server_default="es-MX"),
        sa.Column(
            "timezone",
            sa.String(50),
            nullable=False,
            server_default="America/Mexico_City",
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
        # Ecosystem integration
        sa.Column("karafiel_org_id", sa.String(255), nullable=True),
        sa.Column("dhanam_space_id", sa.String(255), nullable=True),
        sa.Column("phynd_tenant_id", sa.String(255), nullable=True),
        # Feature flags
        sa.Column("cfdi_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "intelligence_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Resource limits
        sa.Column("max_agents", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_daily_tasks", sa.Integer, nullable=False, server_default="100"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenant_configs_org_id", "tenant_configs", ["org_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tenant_configs_org_id", "tenant_configs")
    op.drop_table("tenant_configs")
