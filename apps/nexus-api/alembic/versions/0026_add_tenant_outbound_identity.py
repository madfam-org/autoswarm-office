"""Add first-class outbound identity columns on tenant_configs.

Closes the regression introduced by the v2.2.x email From: lockdown
(commit b72399e). Today the email tools resolve outbound identity by
joining ``tenant_configs.brand_name`` / ``razon_social`` to
``tenant_identities`` because dedicated columns did not exist. New
tenants who haven't manually populated ``tenant_identities`` see email
sends refuse with ``"Tenant outbound identity not configured"`` —
silent breakage of the email feature.

These three columns let tenants configure outbound identity from the
office UI without ops intervention. All nullable so existing rows
continue to work unchanged; the email lockdown's existing fallback
chain (brand_name → legal_name → razon_social →
tenant_identities.primary_contact_email) handles ``None`` on any of
the new columns by falling through to the legacy resolver.

Idempotent ADD COLUMN — safe to re-run.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_configs",
        sa.Column("outbound_user_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("outbound_user_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("outbound_agent_slug", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_configs", "outbound_agent_slug")
    op.drop_column("tenant_configs", "outbound_user_name")
    op.drop_column("tenant_configs", "outbound_user_email")
