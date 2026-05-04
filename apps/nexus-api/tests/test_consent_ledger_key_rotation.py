"""Tests for per-period HMAC key tracking on the consent ledger (migration 0030).

Pre-fix: ``compute_signature()`` used a single env-driven key. Rotating
``CONSENT_LEDGER_SIGNING_SECRET`` invalidated every pre-rotation row
because the verifier always used the *current* key.

Post-fix:

- ``consent_ledger_signing_keys`` registry stores every key version
  that has ever been current. Each ledger row carries
  ``signing_key_version`` (FK to the registry) so the verifier can
  look up the key that signed THIS row, regardless of how many
  rotations have happened since.
- ``POST /api/v1/admin/consent-ledger/promote-key`` is the documented
  mutation: atomic flip of the previous current row to retired +
  insert of a new row marked current.
- A Postgres partial unique index on ``is_current=true`` enforces
  "exactly one current key" at the DB layer (skipped on SQLite —
  test backend — but the in-transaction ordering preserves it).

These tests pin the new behaviour. Coverage:

1. Bootstrap migration creates a v1 key (verified via the conftest
   fixture that mirrors the migration's bootstrap).
2. Old rows verify against v1 EVEN AFTER v2 is promoted.
3. New rows after promotion are signed with v2.
4. Two ``is_current=true`` rows are forbidden by the partial unique
   index (Postgres-only sentinel; on SQLite we rely on the
   in-transaction flip ordering, which we also verify).
5. Promote endpoint requires admin role (403 for non-admin tokens).
6. Promote endpoint emits ``consent_ledger.key_promoted`` to
   ``task_events``.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import (
    ConsentLedger,
    ConsentLedgerSigningKey,
    TaskEvent,
)
from nexus_api.routers.onboarding import (
    CONSENT_CLAUSES,
    compute_signature,
    verify_signature_with_db,
)

_TENANTS_URL = "/api/v1/tenants"
_PROMOTE_URL = "/api/v1/admin/consent-ledger/promote-key"

# 64-char hex (32 bytes) — same shape as `openssl rand -hex 32`
_NEW_KEY_V2 = "a" * 64
_NEW_KEY_V3 = "b" * 64


async def _bootstrap_tenant(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        f"{_TENANTS_URL}/",
        headers=headers,
        json={"org_name": "Key Rotation Test Co"},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# 1. Bootstrap — v1 key exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_creates_v1_key(db_session: AsyncSession) -> None:
    """The conftest fixture (mirroring migration 0030) inserts a v1 key.

    Regression sentinel: if the fixture or migration regresses to NOT
    inserting v1, every voice-mode write would fail with 503 ("no
    current signing key").
    """
    rows = (
        (await db_session.execute(select(ConsentLedgerSigningKey)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    v1 = rows[0]
    assert v1.key_version == 1
    assert v1.is_current is True
    assert v1.retired_at is None
    assert v1.key_value, "v1 must have a non-empty key value"


# ---------------------------------------------------------------------------
# 2. Old rows verify under v1 even after v2 is promoted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_rotation_rows_verify_after_promotion(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Sign a row under v1, then promote v2, then verify the v1 row still
    passes — this is the property that closes the §6 limitation.
    """
    await _bootstrap_tenant(client, auth_headers)
    phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]
    resp = await client.post(
        "/api/v1/onboarding/voice-mode",
        headers=auth_headers,
        json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
    )
    assert resp.status_code == 201, resp.text

    # Confirm row was signed under v1.
    pre = (await db_session.execute(select(ConsentLedger))).scalar_one()
    assert pre.signing_key_version == 1

    # Verify under the registry — must succeed.
    assert await verify_signature_with_db(db_session, pre) is True

    # Promote v2.
    resp = await client.post(
        _PROMOTE_URL,
        headers=auth_headers,
        json={"new_key_value": _NEW_KEY_V2},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["new_key_version"] == 2
    assert body["previous_key_version"] == 1

    # Reload the pre-rotation row + re-verify under the registry. Must
    # still pass — this is the post-fix invariant.
    await db_session.refresh(pre)
    assert pre.signing_key_version == 1
    assert await verify_signature_with_db(db_session, pre) is True, (
        "pre-rotation ledger row must remain verifiable after promoting "
        "a new signing key — per-period tracking has regressed"
    )


# ---------------------------------------------------------------------------
# 3. New rows after promotion are signed with v2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_rotation_rows_use_v2_key(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """After v2 is promoted, new ledger rows MUST carry signing_key_version=2
    and verify only under the v2 key.
    """
    await _bootstrap_tenant(client, auth_headers)

    # Promote v2 BEFORE writing any consent row.
    resp = await client.post(
        _PROMOTE_URL,
        headers=auth_headers,
        json={"new_key_value": _NEW_KEY_V2},
    )
    assert resp.status_code == 201, resp.text

    # Sign a row.
    phrase = CONSENT_CLAUSES["agent_identified"]["typed_phrase"]
    resp = await client.post(
        "/api/v1/onboarding/voice-mode",
        headers=auth_headers,
        json={"mode": "agent_identified", "typed_confirmation": phrase},
    )
    assert resp.status_code == 201, resp.text

    row = (await db_session.execute(select(ConsentLedger))).scalar_one()
    assert row.signing_key_version == 2, (
        f"new row signed under wrong version: {row.signing_key_version}"
    )

    # Re-verify under registry. Verifier MUST pick up v2.
    assert await verify_signature_with_db(db_session, row) is True

    # Sanity: the same payload signed under v1 must NOT match (different
    # keys → different digest).
    v1_sig = compute_signature(
        org_id=row.org_id,
        user_sub=row.user_sub,
        mode=row.mode,
        clause_version=row.clause_version,
        typed_confirmation=row.typed_confirmation,
        created_at=row.created_at.replace(microsecond=0),
        key_value=(
            (
                await db_session.execute(
                    select(ConsentLedgerSigningKey).where(
                        ConsentLedgerSigningKey.key_version == 1
                    )
                )
            )
            .scalar_one()
            .key_value
        ),
    )
    assert v1_sig != row.signature_sha256


# ---------------------------------------------------------------------------
# 4. Multi-promotion + sequential rotation stay verifiable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_one_current_key_after_promotion(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """After promoting v2 and v3, only v3 is current. v1+v2 are retired."""
    await _bootstrap_tenant(client, auth_headers)

    for new_value in (_NEW_KEY_V2, _NEW_KEY_V3):
        resp = await client.post(
            _PROMOTE_URL,
            headers=auth_headers,
            json={"new_key_value": new_value},
        )
        assert resp.status_code == 201, resp.text

    # Inspect the registry.
    rows = (
        (
            await db_session.execute(
                select(ConsentLedgerSigningKey).order_by(
                    ConsentLedgerSigningKey.key_version
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3
    assert [r.key_version for r in rows] == [1, 2, 3]
    assert [r.is_current for r in rows] == [False, False, True]
    # v1 + v2 must be retired (retired_at non-NULL); v3 still active.
    assert rows[0].retired_at is not None
    assert rows[1].retired_at is not None
    assert rows[2].retired_at is None

    # Defense-in-depth: count of is_current=true rows must be exactly 1.
    current_count = sum(1 for r in rows if r.is_current)
    assert current_count == 1, (
        f"DB invariant violated: {current_count} rows have is_current=true "
        "(should be exactly 1)"
    )


# ---------------------------------------------------------------------------
# 5. Promote endpoint requires admin role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_endpoint_requires_admin_role(
    client: httpx.AsyncClient,
) -> None:
    """A token without admin/platform role MUST get 403."""
    # The dev-bypass token used by ``auth_headers`` carries the admin
    # role. Build a fresh test token by overriding the auth dependency
    # for this single request.
    from nexus_api.auth import get_current_user
    from nexus_api.main import app as _fastapi_app

    async def _non_admin_user() -> dict[str, object]:
        return {
            "sub": "regular-user",
            "user_id": "regular-user",
            "roles": ["tactician"],  # no admin, no platform
            "org_id": "test-org",
            "email": "user@example.com",
        }

    try:
        _fastapi_app.dependency_overrides[get_current_user] = _non_admin_user
        resp = await client.post(
            _PROMOTE_URL,
            headers={"Authorization": "Bearer test-token"},
            json={"new_key_value": _NEW_KEY_V2},
        )
        assert resp.status_code == 403, (
            f"expected 403 for non-admin role, got {resp.status_code}: {resp.text}"
        )
    finally:
        _fastapi_app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_promote_endpoint_accepts_platform_role(
    client: httpx.AsyncClient,
) -> None:
    """A token with the ``platform`` role (but not ``admin``) MUST succeed."""
    from nexus_api.auth import get_current_user
    from nexus_api.main import app as _fastapi_app

    async def _platform_user() -> dict[str, object]:
        return {
            "sub": "platform-user",
            "user_id": "platform-user",
            "roles": ["platform"],
            "org_id": "platform",
            "email": "ops@madfam.io",
        }

    try:
        _fastapi_app.dependency_overrides[get_current_user] = _platform_user
        resp = await client.post(
            _PROMOTE_URL,
            headers={"Authorization": "Bearer test-token"},
            json={"new_key_value": _NEW_KEY_V2},
        )
        assert resp.status_code == 201, resp.text
    finally:
        _fastapi_app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# 6. Promote endpoint emits the audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_endpoint_emits_audit_event(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A successful promotion MUST land a ``consent_ledger.key_promoted``
    row in ``task_events`` with the new + previous version, and MUST NOT
    leak the key value into the payload.
    """
    resp = await client.post(
        _PROMOTE_URL,
        headers=auth_headers,
        json={"new_key_value": _NEW_KEY_V2},
    )
    assert resp.status_code == 201, resp.text

    events = (
        (
            await db_session.execute(
                select(TaskEvent).where(
                    TaskEvent.event_type == "consent_ledger.key_promoted"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    payload = events[0].payload or {}
    assert payload.get("new_key_version") == 2
    assert payload.get("previous_key_version") == 1
    assert "actor_sub" in payload
    # CRITICAL: the key value MUST NEVER appear in the audit payload.
    assert _NEW_KEY_V2 not in str(payload), (
        "audit event leaked the new key value — never log key material"
    )
    assert events[0].event_category == "security"


# ---------------------------------------------------------------------------
# 7. Promote endpoint validates the new key shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_endpoint_rejects_short_key(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """A key shorter than 16 chars is a typo, not a real key."""
    resp = await client.post(
        _PROMOTE_URL,
        headers=auth_headers,
        json={"new_key_value": "abc123"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_promote_endpoint_rejects_non_hex_key(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Non-hex (e.g. base64) keys are rejected with a clear message."""
    resp = await client.post(
        _PROMOTE_URL,
        headers=auth_headers,
        # 32-char base64-style string — wrong shape, right length.
        json={"new_key_value": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 8. Health endpoint surfaces signing-key state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_reports_signing_key_summary(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``GET /api/v1/health/consent-ledger-grants`` MUST report registry
    state without leaking key values.
    """
    resp = await client.get("/api/v1/health/consent-ledger-grants")
    # Endpoint may be 503 on SQLite (grant probe unavailable) but the
    # signing_keys block should still come through.
    body = resp.json()
    assert "signing_keys" in body
    keys = body["signing_keys"]
    if "error" not in keys:
        assert keys["total_versions"] == 1
        assert keys["current_version"] == 1
        assert keys["current_count"] == 1
        # CRITICAL: never leak key values.
        assert "key_value" not in str(keys)
