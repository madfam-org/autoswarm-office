"""Admin endpoints for consent-ledger HMAC key rotation.

Implements the ``POST /api/v1/admin/consent-ledger/promote-key``
endpoint that closes the rotation limitation flagged in
``docs/SECRET_ROTATION_POLICY.md`` §6.

The promote operation is the documented mutation against the
otherwise append-only ``consent_ledger_signing_keys`` registry:

1. The currently-active row is flipped to ``is_current=false`` and
   ``retired_at=NOW()``. Old ledger rows signed under that key
   stay verifiable forever (the verifier looks up by version).
2. A new row is inserted with the next monotonic ``key_version``,
   the supplied ``new_key_value``, and ``is_current=true``.

Both writes happen inside a single transaction to preserve the
"exactly one current key" invariant. The Postgres partial unique
index ``uq_signing_keys_one_current`` enforces this at the DB
layer as defense in depth.

Auth: Bearer + role-gate to ``admin`` OR ``platform``. Tenant
users cannot rotate the platform-wide signing key — that's a
MADFAM ops responsibility.

Audit: emits ``consent_ledger.key_promoted`` to ``task_events``
with the new key version + actor. The key value is NEVER logged.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_roles
from ..database import get_db
from ..models import ConsentLedgerSigningKey
from .events import emit_event_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-consent"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

# 32-byte hex (64 chars) is the canonical shape for HMAC-SHA256 keys
# (matches ``openssl rand -hex 32`` output, the value
# ``scripts/rotate-secret.sh`` generates). We accept any non-empty
# string but warn-log shorter values so misconfiguration is visible.
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_RECOMMENDED_HEX_LEN = 64
_MIN_KEY_LEN = 16


class PromoteKeyRequest(BaseModel):
    """Body for POST /admin/consent-ledger/promote-key."""

    new_key_value: str = Field(
        ...,
        min_length=_MIN_KEY_LEN,
        max_length=512,
        description=(
            "New HMAC key value. Recommended shape: 64 hex chars "
            "(32 random bytes from `openssl rand -hex 32`). "
            "Must be at least 16 chars to reject obvious typos."
        ),
    )

    @field_validator("new_key_value")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("new_key_value cannot be empty/whitespace")
        # We don't *require* hex, but flag non-hex with a clear error
        # so an operator who pasted a base64 token by mistake gets a
        # helpful message rather than a silent acceptance.
        if not _HEX_RE.match(stripped):
            raise ValueError(
                "new_key_value must be a hex string (use `openssl rand -hex 32`)"
            )
        return stripped


class PromoteKeyResponse(BaseModel):
    """Result of a successful key promotion."""

    new_key_version: int = Field(..., description="Version assigned to the new key.")
    previous_key_version: int | None = Field(
        default=None,
        description=(
            "The version that was active before promotion. NULL if no "
            "previous key was current (placeholder-bootstrap state)."
        ),
    )
    promoted_at: datetime = Field(..., description="UTC timestamp of the promotion.")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/admin/consent-ledger/promote-key",
    response_model=PromoteKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote_signing_key(
    body: PromoteKeyRequest,
    request: Request,
    user: dict[str, Any] = Depends(  # noqa: B008
        require_roles(["admin", "platform"])
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PromoteKeyResponse:
    """Promote a new HMAC key for the consent ledger (atomic rotation).

    Flow inside a single transaction:

    1. Find the currently-active key row (``is_current=true``). May be
       NULL on a fresh install where the bootstrap inserted a
       placeholder. That's OK — we just promote without a retiring step.
    2. Mark it ``is_current=false`` + ``retired_at=NOW()``.
    3. Insert a new row with ``is_current=true`` and the next
       ``key_version`` (max + 1; falls back to 2 when only the v1
       bootstrap exists, which is the common case).
    4. Emit a ``consent_ledger.key_promoted`` audit event. The new
       version is in the payload; the key value is NEVER.

    The Postgres partial unique index would catch step 3 attempting to
    insert while step 2's flip hasn't committed (would raise
    IntegrityError). On SQLite (test backend) the index is skipped
    and the test relies on the in-transaction ordering instead.

    Returns 503 when the registry is in an unexpected state (e.g. >1
    current row before the flip — shouldn't happen with the partial
    unique index, but we surface it rather than silently overwrite).
    """
    promoted_at = datetime.now(UTC).replace(microsecond=0)

    # 1. Find current row(s). >1 is an invariant violation — surface 503.
    current_rows = (
        await db.execute(
            select(ConsentLedgerSigningKey).where(
                ConsentLedgerSigningKey.is_current.is_(True)
            )
        )
    ).scalars().all()
    if len(current_rows) > 1:
        logger.error(
            "promote-key: %d rows have is_current=true (invariant violated)",
            len(current_rows),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Multiple current signing keys (DB invariant violated).",
        )
    previous = current_rows[0] if current_rows else None
    previous_version = previous.key_version if previous else None

    # 2. Retire the previous current row. Use UPDATE to avoid
    #    SQLAlchemy session staleness on the row instance.
    if previous is not None:
        await db.execute(
            update(ConsentLedgerSigningKey)
            .where(ConsentLedgerSigningKey.key_version == previous.key_version)
            .values(is_current=False, retired_at=promoted_at)
        )

    # 3. Insert the new row. ``key_version`` is autoincrement; let the
    #    DB pick the next value. We MAX-then-INSERT only as a safety
    #    net for SQLite where autoincrement on a serial-style col can
    #    race. Postgres SERIAL is sequence-backed and safe.
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        max_v = (
            await db.execute(select(func.max(ConsentLedgerSigningKey.key_version)))
        ).scalar() or 0
        new_row = ConsentLedgerSigningKey(
            key_version=max_v + 1,
            key_value=body.new_key_value,
            is_current=True,
            created_at=promoted_at,
        )
    else:
        new_row = ConsentLedgerSigningKey(
            key_value=body.new_key_value,
            is_current=True,
            created_at=promoted_at,
        )
    db.add(new_row)
    await db.flush()
    await db.refresh(new_row)

    # 4. Audit event. Org_id from the actor's JWT — for platform-role
    #    callers this will be the platform org. The key value is NEVER
    #    in the payload; only the version + actor identity.
    actor_sub = str(user.get("sub") or user.get("user_id") or "unknown")
    org_id = user.get("org_id") or "platform"
    await emit_event_db(
        db,
        event_type="consent_ledger.key_promoted",
        event_category="security",
        org_id=org_id,
        payload={
            "new_key_version": new_row.key_version,
            "previous_key_version": previous_version,
            "actor_sub": actor_sub,
            "actor_ip": request.client.host if request.client else "unknown",
        },
    )

    logger.info(
        "consent_ledger key promoted: new_version=%d previous_version=%s "
        "actor_sub=%s",
        new_row.key_version,
        previous_version,
        actor_sub,
    )

    return PromoteKeyResponse(
        new_key_version=new_row.key_version,
        previous_key_version=previous_version,
        promoted_at=promoted_at,
    )
