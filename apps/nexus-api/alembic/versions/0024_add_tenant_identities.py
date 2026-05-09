"""Add tenant_identities — the cross-service tenant id map.

Backs the Phase 2 tenant_identity tools (``tenant_create_identity_record``,
``tenant_resolve``, ``tenant_validate_consistency``). Every onboarded
MADFAM tenant has identities across Janua / Dhanam / PhyndCRM / Karafiel /
Resend / Cloudflare / Selva Office; this table is the canonical map so
reconciliation + offboarding can enumerate every place a tenant holds
state without having to poll each service. Canonical id is the Janua
org_id.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("canonical_id", sa.String(128), nullable=False, unique=True),
        sa.Column("legal_name", sa.String(512), nullable=False),
        sa.Column("primary_contact_email", sa.String(320), nullable=True),
        sa.Column("janua_org_id", sa.String(128), nullable=True),
        sa.Column("dhanam_space_id", sa.String(128), nullable=True),
        sa.Column("phyndcrm_tenant_id", sa.String(128), nullable=True),
        sa.Column("karafiel_org_id", sa.String(128), nullable=True),
        sa.Column("resend_domain_ids", JSON, nullable=True),
        sa.Column("cloudflare_zone_ids", JSON, nullable=True),
        sa.Column("selva_office_seat_ids", JSON, nullable=True),
        sa.Column("r2_bucket_names", JSON, nullable=True),
        sa.Column("meta", JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_tenant_identities_canonical_id",
        "tenant_identities",
        ["canonical_id"],
        unique=True,
    )
    op.create_index(
        "ix_tenant_identities_janua_org_id",
        "tenant_identities",
        ["janua_org_id"],
    )
    op.create_index(
        "ix_tenant_identities_dhanam_space_id",
        "tenant_identities",
        ["dhanam_space_id"],
    )
    op.create_index(
        "ix_tenant_identities_phyndcrm_tenant_id",
        "tenant_identities",
        ["phyndcrm_tenant_id"],
    )
    op.create_index(
        "ix_tenant_identities_karafiel_org_id",
        "tenant_identities",
        ["karafiel_org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_identities_karafiel_org_id", table_name="tenant_identities")
    op.drop_index("ix_tenant_identities_phyndcrm_tenant_id", table_name="tenant_identities")
    op.drop_index("ix_tenant_identities_dhanam_space_id", table_name="tenant_identities")
    op.drop_index("ix_tenant_identities_janua_org_id", table_name="tenant_identities")
    op.drop_index("ix_tenant_identities_canonical_id", table_name="tenant_identities")
    op.drop_table("tenant_identities")
