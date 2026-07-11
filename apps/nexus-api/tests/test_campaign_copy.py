"""Contract tests for the campaign-copy generation skill (roadmap §2 gap 2).

The LLM layer is fully mocked (``nexus_api.services.campaign_copy._get_router``)
so every test is deterministic. Coverage: claims filtering, the refusal path
(no campaign-permitted claims), claims enforcement on generated variants,
do_not_claim scrubbing, the response contract, and the ``social_post``
channel (body+cta shape + ``max_chars`` length policy, Lane 4.4).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from madfam_inference.types import InferenceResponse
from nexus_api.schemas.tulana_campaign import TulanaSkuCampaignPack
from nexus_api.services.campaign_copy import (
    _over_length_indexes,
    filter_campaign_claims,
    parse_copy_variants,
)

SAFE_CLAIM = {
    "feature_key": "cfdi_auto_issue",
    "feature_label": "Automatic CFDI issuance on checkout",
    "claim_class": "feature",
    "campaign_safe": True,
    "blocking_reasons": [],
    "claim_evidence_url": "https://example.com/evidence/cfdi",
    "notes": "Live in production since 2026-06-22",
}
SAFE_CLAIM_2 = {
    "feature_key": "lfpdppp_consent_ledger",
    "feature_label": "LFPDPPP-aligned consent ledger",
    "claim_class": "feature",
    "campaign_safe": True,
    "blocking_reasons": [],
}
BLOCKED_CLAIM = {
    "feature_key": "soc2_certification",
    "feature_label": "SOC 2 Type II certified",
    "claim_class": "positioning",
    "campaign_safe": False,
    "blocking_reasons": ["evidence_stale"],
}
INCONSISTENT_CLAIM = {
    # campaign_safe=true but blockers present — must fail closed.
    "feature_key": "uptime_sla",
    "feature_label": "99.99% uptime SLA",
    "campaign_safe": True,
    "blocking_reasons": ["claim_unverified"],
}


def _pack(**overrides: object) -> TulanaSkuCampaignPack:
    base: dict[str, Any] = {
        "sku_key": "karafiel__pro",
        "platform": "karafiel",
        "audience": "Mexican SMB compliance officers",
        "ga_readiness": "ready",
        "rank": 1,
        "value_prop": "Compliance without the paperwork burden",
        "proof_points": [
            {
                "label": "CFDI auto-issue live",
                "source": "karafiel production",
                "url": "https://example.com/evidence/cfdi",
            }
        ],
        "claims": [SAFE_CLAIM, SAFE_CLAIM_2, BLOCKED_CLAIM],
        "do_not_claim": ["SOC 2 certified", "guaranteed tax refunds"],
        "policy_state": "approved",
        "last_verified_at": datetime(2026, 7, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return TulanaSkuCampaignPack.model_validate(base)


def _llm_variant(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "subject": "Emite tu CFDI en automático",
        "preheader": "Cumplimiento sin fricción para tu equipo",
        "body": (
            "Karafiel emite el CFDI automáticamente al momento del checkout y "
            "mantiene un registro de consentimiento alineado con la LFPDPPP."
        ),
        "cta": "Agenda una demo",
        "claim_keys_used": ["cfdi_auto_issue", "lfpdppp_consent_ledger"],
    }
    base.update(overrides)
    return base


def _mock_router(*contents: str) -> MagicMock:
    """Router stub whose complete() returns each content string in order."""
    responses = [
        InferenceResponse(
            content=content,
            model="mock-model",
            provider="mock-provider",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
        for content in contents
    ]
    router = MagicMock()
    router.complete = AsyncMock(side_effect=responses)
    return router


def _copy_payload(pack: TulanaSkuCampaignPack, **overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tulana_pack": pack.model_dump(mode="json"),
        "audience": "opted-in Janua users in CDMX",
        "channel": "email",
        "language": "es-MX",
        "variant_count": 2,
    }
    base.update(overrides)
    return base


def _llm_social_variant(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "body": (
            "Karafiel emite el CFDI automáticamente al momento del checkout. "
            "Cumplimiento sin fricción para tu equipo."
        ),
        "cta": "Agenda una demo → karafiel.mx/demo",
        "claim_keys_used": ["cfdi_auto_issue"],
    }
    base.update(overrides)
    return base


def _social_payload(pack: TulanaSkuCampaignPack, **overrides: object) -> dict[str, Any]:
    base = _copy_payload(pack)
    base["channel"] = "social_post"
    base.update(overrides)
    return base


class TestClaimsFiltering:
    def test_separates_safe_from_blocked(self) -> None:
        safe, excluded = filter_campaign_claims(_pack())
        assert [c.feature_key for c in safe] == ["cfdi_auto_issue", "lfpdppp_consent_ledger"]
        assert [c.feature_key for c in excluded] == ["soc2_certification"]

    def test_safe_flag_with_blockers_fails_closed(self) -> None:
        pack = _pack(claims=[SAFE_CLAIM, INCONSISTENT_CLAIM])
        safe, excluded = filter_campaign_claims(pack)
        assert [c.feature_key for c in safe] == ["cfdi_auto_issue"]
        assert [c.feature_key for c in excluded] == ["uptime_sla"]

    def test_no_claims_yields_empty_safe_set(self) -> None:
        safe, excluded = filter_campaign_claims(_pack(claims=[]))
        assert safe == []
        assert excluded == []


class TestParseCopyVariants:
    def test_valid_payload(self) -> None:
        variants = parse_copy_variants(json.dumps({"variants": [_llm_variant()]}))
        assert len(variants) == 1

    @pytest.mark.parametrize(
        "content",
        ["not json", "[]", '{"variants": []}', '{"variants": ["a string"]}', '{"other": 1}'],
    )
    def test_contract_breaches_raise(self, content: str) -> None:
        with pytest.raises(ValueError):
            parse_copy_variants(content)


@pytest.mark.asyncio
async def test_generate_copy_happy_path_contract(client, auth_headers) -> None:
    llm_json = json.dumps({"variants": [_llm_variant(), _llm_variant(subject="Otra opción")]})
    router = _mock_router(llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack()),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["sku_key"] == "karafiel__pro"
    assert body["channel"] == "email"
    assert body["language"] == "es-MX"
    assert body["audience"] == "opted-in Janua users in CDMX"
    assert body["provider"] == "mock-provider"
    assert body["model"] == "mock-model"
    assert body["campaign_safe_claim_keys"] == ["cfdi_auto_issue", "lfpdppp_consent_ledger"]
    assert body["excluded_claim_keys"] == ["soc2_certification"]
    assert body["dropped_variants"] == []
    assert len(body["variants"]) == 2
    for variant in body["variants"]:
        assert variant["subject"]
        assert variant["body"]
        assert variant["cta"]
        assert variant["language"] == "es-MX"
        assert variant["claim_keys_used"]
        assert set(variant["claim_keys_used"]) <= set(body["campaign_safe_claim_keys"])
    router.complete.assert_awaited_once()
    # The prompt must never include the blocked claim's label.
    request = router.complete.await_args.args[0]
    prompt_text = request.system_prompt + json.dumps(request.messages)
    assert "SOC 2 Type II certified" not in prompt_text
    assert "cfdi_auto_issue" in prompt_text


@pytest.mark.asyncio
async def test_refuses_pack_without_claims(client, auth_headers) -> None:
    router = _mock_router()
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(claims=[])),
            headers=auth_headers,
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "no_campaign_safe_claims"
    assert detail["sku_key"] == "karafiel__pro"
    router.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_refuses_pack_with_only_blocked_claims(client, auth_headers) -> None:
    router = _mock_router()
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(claims=[BLOCKED_CLAIM, INCONSISTENT_CLAIM])),
            headers=auth_headers,
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "no_campaign_safe_claims"
    assert detail["excluded_claim_keys"] == ["soc2_certification", "uptime_sla"]
    router.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_invalid_pack(client, auth_headers) -> None:
    response_router = _mock_router()
    with patch("nexus_api.services.campaign_copy._get_router", return_value=response_router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(ga_readiness="blocked")),
            headers=auth_headers,
        )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_tulana_pack"
    response_router.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_variant_citing_blocked_claim_is_dropped(client, auth_headers) -> None:
    llm_json = json.dumps(
        {
            "variants": [
                _llm_variant(),
                _llm_variant(claim_keys_used=["soc2_certification"]),
                _llm_variant(claim_keys_used=[]),
            ]
        }
    )
    router = _mock_router(llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=3),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["variants"]) == 1
    assert body["variants"][0]["claim_keys_used"] == [
        "cfdi_auto_issue",
        "lfpdppp_consent_ledger",
    ]
    assert len(body["dropped_variants"]) == 2
    assert any("soc2_certification" in reason for reason in body["dropped_variants"])
    assert any("ungrounded" in reason for reason in body["dropped_variants"])


@pytest.mark.asyncio
async def test_all_variants_dropped_returns_502(client, auth_headers) -> None:
    llm_json = json.dumps({"variants": [_llm_variant(claim_keys_used=["soc2_certification"])]})
    router = _mock_router(llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error_code"] == "copy_generation_failed"
    assert detail["dropped_variants"]


@pytest.mark.asyncio
async def test_do_not_claim_phrases_are_scrubbed(client, auth_headers) -> None:
    dirty = _llm_variant(
        body="Karafiel emite el CFDI automáticamente. Somos SOC 2 certified y confiables.",
    )
    router = _mock_router(json.dumps({"variants": [dirty]}))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 200
    variant = response.json()["variants"][0]
    assert "soc 2 certified" not in variant["body"].lower()
    assert variant["guardrail_violations"] == ["SOC 2 certified"]


@pytest.mark.asyncio
async def test_malformed_llm_output_retries_then_502(client, auth_headers) -> None:
    router = _mock_router("not json at all", "still {not json")
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack()),
            headers=auth_headers,
        )
    assert response.status_code == 502
    assert response.json()["detail"]["error_code"] == "copy_generation_failed"
    assert router.complete.await_count == 2


@pytest.mark.asyncio
async def test_malformed_then_valid_output_recovers(client, auth_headers) -> None:
    router = _mock_router("not json", json.dumps({"variants": [_llm_variant()]}))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 200
    assert len(response.json()["variants"]) == 1
    assert router.complete.await_count == 2


@pytest.mark.asyncio
async def test_inference_unavailable_returns_503(client, auth_headers) -> None:
    router = MagicMock()
    router.complete = AsyncMock(side_effect=RuntimeError("all providers exhausted"))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack()),
            headers=auth_headers,
        )
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "inference_unavailable"


@pytest.mark.asyncio
async def test_english_output_optional(client, auth_headers) -> None:
    english = _llm_variant(
        subject="Issue your CFDI automatically",
        body="Karafiel issues the CFDI automatically at checkout.",
        cta="Book a demo",
        claim_keys_used=["cfdi_auto_issue"],
    )
    router = _mock_router(json.dumps({"variants": [english]}))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), language="en", variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "en"
    assert body["variants"][0]["language"] == "en"
    request = router.complete.await_args.args[0]
    assert "professional English" in request.system_prompt


class _FakeRedisPool:
    """In-memory stand-in for the idempotency cache (same pattern as
    ``test_idempotency_tier_1_adoption._FakeRedisPool``)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def execute_with_retry(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if method == "get":
            return self.store.get(args[0])
        if method == "set":
            self.store[args[0]] = args[1]
            return True
        raise AssertionError(f"unexpected redis method: {method}")


@pytest.mark.asyncio
async def test_generate_copy_idempotency_replay(client, auth_headers) -> None:
    router = _mock_router(json.dumps({"variants": [_llm_variant()]}))
    headers = {**auth_headers, "Idempotency-Key": "campaign-copy-test-key-1"}
    with (
        patch("selva_redis_pool.get_redis_pool", return_value=_FakeRedisPool()),
        patch("nexus_api.services.campaign_copy._get_router", return_value=router),
    ):
        r1 = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=1),
            headers=headers,
        )
        r2 = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_copy_payload(_pack(), variant_count=1),
            headers=headers,
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    router.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_copy_requires_auth(client) -> None:
    response = await client.post(
        "/api/v1/campaigns/generate-copy",
        json=_copy_payload(_pack()),
    )
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# social_post channel (Lane 4.4): same claims discipline, body+cta shape,
# max_chars length policy for the schedule-social posting targets
# (Mastodon 500 / Bluesky 300 → request default 300).
# ---------------------------------------------------------------------------


