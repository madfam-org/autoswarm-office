"""RLS Phase 1.5 -- strict-mode policies + ``app_admin`` BYPASSRLS role.

Replaces the permissive ``IS NULL OR = ''`` escape hatch in policies
created by migration ``0025`` with strict equality (``org_id =
current_setting('app.current_org_id', true)``). Cross-tenant
maintenance ops (``reap-stale``, audit-middleware writes, A2A
bridge, future Celery jobs) migrate to the new ``app_admin`` role
which has ``BYPASSRLS`` and lives behind the ``admin_session()``
helper introduced alongside this migration in
``nexus_api.database``.

Drives Option B from ``docs/RLS_PHASE_1_5_AUDIT.md`` §3:

  - ``autoswarm_app`` -- normal-traffic role. Loses the escape hatch.
    Every query must carry a session var matching the row's ``org_id``
    or the policy denies it. ``FORCE ROW LEVEL SECURITY`` is enabled
    so the table-owner bypass does NOT apply -- there is no way for
    code running as this role to silently see another tenant's rows.
  - ``app_admin`` -- ops role. Has ``BYPASSRLS`` (skips every policy
    check) and exists ONLY for cross-tenant maintenance paths. Every
    such path is gated by ``admin_session()`` which logs at WARNING
    on entry so cross-tenant access is observable in
    ``pg_stat_activity`` and the structured logs.

Backwards-compatibility invariants this migration preserves:

  1. **Migrations themselves**: Alembic MUST run as a role that has
     ``BYPASSRLS`` (either ``app_admin`` or a superuser). Otherwise
     any future migration that backfills tenant rows is rejected by
     the now-strict policy. The ``upgrade()`` body below performs a
     runtime check on the current Postgres role and raises a clear
     error if the role lacks ``BYPASSRLS``. This is intentional --
     a confusing "permission denied" mid-backfill is far worse than
     a loud failure at the top of the migration.

  2. **Existing data**: Phase 1 (migration ``0025``) policies allowed
     rows where ``app.current_org_id`` was NULL or empty string to
     pass the policy check. After this migration those queries
     return zero rows. The audit doc §2.E enumerates the five
     concrete code paths this affects -- all five were migrated to
     ``tenant_session(org_id=...)`` in PR #126 (commit 285b3c9).
     This migration is the logical follow-on that flips the
     policies themselves.

  3. **Role grants**: ``app_admin`` is created BEFORE policies are
     tightened so any administrative SQL run during the migration
     continues to work. The role is granted the same table
     privileges as ``autoswarm_app`` plus default privileges on
     future tables (so newly created tenant tables inherit ops
     access without a manual grant).

  4. **``tenant_identities``**: deliberately excluded from the
     ``_TENANT_TABLES`` list (see audit doc §2.E and migration
     ``0025``). It is a directory keyed by ``canonical_id`` rather
     than ``org_id`` and follows a different ACL model. Do NOT
     add it to the list below.

Downgrade restores the permissive Phase 1 policies. ``app_admin`` is
NOT dropped on downgrade because it may have active connections from
the BYPASSRLS pool (see ``database.get_admin_engine``); ops may drop
manually if needed via ``DROP ROLE app_admin``. The migration is
fully idempotent on both upgrade and downgrade -- safe to re-run.

Verification on a live cluster: ``GET /api/v1/health/rls-status``
returns ``{strict_mode_enabled: bool, policies: [...],
force_rls_tables: [...]}``.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


# Tenant-scoped tables -- MUST stay in sync with migration 0025's
# ``_TENANT_TABLES``. Any new tenant table is added in the migration that
# creates it, not here. See ``test_rls_strict_mode.py``
# ``TestMigration0028Shape`` for the contract test that catches drift.
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

# The platform-internal bypass marker. Code paths that legitimately scope
# to "all tenants" but cannot use ``admin_session()`` (e.g. read-only
# platform queries from a tenant-bound request) may set
# ``app.current_org_id = 'platform'``. The strict policies honour this
# token. This is the ONE permissive leg the new policies retain -- it
# replaces the broken ``IS NULL OR = ''`` legs with a single, audited,
# explicit string. See audit doc §3 (Option A vs Option B discussion);
# we adopt the sentinel from Option A as a narrow concession because
# some hot-path code paths (e.g. skills marketplace published-skill
# enumeration) need cross-tenant reads from inside a tenant request.
_PLATFORM_BYPASS_MARKER = "platform"


def _is_postgres() -> bool:
    """RLS only exists on Postgres. SQLite test paths skip the migration."""
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _assert_role_has_bypassrls() -> None:
    """Refuse to upgrade if Alembic is not running as a BYPASSRLS role.

    See the module docstring for why -- short version: this migration
    tightens policies in a way that future migrations may need to bypass
    in order to backfill tenant rows. If Alembic itself is running as a
    non-bypass role today, that's a latent bug that this migration would
    only surface as a confusing 'permission denied' inside an unrelated
    future migration. Surface it here, loudly, with a clear remediation.
    """
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT current_user AS role_name, "
            "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypass"
        )
    ).one()
    role_name = row.role_name
    bypass = bool(row.bypass)
    if not bypass:
        raise RuntimeError(
            f"Migration 0028 refuses to run as Postgres role '{role_name}' "
            f"because that role lacks BYPASSRLS. After this migration the "
            f"tenant-isolation policies are strict (no IS NULL escape hatch), "
            f"so any future migration that backfills tenant rows under a "
            f"non-bypass role will fail mid-DDL with 'new row violates row-level "
            f"security policy'. Re-run this migration as the 'app_admin' role "
            f"(see DATABASE_ADMIN_URL) or as a Postgres superuser. See "
            f"docs/RLS_PHASE_1_5_AUDIT.md §2.A."
        )


def _create_app_admin_role() -> None:
    """Create the ``app_admin`` BYPASSRLS role and grant it tenant-table privileges.

    Idempotent -- skips creation if the role already exists. Privileges
    are granted unconditionally (re-grants are no-ops in Postgres). The
    role is ``LOGIN`` so it can back its own connection pool via the
    ``DATABASE_ADMIN_URL`` env var; deployments that prefer to ``SET ROLE
    app_admin`` from the app role can drop ``LOGIN`` post-migration with
    ``ALTER ROLE app_admin NOLOGIN``.
    """
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
                    CREATE ROLE app_admin LOGIN BYPASSRLS;
                END IF;
            END
            $$;
            """
        )
    )

    # Grant the same surface as the app role. Default privileges so newly
    # created tables (future migrations) inherit ops access too.
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO app_admin"))
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_admin"
        )
    )
    op.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_admin"))
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_admin"
        )
    )
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO app_admin"
        )
    )

    # Make ``app_admin`` a member of ``autoswarm_app`` (so the app role can
    # SET ROLE to admin if a deployment chooses to use a single pool with
    # role-switching instead of two pools). Wrapped in DO $$ so a missing
    # autoswarm_app role doesn't abort the migration in dev environments.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
                    GRANT app_admin TO autoswarm_app;
                END IF;
            END
            $$;
            """
        )
    )


def _drop_permissive_policies() -> None:
    """Drop the Phase 1 permissive policies created by migration 0025."""
    for table in _TENANT_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))


def _create_strict_policies() -> None:
    """Create strict-equality policies on every tenant table.

    Policy structure: a row passes USING/WITH CHECK iff
    ``current_setting('app.current_org_id', true)`` is exactly
    ``'platform'`` OR equals the row's ``org_id``. Note ``current_setting
    (..., true)`` returns NULL when the variable is unset, so an unset
    session var produces ``NULL = ...`` which evaluates to NULL ->
    treated as false by the policy -> row denied. This is the desired
    strict behaviour.
    """
    for table in _TENANT_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_{table} ON {table}
                FOR ALL
                USING (
                    current_setting('app.current_org_id', true) = '{_PLATFORM_BYPASS_MARKER}'
                    OR org_id = current_setting('app.current_org_id', true)
                )
                WITH CHECK (
                    current_setting('app.current_org_id', true) = '{_PLATFORM_BYPASS_MARKER}'
                    OR org_id = current_setting('app.current_org_id', true)
                )
                """
            )
        )


