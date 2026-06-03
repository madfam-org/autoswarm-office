"""Grant selva app roles access to all public tables (fresh DB bootstrap).

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-30

Migration 0037 granted only tables added in the Phase 2.x window. Fresh
databases created via ``alembic upgrade head`` leave core tables (e.g.
``swarm_tasks``, ``agents``) owned by the migration role without grants
to the runtime ``selva`` connection — campaign CRM handoff and dispatch
then fail with ``permission denied for table swarm_tasks``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_APP_ROLES = ("selva", "selva_app")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _role_exists(role: str) -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": role},
    )
    return bool(result.scalar())


def upgrade() -> None:
    if not _is_postgres():
        return

    roles = [role for role in _APP_ROLES if _role_exists(role)]
    for role in roles:
        op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        op.execute(
            sa.text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
            )
        )
        op.execute(
            sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        )
        op.execute(
            sa.text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
            )
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    roles = [role for role in _APP_ROLES if _role_exists(role)]
    for role in roles:
        op.execute(
            sa.text(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}")
        )
        op.execute(
            sa.text(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        )
