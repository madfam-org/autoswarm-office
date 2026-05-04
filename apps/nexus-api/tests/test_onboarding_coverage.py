"""Phase 2 critical-path coverage for ``nexus_api.routers.onboarding``.

Targets the gaps not covered by ``test_voice_mode_onboarding.py``:

- ``_get_client_ip`` X-Forwarded-For handling.
- ``_load_tenant`` 404 path (tenant config missing).
- ``_record_consent`` user-email-missing 400.
- ``GET /onboarding/tenant-identity`` — 403 (platform), 404 (no config),
  200 with full identity, 200 with brand_name fallback chain.
- ``PUT /settings/outbound-voice`` — same-mode no-op (no new ledger
  row), success path with new ledger row, missing tenant 404.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_api.models import ConsentLedger, TenantConfig, TenantIdentity
from nexus_api.routers import onboarding as _ob
from nexus_api.routers.onboarding import CONSENT_CLAUSES

_TENANTS_URL = "/api/v1/tenants"


async def _bootstrap_tenant(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        f"{_TENANTS_URL}/",
        headers=headers,
        json={"org_name": "Coverage Test Co"},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# _get_client_ip helper (line 228)
# ---------------------------------------------------------------------------


class TestGetClientIp:
    def test_returns_first_forwarded_for_entry(self) -> None:
        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
        req.client = MagicMock(host="10.0.0.99")
        assert _ob._get_client_ip(req) == "203.0.113.5"

    def test_falls_back_to_request_client_host(self) -> None:
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock(host="198.51.100.7")
        assert _ob._get_client_ip(req) == "198.51.100.7"

    def test_returns_unknown_when_no_client(self) -> None:
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _ob._get_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# Endpoint coverage: missing tenant + missing email + tenant-identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOnboardingMissingTenant:
    async def test_change_voice_mode_404_when_no_tenant(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT /settings/outbound-voice returns 404 if tenant_config is missing."""
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]
        resp = await client.put(
            "/api/v1/settings/outbound-voice",
            headers=auth_headers,
            json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestPutVoiceModeBranches:
    async def test_put_same_mode_returns_200_without_new_ledger_row(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Re-PUT with the same mode should be a no-op (no extra ledger row)."""
        await _bootstrap_tenant(client, auth_headers)
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]
        # First select via POST.
        resp = await client.post(
            "/api/v1/onboarding/voice-mode",
            headers=auth_headers,
            json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
        )
        assert resp.status_code == 201

        # Now PUT the SAME mode — should short-circuit, no new row.
        resp2 = await client.put(
            "/api/v1/settings/outbound-voice",
            headers=auth_headers,
            json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
        )
        assert resp2.status_code == 200
        assert resp2.json()["voice_mode"] == "dyad_selva_plus_user"

        ledgers = (await db_session.execute(select(ConsentLedger))).scalars().all()
        # Only the original POST row — PUT same-mode did not append.
        assert len(ledgers) == 1


# ---------------------------------------------------------------------------
# GET /onboarding/tenant-identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTenantIdentityEndpoint:
    async def test_404_when_tenant_config_missing(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # No tenant created → 404.
        resp = await client.get("/api/v1/onboarding/tenant-identity", headers=auth_headers)
        assert resp.status_code == 404

    async def test_200_with_brand_name_only_when_no_identity_row(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await _bootstrap_tenant(client, auth_headers)
        # Set brand_name on the tenant config (no TenantIdentity row).
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.brand_name = "Acme Corp"
        await db_session.commit()

        resp = await client.get("/api/v1/onboarding/tenant-identity", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # No TenantIdentity row → user_email is None, user_name from brand_name.
        assert body["user_email"] is None
        assert body["user_name"] == "Acme Corp"
        # org_name falls back through legal_name → razon_social → brand_name.
        assert body["org_name"] == "Acme Corp"

    async def test_200_with_full_identity_resolution(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await _bootstrap_tenant(client, auth_headers)
        identity = TenantIdentity(
            canonical_id="dev-org",
            legal_name="Dev Org Legal Name SA de CV",
            primary_contact_email="founder@devorg.example",
        )
        db_session.add(identity)
        # Also set brand_name and razon_social on the tenant config.
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.brand_name = "DevOrg White-Label"
        tc.razon_social = "Dev Org Razón Social"
        await db_session.commit()

        resp = await client.get("/api/v1/onboarding/tenant-identity", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_email"] == "founder@devorg.example"
        # brand_name wins over legal_name + razon_social for user_name.
        assert body["user_name"] == "DevOrg White-Label"
        # org_name prefers legal_name over razon_social/brand_name.
        assert body["org_name"] == "Dev Org Legal Name SA de CV"

    async def test_200_with_razon_social_fallback_for_org_name(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """When legal_name absent but razon_social present, org_name falls through."""
        await _bootstrap_tenant(client, auth_headers)
        # Set razon_social only (no brand_name, no TenantIdentity row).
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.razon_social = "Solo Razón S.A. de C.V."
        await db_session.commit()

        resp = await client.get("/api/v1/onboarding/tenant-identity", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_email"] is None
        assert body["user_name"] == "Solo Razón S.A. de C.V."
        assert body["org_name"] == "Solo Razón S.A. de C.V."


# ---------------------------------------------------------------------------
# Pydantic validator: typed_confirmation length and mode validation
# ---------------------------------------------------------------------------


class TestVoiceModeSelectionValidator:
    def test_validator_rejects_unknown_mode(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ob.VoiceModeSelection(mode="not-a-mode", typed_confirmation="ok")

    def test_validator_accepts_all_three_legal_modes(self) -> None:
        for mode in _ob.VOICE_MODES:
            sel = _ob.VoiceModeSelection(mode=mode, typed_confirmation="x")
            assert sel.mode == mode


# ---------------------------------------------------------------------------
# verify_signature negative branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifySignatureBranches:
    async def test_naive_datetime_normalized_to_utc(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """verify_signature handles a naive (no tzinfo) created_at correctly."""
        from datetime import datetime

        await _bootstrap_tenant(client, auth_headers)
        phrase = CONSENT_CLAUSES["agent_identified"]["typed_phrase"]
        await client.post(
            "/api/v1/onboarding/voice-mode",
            headers=auth_headers,
            json={"mode": "agent_identified", "typed_confirmation": phrase},
        )

        entry = (await db_session.execute(select(ConsentLedger))).scalar_one()
        # Force a naive timestamp to exercise the tzinfo-None branch.
        entry.created_at = datetime(
            entry.created_at.year,
            entry.created_at.month,
            entry.created_at.day,
            entry.created_at.hour,
            entry.created_at.minute,
            entry.created_at.second,
        )
        # Signature must still verify after normalization.
        assert _ob.verify_signature(entry) is True


# ---------------------------------------------------------------------------
# Direct endpoint invocation — bypass FastAPI to give pytest-cov a clean
# stack frame for line tracking. The async-via-httpx-via-ASGI path
# loses trace events under some pytest-cov configurations.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEndpointsDirect:
    """Direct calls bypass FastAPI dependency injection and ASGI."""

    async def test_onboarding_status_direct_no_config(
        self, db_session: AsyncSession
    ) -> None:
        from nexus_api.routers.onboarding import onboarding_status

        out = await onboarding_status(user={"org_id": "ghost-org"}, db=db_session)
        assert out.voice_mode is None
        assert out.onboarding_complete is False

    async def test_onboarding_status_direct_with_config(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        from nexus_api.routers.onboarding import onboarding_status

        await _bootstrap_tenant(client, auth_headers)
        # Force a voice_mode on the tenant
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.voice_mode = "agent_identified"
        await db_session.commit()

        out = await onboarding_status(user={"org_id": "dev-org"}, db=db_session)
        assert out.voice_mode == "agent_identified"
        assert out.onboarding_complete is True

    async def test_voice_mode_preview_direct(self) -> None:
        from nexus_api.routers.onboarding import voice_mode_preview

        out = await voice_mode_preview(mode="user_direct")
        assert out.mode == "user_direct"
        assert "AI disclosure" in out.heads_up or "AI disclosure" in out.clause_body

    async def test_tenant_identity_direct_403_for_platform(
        self, db_session: AsyncSession
    ) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.onboarding import tenant_identity

        with pytest.raises(HTTPException) as exc:
            await tenant_identity(user={"org_id": "platform"}, db=db_session)
        assert exc.value.status_code == 403

    async def test_tenant_identity_direct_403_when_no_org(
        self, db_session: AsyncSession
    ) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.onboarding import tenant_identity

        with pytest.raises(HTTPException) as exc:
            await tenant_identity(user={}, db=db_session)
        assert exc.value.status_code == 403

    async def test_tenant_identity_direct_404_when_no_config(
        self, db_session: AsyncSession
    ) -> None:
        from fastapi import HTTPException

        from nexus_api.routers.onboarding import tenant_identity

        with pytest.raises(HTTPException) as exc:
            await tenant_identity(user={"org_id": "missing-org"}, db=db_session)
        assert exc.value.status_code == 404

    async def test_select_voice_mode_direct_409_when_already_set(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        from unittest.mock import MagicMock

        from fastapi import HTTPException

        from nexus_api.routers.onboarding import (
            CONSENT_CLAUSES,
            VoiceModeSelection,
            select_voice_mode,
        )

        await _bootstrap_tenant(client, auth_headers)
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.voice_mode = "dyad_selva_plus_user"
        await db_session.commit()

        request = MagicMock()
        request.headers = {"user-agent": "test"}
        request.client = MagicMock(host="127.0.0.1")
        body = VoiceModeSelection(
            mode="agent_identified",
            typed_confirmation=CONSENT_CLAUSES["agent_identified"]["typed_phrase"],
        )
        with pytest.raises(HTTPException) as exc:
            await select_voice_mode(
                body=body,
                request=request,
                user={"org_id": "dev-org", "sub": "u", "email": "u@x.io"},
                db=db_session,
            )
        assert exc.value.status_code == 409

    async def test_change_voice_mode_direct_same_mode_short_circuits(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        from unittest.mock import MagicMock

        from nexus_api.routers.onboarding import (
            CONSENT_CLAUSES,
            VoiceModeSelection,
            change_voice_mode,
        )

        await _bootstrap_tenant(client, auth_headers)
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.voice_mode = "dyad_selva_plus_user"
        await db_session.commit()

        request = MagicMock()
        request.headers = {"user-agent": "test"}
        request.client = MagicMock(host="127.0.0.1")
        body = VoiceModeSelection(
            mode="dyad_selva_plus_user",
            typed_confirmation=CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"],
        )
        out = await change_voice_mode(
            body=body,
            request=request,
            user={"org_id": "dev-org", "sub": "u", "email": "u@x.io"},
            db=db_session,
        )
        # Same mode → short-circuit, no new ledger row.
        assert out.voice_mode == "dyad_selva_plus_user"
        ledgers = (await db_session.execute(select(ConsentLedger))).scalars().all()
        assert len(ledgers) == 0

    async def test_change_voice_mode_direct_with_change(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        from unittest.mock import MagicMock

        from nexus_api.routers.onboarding import (
            CONSENT_CLAUSES,
            VoiceModeSelection,
            change_voice_mode,
        )

        await _bootstrap_tenant(client, auth_headers)
        tc = (await db_session.execute(select(TenantConfig))).scalar_one()
        tc.voice_mode = "dyad_selva_plus_user"
        await db_session.commit()

        request = MagicMock()
        request.headers = {"user-agent": "test"}
        request.client = MagicMock(host="127.0.0.1")
        body = VoiceModeSelection(
            mode="agent_identified",
            typed_confirmation=CONSENT_CLAUSES["agent_identified"]["typed_phrase"],
        )
        out = await change_voice_mode(
            body=body,
            request=request,
            user={"org_id": "dev-org", "sub": "u", "email": "u@x.io"},
            db=db_session,
        )
        assert out.voice_mode == "agent_identified"
        ledgers = (await db_session.execute(select(ConsentLedger))).scalars().all()
        assert len(ledgers) == 1
        assert ledgers[0].mode == "agent_identified"
