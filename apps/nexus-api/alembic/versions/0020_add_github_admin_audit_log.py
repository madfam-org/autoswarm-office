"""Add append-only github_admin_audit_log for RFC 0006 Sprint 1.

Feature: RFC 0006 Sprint 1 -- Selva github_admin.* tool family.

- ``github_admin_audit_log`` -- append-only row per admin operation
  attempt against the GitHub API. Records agent_id, actor_user_sub,
  operation, target org/repo/team, the JSON request body (safe to log
  -- tool contract guarantees no PAT ever lives here), a structured
  response_summary (diff of members added/removed, rule fields changed),
  rationale, approval chain, and a tamper-evidence SHA-256 signature
  over the row's identifying fields (same pattern as migration 0019).
- ``token_sha256_prefix`` captures the first 8 hex chars of the PAT
  used for the API call. Lets auditors correlate a specific row to a
  specific rotation window without storing the PAT itself.
- UPDATE and DELETE are REVOKEd from the app role at the DB level so
  corrections land as new rows with ``rollback_of_id`` set, never as
  in-place mutations.

The PAT itself is NEVER stored. Only the 8-char hash prefix crosses
this migration's boundary. See RFC 0006 Sprint 1 "Audit trail".

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


# Operations are the RFC 0006 v0.1 tool surface: 3 mutating + 1 read.
ALLOWED_OPERATIONS = (
    "create_team",
    "set_team_membership",
    "set_branch_protection",
    "audit_team_membership",
)

# Status lifecycle mirrors secret_audit_log exactly so the approval
# queue consumer can share plumbing across both audit tables.
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
        "github_admin_audit_log",
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
        # Actors -- same shape as secret_audit_log.
        sa.Column(
            "agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("actor_user_sub", sa.String(255), nullable=True),
        # Operation + target identifying fields. (org, repo, team_slug) is
        # the natural key for drift-detection queries. repo is null for
        # team-level ops; team_slug is null for repo-level ops.
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("target_org", sa.String(255), nullable=False),
        sa.Column("target_repo", sa.String(255), nullable=True),
        sa.Column("target_team_slug", sa.String(255), nullable=True),
        sa.Column("target_branch", sa.String(255), nullable=True),
        # Exactly 8 hex chars of SHA-256(PAT). CHECK constraint enforced
        # below. Safe to log: 8 hex chars = 32 bits, not brute-forceable
        # back to the PAT, but enough to correlate to a rotation window.
        sa.Column("token_sha256_prefix", sa.String(8), nullable=False),
        # Full tool call input (safe -- contract says no PAT in here).
        sa.Column(
            "request_body",
            sa.dialects.postgresql.JSON,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        # Structured diff of the apply step -- which members were added
        # or removed, which protection rule fields changed, etc.
        sa.Column(
            "response_summary",
            sa.dialects.postgresql.JSON,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("rationale", sa.Text, nullable=False),
        # Correlation / request id -- lets operators grep logs for a
        # specific approval queue entry.
        sa.Column("request_id", sa.String(64), nullable=True),
        # Approval chain + lifecycle.
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
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "rollback_of_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        # Tamper-evidence -- SHA-256 over the row's identifying fields,
        # verified at audit time (see audit.github_admin_audit.verify_signature).
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            (
                "operation IN ('create_team', 'set_team_membership', "
                "'set_branch_protection', 'audit_team_membership')"
            ),
            name="ck_github_admin_audit_operation",
        ),
        sa.CheckConstraint(
            (
                "status IN ('pending_approval', 'approved', 'denied', "
                "'applied', 'failed', 'rolled_back')"
            ),
            name="ck_github_admin_audit_status",
        ),
        sa.CheckConstraint(
            "char_length(token_sha256_prefix) = 8",
            name="ck_github_admin_audit_token_prefix_len",
        ),
    )
    op.create_index(
        "ix_github_admin_audit_target",
        "github_admin_audit_log",
        ["target_org", "target_repo", "target_team_slug"],
    )
    op.create_index(
        "ix_github_admin_audit_created",
        "github_admin_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_github_admin_audit_approval",
        "github_admin_audit_log",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_github_admin_audit_operation",
        "github_admin_audit_log",
        ["operation", "created_at"],
    )

    # Revoke UPDATE and DELETE from the app role -- strictly append-only.
    # Identical pattern to migrations 0018 (consent_ledger) and 0019
    # (secret_audit_log).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
            REVOKE UPDATE, DELETE ON github_admin_audit_log FROM selva_app;
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
            GRANT UPDATE, DELETE ON github_admin_audit_log TO selva_app;
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_github_admin_audit_operation", table_name="github_admin_audit_log")
    op.drop_index("ix_github_admin_audit_approval", table_name="github_admin_audit_log")
    op.drop_index("ix_github_admin_audit_created", table_name="github_admin_audit_log")
    op.drop_index("ix_github_admin_audit_target", table_name="github_admin_audit_log")
    op.drop_table("github_admin_audit_log")
