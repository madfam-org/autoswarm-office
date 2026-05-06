"""Per-period HMAC key tracking for the consent ledger.

Closes the rotation limitation flagged in
``docs/SECRET_ROTATION_POLICY.md`` §6: today rotating
``CONSENT_LEDGER_SIGNING_SECRET`` invalidates every pre-rotation row
because ``compute_signature()`` recomputes the HMAC with the
single current key.

This migration introduces a per-period key registry so each row
carries the ``key_version`` that signed it. The verifier looks up
that version's key value and recomputes — old rows stay verifiable
indefinitely; new rows get the current key.

Schema:

- ``consent_ledger_signing_keys``: append-only registry of every
  signing key version that has ever been current.

  - ``key_version`` SERIAL PK — monotonic integer, never reused.
  - ``key_value`` TEXT NOT NULL — the HMAC key (32-byte hex
    typically; we don't enforce length so that a future
    longer key (e.g. SHA-512 HMAC) can drop in without an ALTER).
  - ``created_at`` TIMESTAMPTZ NOT NULL DEFAULT NOW().
  - ``retired_at`` TIMESTAMPTZ NULL — set when this key stops
    signing new rows. NULL while current; set when promoted away.
  - ``is_current`` BOOLEAN NOT NULL DEFAULT FALSE — exactly one
    row at a time should be true. Enforced by a partial unique
    index ``uq_signing_keys_one_current`` (defense in depth
    against a bug that promotes two keys at once).

- ``consent_ledger.signing_key_version`` INTEGER NOT NULL DEFAULT
  1, FK to ``consent_ledger_signing_keys.key_version``. All
  existing rows backfill to version 1.

Bootstrap:

- The migration inserts a row with ``key_version=1``,
  ``key_value=<env CONSENT_LEDGER_SIGNING_SECRET>``,
  ``is_current=true``. If the env var is unset OR equals the
  ``dev-default-CHANGE-ME`` sentinel, the row is still inserted
  with ``is_current=false`` and ``key_value=''`` so the system
  doesn't crash but admin must promote a real key via
  ``POST /api/v1/admin/consent-ledger/promote-key`` before any
  new ledger rows can be signed.

- INSERT-only at the application layer: UPDATE/DELETE are
  REVOKEd from ``autoswarm_app`` so the registry is itself
  append-only. Promotion is handled via DDL-grade SQL inside
  the admin endpoint's transaction (it uses the migration role).

Idempotent: re-running upgrade is safe — existing tables and
the v1 bootstrap row are detected and skipped.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-03
"""

from __future__ import annotations

