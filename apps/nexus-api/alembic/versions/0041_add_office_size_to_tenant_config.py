"""Add office_size to tenant_configs (onboarding office-size step).

The office-size onboarding step (office-ui #245) persisted the chosen size
band only in localStorage. This adds a durable, org-scoped column so the
choice survives across devices and can inform initial office layout +
suggested tier. Nullable + advisory — never gates access.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_TABLE = "tenant_configs"
_COLUMN = "office_size"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(16), nullable=True))


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