class TestSocialLengthPolicy:
    def test_over_length_indexes(self) -> None:
        variants = [
            {"body": "x" * 300},
            {"body": "x" * 301},
            {"body": None},
            {"cta": "no body at all"},
        ]
        assert _over_length_indexes(variants, 300) == [1]

    def test_strips_before_measuring(self) -> None:
        assert _over_length_indexes([{"body": " " + "x" * 300 + " "}], 300) == []


@pytest.mark.asyncio
async def test_social_post_happy_path(client, auth_headers) -> None:
    llm_json = json.dumps(
        {
            "variants": [
                _llm_social_variant(),
                _llm_social_variant(claim_keys_used=["lfpdppp_consent_ledger"]),
            ]
        }
    )
    router = _mock_router(llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack()),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "social_post"
    assert body["campaign_safe_claim_keys"] == ["cfdi_auto_issue", "lfpdppp_consent_ledger"]
    assert body["excluded_claim_keys"] == ["soc2_certification"]
    assert body["dropped_variants"] == []
    assert len(body["variants"]) == 2
    for variant in body["variants"]:
        assert variant["subject"] is None
        assert variant["preheader"] is None
        assert variant["body"]
        assert len(variant["body"]) <= 300  # default max_chars (Bluesky)
        assert variant["cta"]
        assert variant["claim_keys_used"]
        assert set(variant["claim_keys_used"]) <= set(body["campaign_safe_claim_keys"])
    router.complete.assert_awaited_once()
    request = router.complete.await_args.args[0]
    prompt_text = request.system_prompt + json.dumps(request.messages)
    # Social prompt asks for the post shape (no email fields) + length rule,
    # under the same claims discipline: blocked labels never enter the prompt.
    assert "at most 300 characters" in request.system_prompt
    assert '"subject"' not in request.system_prompt
    assert '"preheader"' not in request.system_prompt
    assert "SOC 2 Type II certified" not in prompt_text
    assert "cfdi_auto_issue" in prompt_text


