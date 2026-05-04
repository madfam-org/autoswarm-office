"""Add external_a2a_callers — first-class tenant model for A2A peers.

Today the A2A protocol bridge in ``apps/nexus-api/nexus_api/main.py``
funnels every inbound ``tasks/send`` through the synthetic
``org_id="a2a-external"`` org (introduced in PR #126 to satisfy the
RLS Phase 1.5 strict-mode contract). That synthetic org has no
``tenant_configs`` row, no quota, no consent ledger entry, no audit
attribution, and no revocation primitive. See
``docs/rfcs/0018-a2a-external-tenant-model.md`` for the full
problem statement and the migration path.

This migration is **scaffold only** — it creates the
``external_a2a_callers`` table and the SQLAlchemy model, but does
NOT change the bridge functions in ``main.py``. Behavior cutover
lands in a follow-up PR (Phase C in the RFC) gated by the
``A2A_PER_CALLER_TENANT`` env flag.

Columns:

- ``id`` — UUID PK.
- ``name`` — human-readable label (from peer's AgentCard ``name``).
- ``agent_card_url`` — the peer's ``/.well-known/agent.json`` URL.
  UNIQUE so the (org_id derivation = sha256(url)[:16]) stays
  deterministic and re-registrations are idempotent.
- ``public_key`` — PEM-encoded key for verifying the peer's
  per-request signed JWT (Option B in RFC §5). NULL until the
  peer registers a key.
- ``status`` — ``active`` | ``suspended`` | ``revoked``. Revocation
  primitive — admin can disable a single caller without disabling
  the whole protocol.
- ``subscription_tier`` — billing tier slug. Default
  ``"external_a2a"`` (a new key added to ``TIER_DAILY_TASK_LIMIT``
  in the cutover PR; the slug is referenced now so the column
  default does not need a backfill later).
- ``daily_task_limit`` — per-caller cap; overrides the tier
  default when set. Defaults to 100, matching the proposed
  ``external_a2a`` tier.
- ``created_at`` / ``last_seen_at`` — provenance + activity
  tracking. ``last_seen_at`` touched on every successful
  ``tasks/send`` once the cutover ships.
- ``owner_user_id`` — the MADFAM user_sub who approved this
  caller during registration. NULL for the legacy/seed row
  inserted by ops.

Idempotent: uses ``op.create_table`` + an ``IF NOT EXISTS``
short-circuit on the index (Postgres-only — see the helper
function below). Re-running upgrade is safe.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    """Return True if *name* already exists.

    Mirrors the ``IF NOT EXISTS`` idiom so re-running upgrade in
    environments where the table has been hand-applied (or where
    the migration ran partially before failing) does not blow up.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("external_a2a_callers"):
        op.create_table(
            "external_a2a_callers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            # 2048 because RFC 3986 doesn't bound URL length and some
            # AgentCard URLs include path segments + query params.
            sa.Column("agent_card_url", sa.String(length=2048), nullable=False),
            # PEM keys are typically 1-4 KB; TEXT (unbounded) so
            # rotation to a longer key (e.g. RSA-4096 → ECC-P521 hybrid)
            # never requires a column ALTER.
            sa.Column("public_key", sa.Text(), nullable=True),
            # CHECK constraint at the DB level pins values to the three
            # legal states. The app layer will also validate but defence-
            # in-depth: a future ad-hoc UPDATE with a typo cannot leave
            # a caller in an undefined state.
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column(
                "subscription_tier",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'external_a2a'"),
            ),
            sa.Column(
                "daily_task_limit",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("100"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "owner_user_id",
                sa.String(length=255),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "agent_card_url",
                name="uq_external_a2a_callers_agent_card_url",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'suspended', 'revoked')",
                name="ck_external_a2a_callers_status",
            ),
        )

    # Indexes are idempotent via inspector lookup. ``agent_card_url``
    # gets its own UNIQUE index in addition to the constraint above
    # so the query planner has an explicit object to attach stats to —
    # the constraint-backed index name is implementation-defined and
    # varies between Postgres versions.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("external_a2a_callers")}

    if "ix_external_a2a_callers_agent_card_url" not in existing_indexes:
        op.create_index(
            "ix_external_a2a_callers_agent_card_url",
            "external_a2a_callers",
            ["agent_card_url"],
            unique=True,
        )

    if "ix_external_a2a_callers_status" not in existing_indexes:
        # Filter index for the dispatch hot path
        # (``WHERE status='active'``). Cardinality is low (3 values)
        # but the dispatch path will read this on every A2A request
        # once the cutover ships, so we want the index resident.
        op.create_index(
            "ix_external_a2a_callers_status",
            "external_a2a_callers",
            ["status"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_external_a2a_callers_status",
        table_name="external_a2a_callers",
    )
    op.drop_index(
        "ix_external_a2a_callers_agent_card_url",
        table_name="external_a2a_callers",
    )
    op.drop_table("external_a2a_callers")
