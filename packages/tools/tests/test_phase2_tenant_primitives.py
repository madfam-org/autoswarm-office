"""Tests for Phase 2 tenant-onboarding primitives.

Covers all 6 modules in a single file: registry shape, param schemas,
credential gating, happy path, error bubble-up. Uses httpx-client-level
mocks via ``patch()`` on each module's ``_request`` helper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from selva_tools.builtins.dhanam_provisioning import (
    DhanamCreditLedgerQueryTool,
    DhanamSpaceCreateTool,
    DhanamSubscriptionCreateTool,
    get_dhanam_provisioning_tools,
)
from selva_tools.builtins.janua_admin import (
    JanuaOauthClientCreateTool,
    JanuaOauthClientRotateSecretTool,
    get_janua_admin_tools,
)
from selva_tools.builtins.karafiel_provisioning import (
    KarafielOrgCreateTool,
    KarafielSatCertUploadTool,
    get_karafiel_provisioning_tools,
)
from selva_tools.builtins.phyndcrm_provisioning import (
    PhynecrmPipelineBootstrapTool,
    PhynecrmTenantCreateTool,
    get_phyndcrm_provisioning_tools,
)
from selva_tools.builtins.resend_domain import (
    ResendDomainAddTool,
    ResendDomainListTool,
    get_resend_domain_tools,
)
from selva_tools.builtins.tenant_identity import (
    TenantCreateIdentityRecordTool,
    TenantResolveTool,
    TenantValidateConsistencyTool,
    get_tenant_identity_tools,
)

# -- Registry shape ---------------------------------------------------------


class TestRegistries:
    def test_janua_admin_five_tools(self) -> None:
        assert {t.name for t in get_janua_admin_tools()} == {
            "janua_oauth_client_create",
            "janua_oauth_client_update",
            "janua_oauth_client_rotate_secret",
            "janua_oauth_client_delete",
            "janua_org_create",
        }

    def test_dhanam_four_tools(self) -> None:
        assert {t.name for t in get_dhanam_provisioning_tools()} == {
            "dhanam_space_create",
            "dhanam_subscription_create",
            "dhanam_subscription_update",
            "dhanam_credit_ledger_query",
        }

    def test_phyndcrm_three_tools(self) -> None:
        assert {t.name for t in get_phyndcrm_provisioning_tools()} == {
            "phyndcrm_tenant_create",
            "phyndcrm_pipeline_bootstrap",
            "phyndcrm_tenant_config_get",
        }

    def test_karafiel_four_tools(self) -> None:
        assert {t.name for t in get_karafiel_provisioning_tools()} == {
            "karafiel_org_create",
            "karafiel_sat_cert_upload",
            "karafiel_pac_register",
            "karafiel_invoice_series_create",
        }

    def test_resend_four_tools(self) -> None:
        assert {t.name for t in get_resend_domain_tools()} == {
            "resend_domain_add",
            "resend_domain_verify",
            "resend_domain_list",
            "resend_domain_delete",
        }

    def test_tenant_identity_three_tools(self) -> None:
        assert {t.name for t in get_tenant_identity_tools()} == {
            "tenant_create_identity_record",
            "tenant_resolve",
            "tenant_validate_consistency",
        }


# -- Credential gating ------------------------------------------------------


class TestCredentialGating:
    @pytest.mark.asyncio
    async def test_janua_missing_token(self) -> None:
        with patch("selva_tools.builtins.janua_admin.JANUA_ADMIN_TOKEN", ""):
            r = await JanuaOauthClientCreateTool().execute(name="x", redirect_uris=["https://x"])
            assert r.success is False
            assert "JANUA_ADMIN_TOKEN" in (r.error or "")

    @pytest.mark.asyncio
    async def test_dhanam_missing_token(self) -> None:
        with patch("selva_tools.builtins.dhanam_provisioning.DHANAM_ADMIN_TOKEN", ""):
            r = await DhanamSpaceCreateTool().execute(name="x")
            assert r.success is False
            assert "DHANAM_ADMIN_TOKEN" in (r.error or "")

    @pytest.mark.asyncio
    async def test_phyndcrm_missing_token(self) -> None:
        with patch("selva_tools.builtins.phyndcrm_provisioning.PHYNE_CRM_TOKEN", ""):
            r = await PhynecrmTenantCreateTool().execute(
                tenant_id="t", legal_name="x", primary_contact_email="a@b.c"
            )
            assert r.success is False
            assert "PHYNE_CRM_FEDERATION_TOKEN" in (r.error or "")

    @pytest.mark.asyncio
    async def test_karafiel_missing_token(self) -> None:
        with patch("selva_tools.builtins.karafiel_provisioning.KARAFIEL_ADMIN_TOKEN", ""):
            r = await KarafielOrgCreateTool().execute(
                rfc="ABC010101XYZ",
                razon_social="Test",
                regimen_fiscal="601",
                domicilio_fiscal_cp="62710",
            )
            assert r.success is False
            assert "KARAFIEL_ADMIN_TOKEN" in (r.error or "")

    @pytest.mark.asyncio
    async def test_resend_missing_key(self) -> None:
        with patch("selva_tools.builtins.resend_domain.RESEND_API_KEY", ""):
            r = await ResendDomainAddTool().execute(name="tenant.com")
            assert r.success is False
            assert "RESEND_API_KEY" in (r.error or "")

    @pytest.mark.asyncio
    async def test_tenant_identity_missing_token(self) -> None:
        with patch("selva_tools.builtins.tenant_identity.WORKER_API_TOKEN", ""):
            r = await TenantResolveTool().execute(lookup_field="janua_org_id", lookup_value="abc")
            assert r.success is False
            assert "WORKER_API_TOKEN" in (r.error or "")


# -- Happy-path per critical tool -------------------------------------------


class TestJanua:
    @pytest.mark.asyncio
    async def test_oauth_client_create_returns_secret(self) -> None:
        with (
            patch("selva_tools.builtins.janua_admin.JANUA_ADMIN_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.janua_admin._request",
                new=AsyncMock(
                    return_value=(
                        201,
                        {
                            "name": "tenant-app",
                            "client_id": "cid-1",
                            "client_secret": "sec-xxx",
                        },
                    )
                ),
            ),
        ):
            r = await JanuaOauthClientCreateTool().execute(
                name="tenant-app", redirect_uris=["https://tenant.com/cb"]
            )
            assert r.success is True
            assert r.data["client_id"] == "cid-1"
            assert r.data["client_secret"] == "sec-xxx"
            assert r.data["jwks_uri"].endswith("/.well-known/jwks.json")

    @pytest.mark.asyncio
    async def test_rotate_returns_new_secret(self) -> None:
        with (
            patch("selva_tools.builtins.janua_admin.JANUA_ADMIN_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.janua_admin._request",
                new=AsyncMock(
                    return_value=(
                        200,
                        {"client_secret": "new-sec", "expires_old_secret_at": "2026-04-25"},
                    )
                ),
            ),
        ):
            r = await JanuaOauthClientRotateSecretTool().execute(client_id="cid")
            assert r.success is True
            assert r.data["client_secret"] == "new-sec"
            assert r.data["expires_old_secret_at"] == "2026-04-25"


class TestDhanam:
    @pytest.mark.asyncio
    async def test_space_create_returns_space_id(self) -> None:
        with (
            patch("selva_tools.builtins.dhanam_provisioning.DHANAM_ADMIN_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.dhanam_provisioning._request",
                new=AsyncMock(return_value=(201, {"id": "sp-1", "name": "tenant"})),
            ),
        ):
            r = await DhanamSpaceCreateTool().execute(name="tenant")
            assert r.success is True
            assert r.data["space_id"] == "sp-1"

    @pytest.mark.asyncio
    async def test_subscription_create_with_credit_ceiling(self) -> None:
        captured: dict = {}

        async def fake(method, path, json_body=None):
            captured["path"] = path
            captured["json_body"] = json_body
            return 201, {"id": "sub-1", "plan_id": "growth", "status": "active"}

        with (
            patch("selva_tools.builtins.dhanam_provisioning.DHANAM_ADMIN_TOKEN", "tok"),
            patch("selva_tools.builtins.dhanam_provisioning._request", new=fake),
        ):
            r = await DhanamSubscriptionCreateTool().execute(
                space_id="sp-1",
                plan_id="growth",
                credit_ceiling_cents=50000,
            )
            assert r.success is True
            assert captured["path"] == "/spaces/sp-1/subscriptions"
            assert captured["json_body"]["credit_ceiling_cents"] == 50000

    @pytest.mark.asyncio
    async def test_credit_ledger_query(self) -> None:
        with (
            patch("selva_tools.builtins.dhanam_provisioning.DHANAM_ADMIN_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.dhanam_provisioning._request",
                new=AsyncMock(
                    return_value=(
                        200,
                        {"used_cents": 12000, "ceiling_cents": 50000},
                    )
                ),
            ),
        ):
            r = await DhanamCreditLedgerQueryTool().execute(space_id="sp-1")
            assert r.success is True
            assert "12000" in r.output


class TestPhynecrm:
    @pytest.mark.asyncio
    async def test_pipeline_bootstrap_default_stages(self) -> None:
        captured: dict = {}

        async def fake(proc, input_data=None):
            captured["proc"] = proc
            captured["input"] = input_data
            return 200, {
                "result": {"data": {"json": {"id": "pip-1", "name": "Default Sales Pipeline"}}}
            }

        with (
            patch("selva_tools.builtins.phyndcrm_provisioning.PHYNE_CRM_TOKEN", "tok"),
            patch("selva_tools.builtins.phyndcrm_provisioning._trpc", new=fake),
        ):
            r = await PhynecrmPipelineBootstrapTool().execute(tenant_id="t-1")
            assert r.success is True
            # 6 default stages
            assert r.data["stage_count"] == 6
            assert captured["proc"] == "pipelines.createWithStages"

    @pytest.mark.asyncio
    async def test_tenant_create_passes_voice_mode_when_provided(self) -> None:
        captured: dict = {}

        async def fake(proc, input_data=None):
            captured["input"] = input_data
            return 200, {"result": {"data": {"json": {}}}}

        with (
            patch("selva_tools.builtins.phyndcrm_provisioning.PHYNE_CRM_TOKEN", "tok"),
            patch("selva_tools.builtins.phyndcrm_provisioning._trpc", new=fake),
        ):
            await PhynecrmTenantCreateTool().execute(
                tenant_id="t",
                legal_name="LN",
                primary_contact_email="a@b.c",
                voice_mode="dyad_selva_plus_user",
            )
            assert captured["input"]["voice_mode"] == "dyad_selva_plus_user"


class TestKarafiel:
    @pytest.mark.asyncio
    async def test_org_create_returns_org_id(self) -> None:
        with (
            patch("selva_tools.builtins.karafiel_provisioning.KARAFIEL_ADMIN_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.karafiel_provisioning._request",
                new=AsyncMock(return_value=(201, {"id": "org-1", "rfc": "IMS2604184U1"})),
            ),
        ):
            r = await KarafielOrgCreateTool().execute(
                rfc="IMS2604184U1",
                razon_social="Innovaciones MADFAM S.A.S. de C.V.",
                regimen_fiscal="601",
                domicilio_fiscal_cp="62710",
            )
            assert r.success is True
            assert r.data["org_id"] == "org-1"
            assert r.data["sat_cert_uploaded"] is False

    @pytest.mark.asyncio
    async def test_sat_cert_upload_rejects_invalid_base64(self) -> None:
        with patch("selva_tools.builtins.karafiel_provisioning.KARAFIEL_ADMIN_TOKEN", "tok"):
            r = await KarafielSatCertUploadTool().execute(
                org_id="org",
                cer_base64="not valid base64 !!!",
                key_base64="AAAA",
                key_password="x",
            )
            assert r.success is False
            assert "decode cleanly" in (r.error or "")


class TestResend:
    @pytest.mark.asyncio
    async def test_domain_add_surfaces_dns_records(self) -> None:
        with (
            patch("selva_tools.builtins.resend_domain.RESEND_API_KEY", "key"),
            patch(
                "selva_tools.builtins.resend_domain._request",
                new=AsyncMock(
                    return_value=(
                        201,
                        {
                            "id": "d-1",
                            "name": "tenant.com",
                            "status": "not_started",
                            "records": [
                                {
                                    "record": "SPF",
                                    "type": "TXT",
                                    "value": "v=spf1 include:amazonses.com ~all",
                                },
                                {
                                    "record": "DKIM",
                                    "type": "CNAME",
                                    "value": "resend._domainkey.tenant.com",
                                },
                            ],
                        },
                    )
                ),
            ),
        ):
            r = await ResendDomainAddTool().execute(name="tenant.com")
            assert r.success is True
            assert r.data["domain_id"] == "d-1"
            assert len(r.data["records"]) == 2

    @pytest.mark.asyncio
    async def test_domain_list(self) -> None:
        with (
            patch("selva_tools.builtins.resend_domain.RESEND_API_KEY", "key"),
            patch(
                "selva_tools.builtins.resend_domain._request",
                new=AsyncMock(
                    return_value=(
                        200,
                        {
                            "data": [
                                {
                                    "id": "d-1",
                                    "name": "madfam.io",
                                    "status": "verified",
                                    "region": "us-east-1",
                                }
                            ]
                        },
                    )
                ),
            ),
        ):
            r = await ResendDomainListTool().execute()
            assert r.success is True
            assert r.data["domains"][0]["name"] == "madfam.io"


class TestTenantIdentity:
    @pytest.mark.asyncio
    async def test_create_record_round_trip(self) -> None:
        with (
            patch("selva_tools.builtins.tenant_identity.WORKER_API_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.tenant_identity._request",
                new=AsyncMock(return_value=(201, {"id": "ti-1"})),
            ),
        ):
            r = await TenantCreateIdentityRecordTool().execute(
                canonical_id="org-janua-123",
                legal_name="Tenant Inc.",
                janua_org_id="org-janua-123",
                dhanam_space_id="sp-1",
                phyndcrm_tenant_id="t-1",
            )
            assert r.success is True
            assert r.data["canonical_id"] == "org-janua-123"

    @pytest.mark.asyncio
    async def test_resolve_not_found_returns_structured_error(self) -> None:
        with (
            patch("selva_tools.builtins.tenant_identity.WORKER_API_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.tenant_identity._request",
                new=AsyncMock(return_value=(404, {"detail": "Not found"})),
            ),
        ):
            r = await TenantResolveTool().execute(
                lookup_field="janua_org_id", lookup_value="missing"
            )
            assert r.success is False
            assert "no tenant found" in (r.error or "")

    @pytest.mark.asyncio
    async def test_validate_consistency_reports_drifts(self) -> None:
        with (
            patch("selva_tools.builtins.tenant_identity.WORKER_API_TOKEN", "tok"),
            patch(
                "selva_tools.builtins.tenant_identity._request",
                new=AsyncMock(
                    return_value=(
                        200,
                        {
                            "canonical_id": "org-1",
                            "services_checked": 4,
                            "drifts": [
                                {
                                    "service": "karafiel",
                                    "id": "k-1",
                                    "reason": "org returned 404",
                                }
                            ],
                        },
                    )
                ),
            ),
        ):
            r = await TenantValidateConsistencyTool().execute(canonical_id="org-1")
            assert r.success is True
            assert r.data["drifts"][0]["service"] == "karafiel"
