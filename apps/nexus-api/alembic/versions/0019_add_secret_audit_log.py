"""Add append-only secret_audit_log for RFC 0005 k8s Secret writes.

Feature: RFC 0005 Sprint 1a — Selva K8s secret-management capability.

- ``secret_audit_log`` — append-only row per write attempt. Records
  agent_id, actor_user_sub, target cluster/namespace/secret/key,
  operation type, the 8-hex-char SHA-256 prefix of the value (NEVER
  the value), source provenance, rationale, approval chain, and a
  tamper-evidence SHA-256 digest (``signature_sha256``) over the row's
  identifying fields (pattern cribbed from migration 0018's
  ``consent_ledger``).
- UPDATE and DELETE are revoked from the app role at the DB level so
  corrections land as new rows with ``rollback_of_id`` set, never as
  mutations.

The value itself is NOT in the migration. It never enters the
database — only the 8-char hash prefix does. See RFC 0005 §"Audit trail".

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


ALLOWED_OPERATIONS = ("create", "update", "rotate", "delete")
ALLOWED_STATUSES = (
    "pending_approval",
    "approved",
    "denied",
    "applied",
    "failed",
    "rolled_back",
)


def upgrade() -> None:
    op.create_table(
        "secret_audit_log",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Actors
        sa.Column(
            "agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("actor_user_sub", sa.String(255), nullable=True),
        # Target — (cluster, namespace, secret_name, key) is the
        # natural key for idempotency queries.
        sa.Column("target_cluster", sa.String(64), nullable=False),
        sa.Column("target_namespace", sa.String(255), nullable=False),
        sa.Column("target_secret_name", sa.String(255), nullable=False),
        sa.Column("target_key", sa.String(255), nullable=False),
        # Write intent + hash prefix
        sa.Column("operation", sa.String(16), nullable=False),
        # Exactly 8 hex chars — enforced by CHECK constraint below.
        sa.Column("value_sha256_prefix", sa.String(8), nullable=False),
        sa.Column("predecessor_sha256_prefix", sa.String(8), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        # Approval chain
        sa.Column(
            "approval_request_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "approval_chain",
            sa.dialects.postgresql.JSON,
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        # Lifecycle
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "rollback_of_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Tamper-evidence
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "operation IN ('create', 'update', 'rotate', 'delete')",
            name="ck_secret_audit_operation",
        ),
        sa.CheckConstraint(
            (
                "status IN ('pending_approval', 'approved', 'denied', "
                "'applied', 'failed', 'rolled_back')"
            ),
            name="ck_secret_audit_status",
        ),
        sa.CheckConstraint(
            "char_length(value_sha256_prefix) = 8",
            name="ck_secret_audit_sha_prefix_len",
        ),
        sa.CheckConstraint(
            ("predecessor_sha256_prefix IS NULL OR char_length(predecessor_sha256_prefix) = 8"),
            name="ck_secret_audit_pred_prefix_len",
        ),
    )
    op.create_index(
        "ix_secret_audit_target",
        "secret_audit_log",
        [
            "target_cluster",
            "target_namespace",
            "target_secret_name",
            "target_key",
        ],
    )
    op.create_index(
        "ix_secret_audit_created",
        "secret_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_secret_audit_approval",
        "secret_audit_log",
        ["approval_request_id"],
    )

    # Revoke UPDATE and DELETE from the app role so the ledger is
    # strictly append-only. Same pattern as migration 0018 for
    # consent_ledger.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            REVOKE UPDATE, DELETE ON secret_audit_log FROM selva_app;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            GRANT UPDATE, DELETE ON secret_audit_log TO selva_app;
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_secret_audit_approval", table_name="secret_audit_log")
    op.drop_index("ix_secret_audit_created", table_name="secret_audit_log")
    op.drop_index("ix_secret_audit_target", table_name="secret_audit_log")
    op.drop_table("secret_audit_log")