@pytest.mark.asyncio
async def test_social_post_over_length_body_retried_then_dropped(client, auth_headers) -> None:
    over = _llm_social_variant(body="K" * 350)
    llm_json = json.dumps({"variants": [_llm_social_variant(), over]})
    # Same over-length output on both attempts → the offender is dropped.
    router = _mock_router(llm_json, llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack()),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["variants"]) == 1
    assert len(body["dropped_variants"]) == 1
    assert "max_chars" in body["dropped_variants"][0]
    assert "350 > 300" in body["dropped_variants"][0]
    # Exactly one length re-prompt happened before the drop.
    assert router.complete.await_count == 2
    retry_request = router.complete.await_args.args[0]
    assert "character body limit" in retry_request.messages[0]["content"]


@pytest.mark.asyncio
async def test_social_post_over_length_recovers_on_retry(client, auth_headers) -> None:
    over = json.dumps({"variants": [_llm_social_variant(body="K" * 350)]})
    good = json.dumps({"variants": [_llm_social_variant()]})
    router = _mock_router(over, good)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack(), variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["variants"]) == 1
    assert body["dropped_variants"] == []
    assert router.complete.await_count == 2


@pytest.mark.asyncio
async def test_social_post_max_chars_mastodon_500(client, auth_headers) -> None:
    body_400 = ("Karafiel emite el CFDI automáticamente. " * 10).strip()
    assert 300 < len(body_400) <= 500
    router = _mock_router(json.dumps({"variants": [_llm_social_variant(body=body_400)]}))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack(), variant_count=1, max_chars=500),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["dropped_variants"] == []
    assert len(body["variants"][0]["body"]) == len(body_400)
    # 400 chars fits the Mastodon-sized budget → no length re-prompt.
    router.complete.assert_awaited_once()
    request = router.complete.await_args.args[0]
    assert "at most 500 characters" in request.system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_max_chars", [60, 900])
