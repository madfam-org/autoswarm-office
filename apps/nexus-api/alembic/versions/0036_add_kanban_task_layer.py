"""Add first-class kanban task metadata.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


_PLATFORM_BYPASS_MARKER = "platform"
_NEW_TABLES = ("task_comments", "task_history")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _uuid_type() -> Any:
    return UUID(as_uuid=True) if _is_postgres() else sa.String(length=36)


def _now_default() -> sa.TextClause:
    return sa.text("NOW()" if _is_postgres() else "CURRENT_TIMESTAMP")


def _json_array_default() -> sa.TextClause:
    return sa.text("'[]'::json" if _is_postgres() else "'[]'")


def _grant_table(table: str) -> None:
    if not _is_postgres():
        return
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'selva_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO selva_app;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_admin;
                END IF;
            END
            $$;
            """
        )
    )


def _enable_rls(table: str) -> None:
    if not _is_postgres():
        return
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    uuid_type = _uuid_type()
    now = _now_default()
    json_array_default = _json_array_default()

    if not _has_column("swarm_tasks", "title"):
        op.add_column("swarm_tasks", sa.Column("title", sa.String(length=200), nullable=True))
    if not _has_column("swarm_tasks", "kanban_status"):
        op.add_column(
            "swarm_tasks",
            sa.Column(
                "kanban_status",
                sa.String(length=50),
                nullable=False,
                server_default="todo",
            ),
        )
    if not _has_column("swarm_tasks", "priority"):
        op.add_column(
            "swarm_tasks",
            sa.Column(
                "priority",
                sa.String(length=20),
                nullable=False,
                server_default="medium",
            ),
        )
    if not _has_column("swarm_tasks", "labels"):
        op.add_column(
            "swarm_tasks",
            sa.Column("labels", sa.JSON(), nullable=False, server_default=json_array_default),
        )
    if not _has_column("swarm_tasks", "due_date"):
        op.add_column(
            "swarm_tasks",
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column("swarm_tasks", "creator_id"):
        op.add_column("swarm_tasks", sa.Column("creator_id", sa.String(length=255), nullable=True))
    if not _has_column("swarm_tasks", "parent_task_id"):
        op.add_column("swarm_tasks", sa.Column("parent_task_id", uuid_type, nullable=True))
        if _is_postgres():
            op.create_foreign_key(
                "fk_swarm_tasks_parent_task_id",
                "swarm_tasks",
                "swarm_tasks",
                ["parent_task_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if not _has_column("swarm_tasks", "depends_on"):
        op.add_column(
            "swarm_tasks",
            sa.Column("depends_on", sa.JSON(), nullable=False, server_default=json_array_default),
        )
    if not _has_column("swarm_tasks", "updated_at"):
        op.add_column(
            "swarm_tasks",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        )

    if _is_postgres():
        op.execute(
            sa.text(
                """
                UPDATE swarm_tasks
                SET kanban_status = CASE
                    WHEN status IN ('running') THEN 'in_progress'
                    WHEN status IN ('completed') THEN 'done'
                    WHEN status IN ('failed', 'cancelled') THEN 'blocked'
                    ELSE 'todo'
                END
                WHERE kanban_status = 'todo'
                """
            )
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("swarm_tasks")}
    if "ix_swarm_tasks_kanban_status_updated_at" not in existing_indexes:
        op.create_index(
            "ix_swarm_tasks_kanban_status_updated_at",
            "swarm_tasks",
            ["kanban_status", "updated_at"],
        )
    if "ix_swarm_tasks_priority_due_date" not in existing_indexes:
        op.create_index("ix_swarm_tasks_priority_due_date", "swarm_tasks", ["priority", "due_date"])
    if "ix_swarm_tasks_parent_task_id" not in existing_indexes:
        op.create_index("ix_swarm_tasks_parent_task_id", "swarm_tasks", ["parent_task_id"])

    if not _has_table("task_comments"):
        op.create_table(
            "task_comments",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "task_id",
                uuid_type,
                sa.ForeignKey("swarm_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("org_id", sa.String(length=255), nullable=False),
            sa.Column("author_id", sa.String(length=255), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        )
    if not _has_table("task_history"):
        op.create_table(
            "task_history",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "task_id",
                uuid_type,
                sa.ForeignKey("swarm_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("org_id", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("actor_id", sa.String(length=255), nullable=True),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json" if _is_postgres() else "'{}'"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        )

    for table in _NEW_TABLES:
        existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}
        task_index = f"ix_{table}_task_created"
        org_index = f"ix_{table}_org_created"
        if task_index not in existing:
            op.create_index(task_index, table, ["task_id", "created_at"])
        if org_index not in existing:
            op.create_index(org_index, table, ["org_id", "created_at"])
        _grant_table(table)
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        if _has_table(table):
            op.drop_index(f"ix_{table}_org_created", table_name=table)
            op.drop_index(f"ix_{table}_task_created", table_name=table)
            op.drop_table(table)

    existing_indexes = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("swarm_tasks")}
    if "ix_swarm_tasks_parent_task_id" in existing_indexes:
        op.drop_index("ix_swarm_tasks_parent_task_id", table_name="swarm_tasks")
    if "ix_swarm_tasks_priority_due_date" in existing_indexes:
        op.drop_index("ix_swarm_tasks_priority_due_date", table_name="swarm_tasks")
    if "ix_swarm_tasks_kanban_status_updated_at" in existing_indexes:
        op.drop_index("ix_swarm_tasks_kanban_status_updated_at", table_name="swarm_tasks")
    if _is_postgres():
        op.drop_constraint("fk_swarm_tasks_parent_task_id", "swarm_tasks", type_="foreignkey")

    for column in (
        "updated_at",
        "depends_on",
        "parent_task_id",
        "creator_id",
        "due_date",
        "labels",
        "priority",
        "kanban_status",
        "title",
    ):
        if _has_column("swarm_tasks", column):
            op.drop_column("swarm_tasks", column)
