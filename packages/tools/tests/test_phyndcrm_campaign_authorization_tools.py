"""Tests for the PhyndCRM campaign-authorization tools (owner money-gate).

phynd-crm owns the ledger and the fail-closed send gate; these tools relay
review state and the OWNER's decision. The tests cover credential gating,
PLATFORM audience tagging, operator/note requirements (enforced locally
before any network call), superjson envelope handling, and error surfacing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins.phyndcrm_campaign_authorizations import (
    PhyndcrmCampaignAuthorizationDecideTool,
    PhyndcrmCampaignAuthorizationPreviewTool,
    PhyndcrmCampaignAuthorizationRequestTool,
    PhyndcrmCampaignAuthorizationsPendingTool,
    get_phyndcrm_campaign_authorization_tools,
)

_MOD = "selva_tools.builtins.phyndcrm_campaign_authorizations"


def _wrap(json_payload: object) -> dict:
    """tRPC superjson success envelope."""
    return {"result": {"data": {"json": json_payload}}}


_PENDING_ROW = {
    "authorization": {
        "id": "auth-1",
        "campaignId": "camp-1",
        "status": "pending",
        "requestedBy": "staff@madfam.io",
        "createdAt": "2026-07-19T20:00:00.000Z",
        "snapshot": {
            "payload": {
                "name": "Dhanam — dhanam__essentials",
                "variants": [{"variantId": "v1"}, {"variantId": "v2"}],
            },
            "context": {
                "coverage": {"grantedNotSuppressed": 2, "contactsWithEmail": 6},
            },
        },
    },
    "campaign": {
        "id": "camp-1",
        "name": "Dhanam — dhanam__essentials",
        "skuKey": "dhanam__essentials",
    },
}

_PREVIEW = {
    "authorization": {"id": "auth-1", "campaignId": "camp-1", "status": "pending"},
    "stale": False,
    "snapshot": {
        "payload": {
            "name": "Dhanam — dhanam__essentials",
            "skuKey": "dhanam__essentials",
            "channel": "email",
            "sender": "MADFAM <noreply@madfam.io>",
            "privacyUrl": "https://app.dhan.am/privacy",
            "schedule": {"startDate": None, "endDate": None},
            "audienceDefinition": "consumidores con opt-in doble",
            "guardrailsDoNotClaim": ["No prometer sincronización bancaria en vivo"],
            "variants": [
                {
                    "variantId": "es-a",
                    "language": "es-MX",
                    "subject": "Tus finanzas en orden",
                    "preheader": "En minutos",
                    "body": "Hola:\nCuerpo del correo.",
                    "cta": "Probar",
                    "ctaUrl": "https://app.dhan.am/register",
                    "claimKeysUsed": ["statement_import_csv_pdf"],
                }
            ],
        },
        "context": {
            "capturedAt": "2026-07-19T20:00:00.000Z",
            "proofPoints": [{"label": "Price", "value": "MX$150/month"}],
            "coverage": {
                "contactsWithEmail": 6,
                "consent": {"granted": 3, "pendingDoubleOptIn": 1, "revoked": 0},
                "suppressed": 1,
                "grantedNotSuppressed": 2,
            },
        },
    },
    "rendered": [{"variantId": "es-a", "subject": "Tus finanzas en orden", "html": "<html/>"}],
}


class TestAudienceAndRegistration:
    def test_all_tools_are_platform_audience(self) -> None:
        for tool in get_phyndcrm_campaign_authorization_tools():
            assert tool.audience is Audience.PLATFORM, tool.name

    def test_exports_four_tools(self) -> None:
        names = {t.name for t in get_phyndcrm_campaign_authorization_tools()}
        assert names == {
            "phyndcrm_campaign_authorizations_pending",
            "phyndcrm_campaign_authorization_preview",
            "phyndcrm_campaign_authorization_decide",
            "phyndcrm_campaign_authorization_request",
        }

    def test_names_carry_crm_for_hitl_classifier(self) -> None:
        # The permission classifier maps 'crm' substring → CRM_UPDATE (ASK),
        # so the decide/request mutations stay HITL-gated inside Selva too.
        for tool in get_phyndcrm_campaign_authorization_tools():
            assert "crm" in tool.name


class TestCredentialGating:
    @pytest.mark.asyncio
    async def test_all_tools_fail_closed_without_token(self) -> None:
        with patch(f"{_MOD}.PHYND_CRM_TOKEN", ""):
            results = [
                await PhyndcrmCampaignAuthorizationsPendingTool().execute(),
                await PhyndcrmCampaignAuthorizationPreviewTool().execute(
                    authorization_id="auth-1"
                ),
                await PhyndcrmCampaignAuthorizationDecideTool().execute(
                    authorization_id="auth-1", decision="authorize", operator="o@x.mx"
                ),
                await PhyndcrmCampaignAuthorizationRequestTool().execute(campaign_id="camp-1"),
            ]
        for result in results:
            assert result.success is False
            assert "PHYND_CRM_FEDERATION_TOKEN" in (result.error or "")


class TestPendingList:
    @pytest.mark.asyncio
    async def test_lists_pending_with_ids_and_honest_coverage(self) -> None:
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_query",
                new=AsyncMock(return_value=(200, _wrap([_PENDING_ROW]))),
            ) as mock_query,
        ):
            result = await PhyndcrmCampaignAuthorizationsPendingTool().execute()
        assert result.success is True
        assert mock_query.await_args.args[0] == "campaignAuthorizations.listPending"
        assert "auth-1" in result.output
        assert "2 variant(s)" in result.output
        assert "sendable today 2 of 6" in result.output
        assert result.data["pending"][0]["authorization_id"] == "auth-1"

    @pytest.mark.asyncio
    async def test_empty_queue(self) -> None:
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(f"{_MOD}._trpc_query", new=AsyncMock(return_value=(200, _wrap([])))),
        ):
            result = await PhyndcrmCampaignAuthorizationsPendingTool().execute()
        assert result.success is True
        assert "No campaigns" in result.output
        assert result.data == {"pending": []}


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_surfaces_guardrails_coverage_and_variants(self) -> None:
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_query",
                new=AsyncMock(return_value=(200, _wrap(_PREVIEW))),
            ) as mock_query,
        ):
            result = await PhyndcrmCampaignAuthorizationPreviewTool().execute(
                authorization_id="auth-1"
            )
        assert result.success is True
        assert mock_query.await_args.args[0] == "campaignAuthorizations.getPreview"
        assert mock_query.await_args.args[1] == {"id": "auth-1"}
        # The review must carry the load-bearing facts verbatim.
        assert "MADFAM <noreply@madfam.io>" in result.output
        assert "No prometer sincronización bancaria en vivo" in result.output
        assert "SENDABLE TODAY (granted, not suppressed): 2" in result.output
        assert "Tus finanzas en orden" in result.output
        assert "statement_import_csv_pdf" in result.output
        assert "STALE" not in result.output
        # Rendered production HTML rides in data for card-capable surfaces.
        assert result.data["rendered"][0]["html"] == "<html/>"

    @pytest.mark.asyncio
    async def test_preview_flags_stale_snapshot(self) -> None:
        stale_preview = {**_PREVIEW, "stale": True}
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_query",
                new=AsyncMock(return_value=(200, _wrap(stale_preview))),
            ),
        ):
            result = await PhyndcrmCampaignAuthorizationPreviewTool().execute(
                authorization_id="auth-1"
            )
        assert result.success is True
        assert "STALE" in result.output
        assert result.data["stale"] is True


class TestDecide:
    @pytest.mark.asyncio
    async def test_reject_requires_note_before_any_network_call(self) -> None:
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(f"{_MOD}._trpc_mutate", new=AsyncMock()) as mock_mutate,
        ):
            result = await PhyndcrmCampaignAuthorizationDecideTool().execute(
                authorization_id="auth-1", decision="reject", operator="owner@madfam.io"
            )
        assert result.success is False
        assert "note" in (result.error or "").lower()
        mock_mutate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_operator_required_before_any_network_call(self) -> None:
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(f"{_MOD}._trpc_mutate", new=AsyncMock()) as mock_mutate,
        ):
            result = await PhyndcrmCampaignAuthorizationDecideTool().execute(
                authorization_id="auth-1", decision="authorize", operator="   "
            )
        assert result.success is False
        assert "operator" in (result.error or "").lower()
        mock_mutate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorize_relays_operator_as_actor(self) -> None:
        record = {
            "id": "auth-1",
            "status": "authorized",
            "decidedBy": "owner@madfam.io (via service:selva)",
            "decidedVia": "selva",
            "decidedAt": "2026-07-19T21:00:00.000Z",
            "decisionNote": None,
        }
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_mutate",
                new=AsyncMock(return_value=(200, _wrap(record))),
            ) as mock_mutate,
        ):
            result = await PhyndcrmCampaignAuthorizationDecideTool().execute(
                authorization_id="auth-1",
                decision="authorize",
                operator="owner@madfam.io",
            )
        assert result.success is True
        assert mock_mutate.await_args.args[0] == "campaignAuthorizations.decide"
        sent = mock_mutate.await_args.args[1]
        assert sent == {
            "id": "auth-1",
            "decision": "authorized",
            "actor": "owner@madfam.io",
        }
        assert result.data["status"] == "authorized"
        assert "voids this authorization" in result.output

    @pytest.mark.asyncio
    async def test_reject_with_note_parks_campaign(self) -> None:
        record = {
            "id": "auth-1",
            "status": "rejected",
            "decidedBy": "owner@madfam.io (via service:selva)",
            "decidedVia": "selva",
            "decidedAt": "2026-07-19T21:00:00.000Z",
            "decisionNote": "Cifras no cuadran",
        }
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_mutate",
                new=AsyncMock(return_value=(200, _wrap(record))),
            ) as mock_mutate,
        ):
            result = await PhyndcrmCampaignAuthorizationDecideTool().execute(
                authorization_id="auth-1",
                decision="reject",
                operator="owner@madfam.io",
                note="Cifras no cuadran",
            )
        assert result.success is True
        sent = mock_mutate.await_args.args[1]
        assert sent["decision"] == "rejected"
        assert sent["note"] == "Cifras no cuadran"
        assert "parked" in result.output

    @pytest.mark.asyncio
    async def test_trpc_error_is_surfaced(self) -> None:
        # e.g. phynd refuses to authorize a drifted snapshot (hash mismatch).
        error_body = {
            "error": {"json": {"message": "Campaign changed after this authorization request"}}
        }
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(f"{_MOD}._trpc_mutate", new=AsyncMock(return_value=(400, error_body))),
        ):
            result = await PhyndcrmCampaignAuthorizationDecideTool().execute(
                authorization_id="auth-1",
                decision="authorize",
                operator="owner@madfam.io",
            )
        assert result.success is False
        assert "changed after" in (result.error or "")


class TestRequest:
    @pytest.mark.asyncio
    async def test_request_creates_fresh_pending(self) -> None:
        record = {"id": "auth-2", "campaignId": "camp-1", "status": "pending"}
        with (
            patch(f"{_MOD}.PHYND_CRM_TOKEN", "tok"),
            patch(
                f"{_MOD}._trpc_mutate",
                new=AsyncMock(return_value=(200, _wrap(record))),
            ) as mock_mutate,
        ):
            result = await PhyndcrmCampaignAuthorizationRequestTool().execute(
                campaign_id="camp-1"
            )
        assert result.success is True
        assert mock_mutate.await_args.args[0] == "campaignAuthorizations.request"
        assert mock_mutate.await_args.args[1] == {"campaignId": "camp-1"}
        assert result.data["authorization_id"] == "auth-2"
