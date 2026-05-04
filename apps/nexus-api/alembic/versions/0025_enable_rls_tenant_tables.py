"""Enable Postgres Row-Level Security on every tenant-scoped table.

Closes the entire class of "missed `.where(org_id == tenant.org_id)`"
bugs by enforcing tenant isolation at the database layer. App-layer
scoping was correct as of v2.2.x (commit b72399e); this is the
defense-in-depth that catches any future router that forgets.

Pattern: every tenant-scoped table (every table with an ``org_id``
column) gets RLS enabled and a policy filtering by
``current_setting('app.current_org_id', true)``. The session variable
is set in ``database.get_db`` from the auth context's
``org_id_var`` ContextVar, which auth.py already populates on every
request.

PERMISSIVE ESCAPE HATCH (Phase 1 only — TODO Phase 1.5):

The policies use ``current_setting(..., true) IS NULL OR ... = ''``
as a NULL-safe escape hatch for paths that legitimately have no
tenant context (Alembic migrations, seed scripts, healthchecks,
demo paths). The ``true`` second arg to ``current_setting`` returns
NULL instead of raising when the variable is unset.

This permissive branch must be tightened in Phase 1.5 after
auditing every code path that runs without an org_id. See
ROADMAP.md.

NOT USED YET (Phase 1.5):
- ``FORCE ROW LEVEL SECURITY`` (would apply policies to the table
  owner role too — useful once we're confident no admin script needs
  to bypass).

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


# Tenant-scoped tables — every table with an ``org_id`` column. Verified
# from models.py at commit time. New tenant tables MUST be added here AND
# get a policy created (see _create_policies below).
_TENANT_TABLES = (
    "departments",
    "agents",
    "approval_requests",
    "swarm_tasks",
    "workflows",
    "artifacts",
    "compute_token_ledger",
    "skill_marketplace_entries",
    "skill_ratings",
    "calendar_connections",
    "maps",
    "task_events",
    "chat_messages",
    "tenant_configs",
    "audit_logs",
    "consent_ledger",
    "hitl_decisions",
    "hitl_confidence",
)

# Tables intentionally NOT enabled for RLS (no org_id column or
# different scoping model):
# - command_approval_requests: scoped by run_id, not org_id
# - schedules: scoped by user_id
# - secret_audit_log, github_admin_audit_log, configmap_audit_log,
#   webhook_audit_log: platform-only audit tables (MADFAM ops only)
# - tenant_identities: keyed by canonical_id (the Janua org_id) but
#   acts as a directory; future Phase may add platform-vs-tenant
#   ACL via a different mechanism


def _is_postgres() -> bool:
    """RLS only exists on Postgres. SQLite test paths skip the migration."""
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    for table in _TENANT_TABLES:
        # Enable RLS on the table. Without a policy, this would block ALL
        # queries — the policies created below restore expected access.
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        # SELECT/UPDATE/DELETE policy: row's org_id must match session's
        # OR session has no tenant context (permissive escape hatch).
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_{table} ON {table}
                FOR ALL
                USING (
                    current_setting('app.current_org_id', true) IS NULL
                    OR current_setting('app.current_org_id', true) = ''
                    OR org_id = current_setting('app.current_org_id', true)
                )
                WITH CHECK (
                    current_setting('app.current_org_id', true) IS NULL
                    OR current_setting('app.current_org_id', true) = ''
                    OR org_id = current_setting('app.current_org_id', true)
                )
                """
            )
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    for table in _TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
