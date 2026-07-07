"""Add cost_usd + caller to compute_token_ledger (RFC 0034 P1).

The inference proxy now writes durable, org-attributed, USD-priced ledger
entries (previously it only emitted best-effort token events). `cost_usd` is
the real provider-priced dollar cost per call (estimate_cost); `caller` is the
calling service/product identity so per-product AI margin becomes computable.
Both nullable so historical rows (token-only agent debits) stay valid.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_TABLE = "compute_token_ledger"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column(_TABLE, "cost_usd"):
        # Numeric(12,6): fractions of a cent through five-figure daily spend.
        op.add_column(_TABLE, sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True))
    if not _has_column(_TABLE, "caller"):
        op.add_column(_TABLE, sa.Column("caller", sa.String(255), nullable=True))
        op.create_index(
            "ix_compute_token_ledger_caller", _TABLE, ["caller"], unique=False
        )


def downgrade() -> None:
    if _has_column(_TABLE, "caller"):
        op.drop_index("ix_compute_token_ledger_caller", table_name=_TABLE)
        op.drop_column(_TABLE, "caller")
    if _has_column(_TABLE, "cost_usd"):
        op.drop_column(_TABLE, "cost_usd")
