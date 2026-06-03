"""Add append-only configmap_audit_log for RFC 0007 Sprint 1 ConfigMap writes.

Feature: RFC 0007 Sprint 1 -- Selva ``config.*`` tool family.

- ``configmap_audit_log`` -- append-only row per ConfigMap read/write/
  delete/list attempt. Records agent_id, actor_user_sub, target
  cluster/namespace/configmap/key, operation type, the 8-hex-char
  SHA-256 prefix of the stringified value AND the predecessor value
  (so a diff is reconstructible for forensic review without storing
  plaintext), rationale, approval chain, HITL level enforced, and a
  tamper-evidence SHA-256 signature over the row's identifying fields
  (pattern cribbed from migration 0019's ``secret_audit_log``).
- UPDATE and DELETE are REVOKEd from the app role at the DB level so
  corrections land as new rows with ``rollback_of_id`` set, never as
  in-place mutations.

ConfigMaps are less sensitive than Secrets -- ConfigMap values are
human-readable config (feature flags, URLs, tunables) -- but they
still change production behaviour (FEATURE_CFDI_AUTO_ISSUE flips,
routing table swaps) so the audit trail matches Secrets in shape
while NOT storing the plaintext itself. Only the SHA-256 prefix
crosses this migration's boundary. RFC 0007 v0.1 chose this over
storing plaintext because ConfigMaps can carry semi-sensitive data
(service hostnames, internal DNS names, webhook URLs) that we don't
want to leak via an audit-table exfil.

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17

Note: on this branch (feat/rfc-0007-sprint-1-config-tools) we're based on
main, which only has migrations through 0019. If RFC 0006's own 0020
migration lands first, this will need to be re-chained to 0021 at merge
time. That's a conflict-resolution problem, not a design problem.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


# The RFC 0007 Sprint 1 tool surface is 4 operations:
#   - read_configmap     (read-only, ALLOW everywhere)
#   - set_configmap_value (write; dev=ALLOW, staging=ASK, prod=ASK)
#   - delete_configmap_key (write; dev=ALLOW, staging=ASK, prod=ASK)
#   - list_configmaps    (read-only, ALLOW everywhere)
ALLOWED_OPERATIONS = ("read", "write", "delete", "list")
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
        "configmap_audit_log",
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
        sa.Column("request_id", sa.String(64), nullable=True),
        # Target -- (cluster, namespace, configmap_name, key) is the
        # natural key for drift audits and idempotency queries.
        sa.Column("target_cluster", sa.String(64), nullable=False),
        sa.Column("target_namespace", sa.String(255), nullable=False),
        sa.Column("target_configmap_name", sa.String(255), nullable=False),
        # key is nullable because list/read operations aren't key-scoped.
        sa.Column("target_key", sa.String(255), nullable=True),
        # Write intent + hash prefixes
        sa.Column("operation", sa.String(16), nullable=False),
        # Exactly 8 hex chars when present -- enforced by CHECK below.
        # Nullable because read/list/delete ops may not have a value.
        sa.Column("value_sha256_prefix", sa.String(8), nullable=True),
        # Predecessor value hash prefix -- lets forensics reconstruct a
        # diff without storing plaintext values on either side.
        sa.Column("previous_value_sha256_prefix", sa.String(8), nullable=True),
        sa.Column("rationale", sa.Text, nullable=False),
        # HITL level enforced for this operation (allow/ask/ask_dual).
        sa.Column("hitl_level", sa.String(16), nullable=False),
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
            "operation IN ('read', 'write', 'delete', 'list')",
            name="ck_configmap_audit_operation",
        ),
        sa.CheckConstraint(
            (
                "status IN ('pending_approval', 'approved', 'denied', "
                "'applied', 'failed', 'rolled_back')"
            ),
            name="ck_configmap_audit_status",
        ),
        sa.CheckConstraint(
            "hitl_level IN ('allow', 'ask', 'ask_dual')",
            name="ck_configmap_audit_hitl_level",
        ),
        sa.CheckConstraint(
            ("value_sha256_prefix IS NULL OR char_length(value_sha256_prefix) = 8"),
            name="ck_configmap_audit_sha_prefix_len",
        ),
        sa.CheckConstraint(
            (
                "previous_value_sha256_prefix IS NULL OR "
                "char_length(previous_value_sha256_prefix) = 8"
            ),
            name="ck_configmap_audit_prev_prefix_len",
        ),
    )
    op.create_index(
        "ix_configmap_audit_target",
        "configmap_audit_log",
        [
            "target_cluster",
            "target_namespace",
            "target_configmap_name",
            "target_key",
        ],
    )
    op.create_index(
        "ix_configmap_audit_created",
        "configmap_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_configmap_audit_approval",
        "configmap_audit_log",
        ["approval_request_id"],
    )

    # Revoke UPDATE and DELETE from the app role so the ledger is
    # strictly append-only. Same pattern as migration 0019 for
    # secret_audit_log and 0018 for consent_ledger.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            REVOKE UPDATE, DELETE ON configmap_audit_log FROM selva_app;
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
            GRANT UPDATE, DELETE ON configmap_audit_log TO selva_app;
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_configmap_audit_approval", table_name="configmap_audit_log")
    op.drop_index("ix_configmap_audit_created", table_name="configmap_audit_log")
    op.drop_index("ix_configmap_audit_target", table_name="configmap_audit_log")
    op.drop_table("configmap_audit_log")
