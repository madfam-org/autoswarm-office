"""Add append-only webhook_audit_log for RFC 0008 provider webhook mgmt.

Feature: RFC 0008 Sprint 1 — Selva provider webhook management
(Stripe / Resend / Janua OIDC redirect) tool family.

- ``webhook_audit_log`` — append-only row per tool invocation. Records
  agent_id, actor_user_sub, provider, action, webhook_id (if any), an
  8-hex-char SHA-256 prefix of the endpoint URL (NEVER the URL itself —
  webhook URLs often embed tokens in their paths), the array of events
  registered, an optional FK into ``secret_audit_log`` for the linked
  secret write (forming the two-row audit chain required by RFC 0008
  §"The critical invariant"), a human-readable pointer to the resulting
  K8s Secret (reference only, not the value), approval chain, status,
  and a tamper-evidence SHA-256 digest (``signature_sha256``).
- UPDATE and DELETE are revoked from the app role at the DB level so
  corrections land as new rows, never as mutations. Same pattern as
  migration 0019 for ``secret_audit_log``.

The webhook signing secret itself NEVER reaches the database. It is
captured in worker-process memory for ~100ms at provider-API-response
time and immediately handed to RFC 0005's ``secrets.write_kubernetes_secret``.
Its only on-disk footprint is the ``value_sha256_prefix`` on the linked
``secret_audit_log`` row.

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


ALLOWED_PROVIDERS = ("stripe", "resend", "janua", "phyndcrm", "dhanam", "mifiel", "facturapi")
ALLOWED_ACTIONS = ("create", "list", "delete", "rotate", "register_oidc_redirect")
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
        "webhook_audit_log",
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
        # Target
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("webhook_id", sa.String(255), nullable=True),
        # Exactly 8 hex chars when present — enforced by CHECK below.
        sa.Column("target_url_sha256_prefix", sa.String(8), nullable=True),
        sa.Column(
            "events_registered",
            sa.dialects.postgresql.JSON,
            nullable=True,
        ),
        # Link to the secret_audit_log row for the secret write that
        # captured the provider-returned signing secret (RFC 0008
        # two-row audit chain).
        sa.Column(
            "linked_secret_audit_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Human-readable pointer: "<namespace>/<secret_name>:<key>".
        # NOT the secret value. Safe to surface in operator UIs.
        sa.Column("resulting_secret_name", sa.String(512), nullable=True),
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
        sa.Column("rationale", sa.Text, nullable=False),
        # Lifecycle
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        # Request correlation (for pairing with nexus-api request logs)
        sa.Column("request_id", sa.String(64), nullable=True),
        # Tamper-evidence
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            (
                "provider IN ('stripe', 'resend', 'janua', 'phyndcrm', "
                "'dhanam', 'mifiel', 'facturapi')"
            ),
            name="ck_webhook_audit_provider",
        ),
        sa.CheckConstraint(
            ("action IN ('create', 'list', 'delete', 'rotate', 'register_oidc_redirect')"),
            name="ck_webhook_audit_action",
        ),
        sa.CheckConstraint(
            (
                "status IN ('pending_approval', 'approved', 'denied', "
                "'applied', 'failed', 'rolled_back')"
            ),
            name="ck_webhook_audit_status",
        ),
        sa.CheckConstraint(
            ("target_url_sha256_prefix IS NULL OR char_length(target_url_sha256_prefix) = 8"),
            name="ck_webhook_audit_url_prefix_len",
        ),
        sa.ForeignKeyConstraint(
            ["linked_secret_audit_id"],
            ["secret_audit_log.id"],
            name="fk_webhook_audit_linked_secret",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_webhook_audit_target",
        "webhook_audit_log",
        ["provider", "target_url_sha256_prefix"],
    )
    op.create_index(
        "ix_webhook_audit_created",
        "webhook_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_webhook_audit_approval",
        "webhook_audit_log",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_webhook_audit_webhook_id",
        "webhook_audit_log",
        ["provider", "webhook_id"],
    )

    # Revoke UPDATE and DELETE from the app role so the ledger is
    # strictly append-only. Same pattern as migration 0019.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
            REVOKE UPDATE, DELETE ON webhook_audit_log FROM autoswarm_app;
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
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
            GRANT UPDATE, DELETE ON webhook_audit_log TO autoswarm_app;
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_webhook_audit_webhook_id", table_name="webhook_audit_log")
    op.drop_index("ix_webhook_audit_approval", table_name="webhook_audit_log")
    op.drop_index("ix_webhook_audit_created", table_name="webhook_audit_log")
    op.drop_index("ix_webhook_audit_target", table_name="webhook_audit_log")
    op.drop_table("webhook_audit_log")