async def test_social_post_max_chars_bounds_rejected(client, auth_headers, bad_max_chars) -> None:
    response = await client.post(
        "/api/v1/campaigns/generate-copy",
        json=_social_payload(_pack(), max_chars=bad_max_chars),
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_social_post_refuses_pack_without_safe_claims(client, auth_headers) -> None:
    router = _mock_router()
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack(claims=[BLOCKED_CLAIM, INCONSISTENT_CLAIM])),
            headers=auth_headers,
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "no_campaign_safe_claims"
    assert detail["excluded_claim_keys"] == ["soc2_certification", "uptime_sla"]
    router.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_social_variant_claims_enforcement(client, auth_headers) -> None:
    llm_json = json.dumps(
        {
            "variants": [
                _llm_social_variant(),
                _llm_social_variant(claim_keys_used=["soc2_certification"]),
                {"body": "Post sin CTA", "claim_keys_used": ["cfdi_auto_issue"]},
            ]
        }
    )
    router = _mock_router(llm_json)
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack(), variant_count=3),
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["variants"]) == 1
    assert body["variants"][0]["claim_keys_used"] == ["cfdi_auto_issue"]
    assert len(body["dropped_variants"]) == 2
    assert any("soc2_certification" in reason for reason in body["dropped_variants"])
    assert any("missing body/cta" in reason for reason in body["dropped_variants"])


@pytest.mark.asyncio
async def test_social_do_not_claim_phrases_are_scrubbed(client, auth_headers) -> None:
    dirty = _llm_social_variant(
        body="Karafiel emite el CFDI automáticamente. Somos SOC 2 certified.",
    )
    router = _mock_router(json.dumps({"variants": [dirty]}))
    with patch("nexus_api.services.campaign_copy._get_router", return_value=router):
        response = await client.post(
            "/api/v1/campaigns/generate-copy",
            json=_social_payload(_pack(), variant_count=1),
            headers=auth_headers,
        )
    assert response.status_code == 200
    variant = response.json()["variants"][0]
    assert "soc 2 certified" not in variant["body"].lower()
    assert variant["guardrail_violations"] == ["SOC 2 certified"]
