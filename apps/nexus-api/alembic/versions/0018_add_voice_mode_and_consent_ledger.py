"""Add voice_mode to tenant_configs + append-only consent_ledger table.

Feature: Outbound Voice Mode (First-Run Configuration).

- tenant_configs.voice_mode — nullable VARCHAR(32), constrained to
  the 3 modes. NULL = onboarding incomplete; no outbound sends
  allowed until it's set.
- consent_ledger — append-only table recording every voice-mode
  selection with the signer's identity, IP, typed confirmation,
  and an integrity hash. UPDATE/DELETE are revoked from the app
  role at the DB level.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


VOICE_MODES = ("user_direct", "dyad_selva_plus_user", "agent_identified")


def upgrade() -> None:
    # 1. Add voice_mode column to tenant_configs. Nullable — existing
    #    orgs read as "onboarding incomplete" rather than silently
    #    defaulting to a mode they didn't consent to.
    op.add_column(
        "tenant_configs",
        sa.Column("voice_mode", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_tenant_configs_voice_mode",
        "tenant_configs",
        sa.text(
            "voice_mode IS NULL OR voice_mode IN "
            "('user_direct', 'dyad_selva_plus_user', 'agent_identified')"
        ),
    )

    # 2. Append-only consent ledger.
    op.create_table(
        "consent_ledger",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("user_sub", sa.String(255), nullable=False),
        sa.Column("user_email", sa.String(320), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("clause_version", sa.String(16), nullable=False),
        sa.Column("typed_confirmation", sa.Text, nullable=False),
        sa.Column("signer_ip", sa.String(45), nullable=False),
        sa.Column("signer_user_agent", sa.Text, nullable=True),
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('user_direct', 'dyad_selva_plus_user', 'agent_identified')",
            name="ck_consent_ledger_mode",
        ),
    )
    op.create_index(
        "ix_consent_ledger_org_created",
        "consent_ledger",
        ["org_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_consent_ledger_user",
        "consent_ledger",
        ["user_sub"],
    )

    # 3. Revoke UPDATE + DELETE from the app role so the ledger is
    #    strictly append-only at the DB level. The app role name
    #    follows the Enclii-standard `<service>_app` pattern. If the
    #    role doesn't exist in a dev DB, the REVOKE no-ops under
    #    PostgreSQL 15+.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            REVOKE UPDATE, DELETE ON consent_ledger FROM selva_app;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Rollback is a pure drop. Zero data loss for existing orgs because
    # voice_mode was nullable; onboarding-complete orgs lose their
    # consent history, which is the unavoidable cost of a downgrade
    # here.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            GRANT UPDATE, DELETE ON consent_ledger TO selva_app;
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_consent_ledger_user", table_name="consent_ledger")
    op.drop_index("ix_consent_ledger_org_created", table_name="consent_ledger")
    op.drop_table("consent_ledger")
    op.drop_constraint("ck_tenant_configs_voice_mode", "tenant_configs", type_="check")
    op.drop_column("tenant_configs", "voice_mode")
