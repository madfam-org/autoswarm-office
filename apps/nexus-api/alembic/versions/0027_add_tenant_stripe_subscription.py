"""Add Stripe subscription columns on tenant_configs.

Required by the Phase 2.7 Stripe webhook handlers
(`apps/nexus-api/nexus_api/routers/stripe_webhooks.py`). Today the
webhook scaffold has no way to look up a tenant from a Stripe customer
ID (the only stable identifier in `customer.subscription.*` and
`invoice.*` events), so the handlers cannot route side effects to the
right ``tenant_configs`` row.

Five new columns:

- ``stripe_customer_id`` -- the Stripe customer ID
  (``cus_...``). Indexed + UNIQUE because it is the lookup key for
  every webhook handler.
- ``stripe_subscription_id`` -- the latest Stripe subscription
  (``sub_...``). NULL for tenants on a one-shot pricing model.
- ``subscription_status`` -- mirrors the Stripe subscription status
  (``active``, ``trialing``, ``past_due``, ``cancelled``,
  ``incomplete``, ...). NULL means "no Stripe subscription on file".
- ``subscription_tier`` -- the Selva tier slug
  (``starter``/``professional``/``enterprise``) derived from the
  subscription's price ID via ``Settings.stripe_price_to_tier_map``.
  Mirrors ``billing_tiers.TIER_DAILY_TASK_LIMIT`` keys.
- ``subscription_current_period_end`` -- when the current paid period
  expires. Used by the cancellation grace-period scheduler.

All nullable so existing rows continue to work unchanged. Idempotent
ADD COLUMN -- safe to re-run.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_configs",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("subscription_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column("subscription_tier", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tenant_configs",
        sa.Column(
            "subscription_current_period_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # UNIQUE on stripe_customer_id so webhook handlers can resolve a single
    # tenant from a Stripe customer.* event without ambiguity. NULL allowed
    # (Postgres treats NULLs as distinct under UNIQUE), so tenants without
    # a Stripe account remain valid.
    op.create_index(
        "ix_tenant_configs_stripe_customer_id",
        "tenant_configs",
        ["stripe_customer_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_configs_stripe_customer_id", table_name="tenant_configs")
    op.drop_column("tenant_configs", "subscription_current_period_end")
    op.drop_column("tenant_configs", "subscription_tier")
    op.drop_column("tenant_configs", "subscription_status")
    op.drop_column("tenant_configs", "stripe_subscription_id")
    op.drop_column("tenant_configs", "stripe_customer_id")
