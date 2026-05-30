"""Tests for Tulana campaign planning graph and do_not_claim guardrails."""

from __future__ import annotations

from selva_workers.graphs.campaign import (
    build_campaign_graph,
    draft_copy,
    guard_campaign_draft,
    load_tulana_pack,
    plan_lane,
)


class TestGuardCampaignDraft:
    def test_scrubs_do_not_claim_phrase(self) -> None:
        draft = "Great product. Do not claim external legal approval. Buy now."
        scrubbed, violations = guard_campaign_draft(
            draft,
            ["Do not claim external legal approval"],
        )
        assert "legal approval" not in scrubbed.lower() or scrubbed == "Great product. Buy now."
        assert "Do not claim external legal approval" in violations

    def test_clean_draft_has_no_violations(self) -> None:
        scrubbed, violations = guard_campaign_draft(
            "Evidence-backed positioning for credential issuers.",
            ["Do not claim external legal approval"],
        )
        assert violations == []
        assert "Evidence-backed" in scrubbed


class TestCampaignGraphStructure:
    def test_build_campaign_graph(self) -> None:
        graph = build_campaign_graph()
        assert graph is not None

    def test_campaign_in_graph_builders(self) -> None:
        from selva_workers.__main__ import GRAPH_BUILDERS

        assert "campaign" in GRAPH_BUILDERS


class TestCampaignNodes:
    def test_load_tulana_pack_missing_payload(self) -> None:
        result = load_tulana_pack({"messages": [], "payload": {}})
        assert result["status"] == "error"

    def test_plan_lane_sets_lane_id(self) -> None:
        state = {
            "messages": [],
            "tulana_pack": {
                "sku_key": "avala__issuer",
                "audience": "credential issuers",
                "ga_readiness": "near_ready",
            },
        }
        result = plan_lane(state)
        assert "avala__issuer::credential issuers::near_ready" == result["campaign_lane"]

    def test_draft_copy_scrubs_do_not_claim(self) -> None:
        state = {
            "messages": [],
            "tulana_pack": {
                "sku_key": "avala__issuer",
                "audience": "credential issuers",
                "ga_readiness": "near_ready",
                "value_prop": "Evidence-backed positioning",
                "proof_points": [{"label": "Comparator", "source": "Canvas"}],
                "do_not_claim": ["Do not claim external legal approval"],
            },
        }
        result = draft_copy(state)
        assert result["status"] in {"draft_ready", "draft_ready_with_scrub"}
        joined = "\n".join(result.get("draft_variants") or [])
        assert "external legal approval" not in joined.lower()

    def test_campaign_timeout_configured(self) -> None:
        from selva_redis_pool.timeout import DEFAULT_TIMEOUTS

        assert DEFAULT_TIMEOUTS["campaign"] == 300
