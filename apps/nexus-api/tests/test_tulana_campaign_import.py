"""Contract tests for Tulana SKU campaign import (Phase 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus_api.schemas.tulana_campaign import TulanaImportRequest, TulanaSkuCampaignPack
from nexus_api.services.tulana_campaign import import_tulana_packs, validate_pack


def _valid_pack(**overrides: object) -> TulanaSkuCampaignPack:
    base = {
        "sku_key": "avala__issuer",
        "platform": "avala",
        "audience": "credential issuers",
        "ga_readiness": "near_ready",
        "rank": 1,
        "value_prop": "Evidence-backed positioning",
        "proof_points": [
            {
                "label": "Comparator",
                "source": "Canvas Credentials",
                "url": "https://example.com/credentials",
            }
        ],
        "do_not_claim": ["Do not claim external legal approval"],
        "policy_state": "waived_by_operator",
        "last_verified_at": datetime(2026, 5, 29, tzinfo=UTC),
    }
    base.update(overrides)
    return TulanaSkuCampaignPack.model_validate(base)


class TestTulanaPackValidation:
    def test_valid_pack_accepted(self) -> None:
        pack = _valid_pack()
        result = validate_pack(pack, allow_blocked=False)
        assert result.accepted is True
        assert result.errors == []
        assert result.rank_score is not None

    def test_missing_do_not_claim_rejected(self) -> None:
        pack = _valid_pack(do_not_claim=[])
        result = validate_pack(pack, allow_blocked=False)
        assert result.accepted is False
        assert any("do_not_claim" in e for e in result.errors)

    def test_blocked_rejected_unless_allowed(self) -> None:
        pack = _valid_pack(ga_readiness="blocked")
        blocked = validate_pack(pack, allow_blocked=False)
        assert blocked.accepted is False
        allowed = validate_pack(pack, allow_blocked=True)
        assert allowed.accepted is True


class TestGuardCampaignDraft:
    def test_scrubs_do_not_claim(self) -> None:
        from nexus_api.services.tulana_campaign import guard_campaign_draft

        scrubbed, violations = guard_campaign_draft(
            "Buy now. Do not claim external legal approval.",
            ["Do not claim external legal approval"],
        )
        assert "external legal approval" not in scrubbed.lower()
        assert violations


class TestTulanaImportRanking:
    def test_ranks_near_ready_before_waived(self) -> None:
        near = _valid_pack(sku_key="a_near", ga_readiness="near_ready", rank=2)
        waived = _valid_pack(sku_key="b_waived", ga_readiness="waived", rank=1)
        result = import_tulana_packs(
            TulanaImportRequest(packs=[waived, near], allow_blocked=False)
        )
        assert result.ranked_sku_keys[0] == "a_near"
        assert len(result.rejected) == 0

    def test_mixed_accept_reject(self) -> None:
        good = _valid_pack()
        bad = _valid_pack(sku_key="bad_sku", do_not_claim=[])
        result = import_tulana_packs(TulanaImportRequest(packs=[good, bad]))
        assert len(result.accepted) == 1
        assert len(result.rejected) == 1
        assert result.rejected[0].sku_key == "bad_sku"


@pytest.mark.asyncio
async def test_import_tulana_pack_endpoint(client, auth_headers) -> None:
    payload = {
        "packs": [
            _valid_pack().model_dump(mode="json"),
            _valid_pack(sku_key="blocked_sku", ga_readiness="blocked").model_dump(mode="json"),
        ],
        "allow_blocked": False,
    }
    response = await client.post(
        "/api/v1/campaigns/import-tulana-pack",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ranked_sku_keys"] == ["avala__issuer"]
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["sku_key"] == "blocked_sku"


@pytest.mark.asyncio
async def test_import_idempotency_replay(client, auth_headers) -> None:
    payload = {"packs": [_valid_pack().model_dump(mode="json")]}
    headers = {**auth_headers, "Idempotency-Key": "tulana-test-key-1"}
    r1 = await client.post(
        "/api/v1/campaigns/import-tulana-pack",
        json=payload,
        headers=headers,
    )
    r2 = await client.post(
        "/api/v1/campaigns/import-tulana-pack",
        json=payload,
        headers=headers,
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_crm_handoff_endpoint(client, auth_headers) -> None:
    pack = _valid_pack()
    payload = {
        "sku_key": pack.sku_key,
        "audience": pack.audience,
        "draft_variants": ["Subject A", "Subject B"],
        "tulana_pack": pack.model_dump(mode="json"),
    }
    response = await client.post(
        "/api/v1/campaigns/crm-handoff",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["task_id"]
    assert body["handoff_id"]


@pytest.mark.asyncio
async def test_crm_handoff_rejects_invalid_pack(client, auth_headers) -> None:
    bad = _valid_pack(do_not_claim=[])
    payload = {
        "sku_key": bad.sku_key,
        "audience": bad.audience,
        "draft_variants": ["Draft"],
        "tulana_pack": bad.model_dump(mode="json"),
    }
    response = await client.post(
        "/api/v1/campaigns/crm-handoff",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tulana_feedback_requires_config(client, auth_headers) -> None:
    payload = {
        "sku_key": "avala__issuer",
        "summary": "Two demo calls booked from LinkedIn draft lane.",
        "outcomes": [{"metric": "demo_calls", "value": 2, "source": "phynd_crm"}],
    }
    with patch(
        "nexus_api.services.tulana_feedback._tulana_config",
        return_value=("", ""),
    ):
        response = await client.post(
            "/api/v1/campaigns/tulana-feedback",
            json=payload,
            headers=auth_headers,
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_tulana_feedback_forwards_to_tulana(client, auth_headers) -> None:
    payload = {
        "sku_key": "avala__issuer",
        "summary": "Campaign generated 12 MQLs with zero do_not_claim violations.",
        "outcomes": [{"metric": "mql_count", "value": 12}],
        "handoff_id": "handoff-123",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"event_id":"ev-99"}'
    mock_resp.json.return_value = {"event_id": "ev-99"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "nexus_api.services.tulana_feedback._tulana_config",
            return_value=("https://tulana.test", "secret"),
        ),
        patch(
            "nexus_api.services.tulana_feedback.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        response = await client.post(
            "/api/v1/campaigns/tulana-feedback",
            json=payload,
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["tulana_event_id"] == "ev-99"
    mock_client.post.assert_awaited_once()