import os
from contextlib import suppress

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _bootstrap_key_value() -> tuple[str, bool]:
    """Resolve the bootstrap key value + whether it should be marked current.

    Returns a tuple of ``(key_value, is_current)``:

    - When ``CONSENT_LEDGER_SIGNING_SECRET`` is set to a real value
      (non-empty, not the dev sentinel), the v1 row uses that value
      and is marked current. Existing rows already verify against
      it — no signature break.

    - When the env var is unset OR matches the dev sentinel, we
      insert a placeholder row marked ``is_current=false`` and
      ``key_value=''``. The system stays runnable (verification of
      old rows still works because the column is non-NULL and the
      FK target exists), but new ledger writes will fail loud at
      the application layer ("no current signing key") until an
      admin promotes a real key.
    """
    raw = os.environ.get("CONSENT_LEDGER_SIGNING_SECRET", "")
    if raw and raw != "dev-default-CHANGE-ME":
        return raw, True
    return "", False


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Registry table.
    if not _has_table("consent_ledger_signing_keys"):
        op.create_table(
            "consent_ledger_signing_keys",
            sa.Column(
                "key_version",
                sa.Integer(),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column("key_value", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()") if is_postgres else sa.text(
                    "CURRENT_TIMESTAMP"
                ),
            ),
            sa.Column(
                "retired_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "is_current",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
        )

    # 2. Partial unique index enforcing "at most one is_current=true".
    #    Postgres-only feature; SQLite (used in tests) silently skips
    #    the WHERE clause but the unique index over a single boolean
    #    column would be too strict, so we only create it on Postgres.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {
        ix["name"] for ix in inspector.get_indexes("consent_ledger_signing_keys")
    }
    if is_postgres and "uq_signing_keys_one_current" not in existing_indexes:
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_signing_keys_one_current
            ON consent_ledger_signing_keys (is_current)
            WHERE is_current = TRUE
            """
        )

    # 3. Add signing_key_version FK column on consent_ledger. Backfill
    #    existing rows to version 1 BEFORE flipping NOT NULL, so the
    #    constraint never fires on pre-existing data.
    if not _has_column("consent_ledger", "signing_key_version"):
        op.add_column(
            "consent_ledger",
            sa.Column(
                "signing_key_version",
                sa.Integer(),
                nullable=True,
                server_default=sa.text("1"),
            ),
        )
        op.execute(
            "UPDATE consent_ledger SET signing_key_version = 1 "
            "WHERE signing_key_version IS NULL"
        )
        # FK after the bootstrap row exists (added below).

    # 4. Bootstrap the v1 row (idempotent via SELECT-then-INSERT). On
    #    re-run we skip — never overwrite a key value that's already
    #    in the DB.
    existing = bind.execute(
        sa.text(
            "SELECT key_version FROM consent_ledger_signing_keys WHERE key_version = 1"
        )
    ).first()

    if existing is None:
        key_value, is_current = _bootstrap_key_value()
        bind.execute(
            sa.text(
                "INSERT INTO consent_ledger_signing_keys "
                "(key_version, key_value, is_current) "
                "VALUES (:v, :k, :c)"
            ),
            {"v": 1, "k": key_value, "c": is_current},
        )

    # 5. Now that the v1 row exists, add the FK + flip NOT NULL on
    #    the new column. FK is created without server_default so
    #    future inserts must explicitly set the version.
    if _has_column("consent_ledger", "signing_key_version"):
        # ALTER NOT NULL — safe because backfill ran above.
        with op.batch_alter_table("consent_ledger") as batch:
            batch.alter_column(
                "signing_key_version",
                existing_type=sa.Integer(),
                nullable=False,
            )

        # Add FK constraint. Skip if it already exists (idempotency).
        existing_fks = {
            fk["name"] for fk in inspector.get_foreign_keys("consent_ledger")
        }
        if "fk_consent_ledger_signing_key" not in existing_fks:
            # SQLite cannot ADD CONSTRAINT — wrap in batch_alter_table.
            with op.batch_alter_table("consent_ledger") as batch:
                batch.create_foreign_key(
                    "fk_consent_ledger_signing_key",
                    "consent_ledger_signing_keys",
                    ["signing_key_version"],
                    ["key_version"],
                )

    # 6. Revoke UPDATE + DELETE on the registry from the app role.
    #    Same pattern as migration 0018 for ``consent_ledger`` itself.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
            REVOKE UPDATE, DELETE ON consent_ledger_signing_keys FROM autoswarm_app;
          END IF;
        END
        $$;
        """
    ) if is_postgres else None


def downgrade() -> None:
    # Re-grant on the registry first so the drop doesn't fail on lock.
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoswarm_app') THEN
                GRANT UPDATE, DELETE ON consent_ledger_signing_keys TO autoswarm_app;
              END IF;
            END
            $$;
            """
        )

    if _has_column("consent_ledger", "signing_key_version"):
        with op.batch_alter_table("consent_ledger") as batch:
            # FK may not exist on older partial-applied DBs.
            with suppress(Exception):
                batch.drop_constraint(
                    "fk_consent_ledger_signing_key", type_="foreignkey"
                )
            batch.drop_column("signing_key_version")

    if is_postgres:
        op.execute(
            "DROP INDEX IF EXISTS uq_signing_keys_one_current"
        )
    if _has_table("consent_ledger_signing_keys"):
        op.drop_table("consent_ledger_signing_keys")
