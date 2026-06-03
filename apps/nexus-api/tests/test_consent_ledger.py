"""Regression tests for consent-ledger HMAC + healthcheck (commit e71337c).

Pre-fix: ``signature_sha256`` was a plain SHA-256 over public ledger
fields. Anyone with INSERT (the ``selva_app`` role still has it,
intentionally) could forge a row and recompute the digest -- the
"tamper evidence" claim was cryptographically vacuous.

Post-fix:
  - ``compute_signature`` uses ``hmac.new(_signing_secret(), ...)``.
    The secret comes from ``Settings.consent_ledger_signing_secret``
    and is held only in the application process; an attacker with DB
    INSERT cannot forge a passing signature without the secret.
  - ``verify_signature`` uses ``hmac.compare_digest`` for constant-time
    comparison (no timing oracle).
  - ``GET /api/v1/health/consent-ledger-grants`` exposes a runtime probe
    of the DB-level append-only invariant (REVOKE UPDATE/DELETE on the
    table from the app role); this catches a re-applied migration or
    manual GRANT that silently re-opens mutability.

These tests pin the new behaviour so the regression cannot silently
return.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from nexus_api.routers import onboarding as _onb_mod
from nexus_api.routers.onboarding import compute_signature


def _payload_kwargs() -> dict:
    return {
        "org_id": "org-test",
        "user_sub": "user-001",
        "mode": "dyad_selva_plus_user",
        "clause_version": "voice-mode-v1.0",
        "typed_confirmation": "I AGREE",
        "created_at": datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
    }


class TestComputeSignatureUsesHmac:
    """compute_signature MUST be HMAC-keyed, not plain SHA-256."""

    def test_compute_signature_uses_hmac_not_sha256(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two different signing secrets MUST produce different signatures
        for the same payload — the property that distinguishes HMAC from
        unkeyed SHA-256.

        Regression sentinel: if anyone replaces ``hmac.new(secret, ...)``
        with ``hashlib.sha256(...)``, both calls below would return the
        SAME digest (the secret would be ignored), and this test fails
        loudly.
        """
        kwargs = _payload_kwargs()

        with patch.object(_onb_mod, "_signing_secret", return_value=b"secret-A"):
            sig_a = compute_signature(**kwargs)

        with patch.object(_onb_mod, "_signing_secret", return_value=b"secret-B"):
            sig_b = compute_signature(**kwargs)

        assert sig_a != sig_b, (
            "compute_signature returned the same digest under two different "
            "signing secrets — this means the function is NOT HMAC-keyed "
            "(the secret was ignored). Plain SHA-256 has regressed."
        )
        # Shape check: still a 64-char lowercase hex digest (column shape
        # invariant is preserved).
        assert len(sig_a) == 64
        assert all(c in "0123456789abcdef" for c in sig_a)

    def test_compute_signature_is_deterministic_under_same_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same secret + same payload → identical digest (control case)."""
        kwargs = _payload_kwargs()
        with patch.object(_onb_mod, "_signing_secret", return_value=b"stable-secret"):
            sig_1 = compute_signature(**kwargs)
            sig_2 = compute_signature(**kwargs)
        assert sig_1 == sig_2


class TestVerifySignatureConstantTime:
    """verify_signature MUST use hmac.compare_digest (constant-time)."""

    def test_verify_signature_uses_constant_time_compare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """hmac.compare_digest MUST be the comparator.

        Regression sentinel: if anyone "simplifies" to ``expected ==
        entry.signature_sha256``, this test fails. ``==`` on str leaks
        a timing oracle that recovers the digest byte-by-byte.
        """
        from nexus_api.routers import onboarding as _onb

        # Build a fake ledger entry that round-trips through verify_signature.
        kwargs = _payload_kwargs()

        with patch.object(_onb, "_signing_secret", return_value=b"test-key"):
            real_sig = compute_signature(**kwargs)

        entry = MagicMock()
        entry.org_id = kwargs["org_id"]
        entry.user_sub = kwargs["user_sub"]
        entry.mode = kwargs["mode"]
        entry.clause_version = kwargs["clause_version"]
        entry.typed_confirmation = kwargs["typed_confirmation"]
        entry.created_at = kwargs["created_at"]
        entry.signature_sha256 = real_sig

        # Spy on hmac.compare_digest (the module-level binding inside onboarding).
        with (
            patch.object(_onb, "_signing_secret", return_value=b"test-key"),
            patch.object(_onb.hmac, "compare_digest", wraps=_onb.hmac.compare_digest) as spy,
        ):
            result = _onb.verify_signature(entry)

        assert result is True
        assert spy.called, (
            "verify_signature did not call hmac.compare_digest — a "
            "timing-oracle-vulnerable comparator (e.g. ``==``) is in "
            "use instead. Constant-time comparison has regressed."
        )


@pytest.mark.asyncio
class TestConsentLedgerGrantsHealthcheck:
    """GET /api/v1/health/consent-ledger-grants exposes the DB-level invariant."""

    async def test_consent_ledger_grants_endpoint_returns_invariant_shape(
        self, client: httpx.AsyncClient
    ) -> None:
        """The endpoint MUST return a JSON body with the documented keys.

        We don't assert specific values because they depend on the test
        DB role (SQLite has no role/grant concept; PostgreSQL with the
        right ``selva_app`` role would return real values). We
        assert the SHAPE so a future refactor that drops a key is
        caught here.
        """

        fake_row = MagicMock()
        fake_row.can_insert = True
        fake_row.can_update = False
        fake_row.can_delete = False

        async def _fake_execute(statement, params=None):
            result = MagicMock()
            result.one = MagicMock(return_value=fake_row)
            return result

        # Patch the DB execute call inside the route handler. We do
        # this by intercepting AsyncSession.execute via the override
        # the client fixture already wires up.
        from nexus_api.database import get_db
        from nexus_api.main import app as _fastapi_app

        async def _fake_get_db():
            db = MagicMock()
            db.execute = _fake_execute
            yield db

        try:
            _fastapi_app.dependency_overrides[get_db] = _fake_get_db

            resp = await client.get("/api/v1/health/consent-ledger-grants")
            assert resp.status_code == 200, (
                f"Expected 200 when invariant holds, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            for key in ("invariant_holds", "can_insert", "can_update", "can_delete"):
                assert key in body, f"Healthcheck response missing key: {key}"

            # Under the patched happy-path values, invariant must hold.
            assert body["invariant_holds"] is True
            assert body["can_insert"] is True
            assert body["can_update"] is False
            assert body["can_delete"] is False
        finally:
            _fastapi_app.dependency_overrides.pop(get_db, None)

    async def test_consent_ledger_grants_returns_503_when_invariant_violated(
        self, client: httpx.AsyncClient
    ) -> None:
        """If UPDATE or DELETE is granted, the endpoint MUST return 503.

        This is the alarm bell: a re-applied migration, manual GRANT
        ALL, or a superuser-mode test seed that re-mutates the grants
        will surface in monitoring.
        """
        from nexus_api.database import get_db
        from nexus_api.main import app as _fastapi_app

        # Simulate a violated invariant (UPDATE re-granted by accident).
        fake_row = MagicMock()
        fake_row.can_insert = True
        fake_row.can_update = True  # ← invariant violation
        fake_row.can_delete = False

        async def _fake_execute(statement, params=None):
            result = MagicMock()
            result.one = MagicMock(return_value=fake_row)
            return result

        async def _fake_get_db():
            db = MagicMock()
            db.execute = _fake_execute
            yield db

        try:
            _fastapi_app.dependency_overrides[get_db] = _fake_get_db
            resp = await client.get("/api/v1/health/consent-ledger-grants")
            assert resp.status_code == 503
            body = resp.json()
            assert body["invariant_holds"] is False
            assert body["can_update"] is True
        finally:
            _fastapi_app.dependency_overrides.pop(get_db, None)