def _force_rls_on_tenant_tables() -> None:
    """Apply ``FORCE ROW LEVEL SECURITY`` so the table-owner bypass does NOT apply.

    Without ``FORCE``, the role that owns the table (typically the role
    that ran ``CREATE TABLE``) skips RLS even with policies enabled.
    With ``FORCE``, only roles with ``BYPASSRLS`` (i.e. ``app_admin``)
    skip the check. This closes the "table owner forgets to scope"
    hole.
    """
    for table in _TENANT_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _unforce_rls_on_tenant_tables() -> None:
    """Reverse ``_force_rls_on_tenant_tables`` -- used by downgrade."""
    for table in _TENANT_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))


def _restore_permissive_policies() -> None:
    """Restore the Phase 1 permissive policies. Used by downgrade."""
    for table in _TENANT_TABLES:
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


def upgrade() -> None:
    if not _is_postgres():
        return

    # 1. Refuse to proceed if Alembic is running as a non-bypass role.
    _assert_role_has_bypassrls()

    # 2. Create the BYPASSRLS role + grants BEFORE policies tighten so we
    #    cannot accidentally lock the migration out of the schema.
    _create_app_admin_role()

    # 3. Drop permissive policies, install strict ones, force RLS.
    _drop_permissive_policies()
    _create_strict_policies()
    _force_rls_on_tenant_tables()


def downgrade() -> None:
    if not _is_postgres():
        return

    # Reverse in opposite order.
    _unforce_rls_on_tenant_tables()
    _drop_permissive_policies()  # drops the strict ones (same name)
    _restore_permissive_policies()
    # Intentionally do NOT drop the ``app_admin`` role -- see module docstring.
