"""Grant runtime DB role access to migration-owned tables.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


# Production currently connects as ``selva``. Older migrations assumed
# the Enclii-standard ``selva_app`` role, so keep both to support fresh
# databases and the live database we are stabilizing.
_APP_ROLES = ("selva", "selva_app")

_READ_WRITE_TABLES = (
    "deployment_evidence_records",
    "external_a2a_callers",
    "gateway_operator_identities",
    "hitl_confidence",
    "hitl_decisions",
    "scheduled_actions",
    "social_account_eggs",
    "social_account_warmup_actions",
    "swarm_task_outbox",
    "task_comments",
    "task_history",
    "tenant_configs",
    "tenant_identities",
)

_APPEND_ONLY_TABLES = (
    "audit_logs",
    "configmap_audit_log",
    "consent_ledger",
    "github_admin_audit_log",
    "secret_audit_log",
    "webhook_audit_log",
)

_SIGNING_KEY_TABLES = ("consent_ledger_signing_keys",)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names(schema="public"))


def _role_exists(role: str) -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": role},
    )
    return bool(result.scalar())


def _grant_if_exists(table: str, role: str, privileges: str) -> None:
    op.execute(sa.text(f"GRANT {privileges} ON TABLE public.{table} TO {role}"))


def _revoke_if_exists(table: str, role: str, privileges: str) -> None:
    op.execute(sa.text(f"REVOKE {privileges} ON TABLE public.{table} FROM {role}"))


def upgrade() -> None:
    if not _is_postgres():
        return

    existing_tables = _existing_tables()
    roles = [role for role in _APP_ROLES if _role_exists(role)]

    for role in roles:
        op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        op.execute(sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))

        for table in _READ_WRITE_TABLES:
            if table in existing_tables:
                _grant_if_exists(table, role, "SELECT, INSERT, UPDATE, DELETE")

        for table in _APPEND_ONLY_TABLES:
            if table in existing_tables:
                _grant_if_exists(table, role, "SELECT, INSERT")
                _revoke_if_exists(table, role, "UPDATE, DELETE")

        for table in _SIGNING_KEY_TABLES:
            if table in existing_tables:
                # The admin consent-key promotion endpoint is the documented
                # mutation path for this registry; DELETE remains forbidden.
                _grant_if_exists(table, role, "SELECT, INSERT, UPDATE")
                _revoke_if_exists(table, role, "DELETE")


def downgrade() -> None:
    if not _is_postgres():
        return

    existing_tables = _existing_tables()
    roles = [role for role in _APP_ROLES if _role_exists(role)]

    for role in roles:
        for table in _READ_WRITE_TABLES:
            if table in existing_tables:
                _revoke_if_exists(table, role, "SELECT, INSERT, UPDATE, DELETE")

        for table in _APPEND_ONLY_TABLES:
            if table in existing_tables:
                _revoke_if_exists(table, role, "SELECT, INSERT")

        for table in _SIGNING_KEY_TABLES:
            if table in existing_tables:
                _revoke_if_exists(table, role, "SELECT, INSERT, UPDATE")
