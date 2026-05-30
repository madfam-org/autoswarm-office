"""Tests for Tulana campaign planning graph and do_not_claim guardrails."""

from __future__ import annotations

from selva_workers.graphs.campaign import (
    build_campaign_graph,
    draft_copy,
    guard_campaign_draft,
    load_tulana_pack,
    plan_lane,
    schedule_social,
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
        assert result["campaign_lane"] == "avala__issuer::credential issuers::near_ready"

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

    def test_schedule_social_calls_nexus_api(self, monkeypatch) -> None:
        calls: list[dict] = []

        class FakeResponse:
            status_code = 201

            def json(self) -> dict:
                return {"count": 2}

            text = ""

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, headers=None, json=None):
                calls.append({"url": url, "headers": headers, "json": json})
                return FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: FakeClient())
        fake_settings = type(
            "S",
            (),
            {"nexus_api_url": "http://test:4300", "event_emit_timeout_seconds": 3},
        )()
        monkeypatch.setattr("selva_workers.config.get_settings", lambda: fake_settings)
        monkeypatch.setattr(
            "selva_workers.auth.get_worker_auth_headers",
            lambda org_id=None: {
                "Authorization": "Bearer test",
                "X-Selva-Tenant-Org": org_id or "",
            },
        )

        state = {
            "messages": [],
            "status": "draft_ready",
            "org_id": "org-test",
            "task_id": "task-1",
            "payload": {"reddit_subreddit": "selva"},
            "tulana_pack": {
                "sku_key": "avala__issuer",
                "audience": "issuers",
                "ga_readiness": "near_ready",
                "value_prop": "Proof-backed",
            },
            "draft_variants": ["Variant A body", "Variant B body"],
        }
        result = schedule_social(state)
        assert result["status"] == "scheduled"
        assert calls
        body = calls[0]["json"]
        assert body["sku_key"] == "avala__issuer"
        assert body["platform"] == "reddit"
        assert len(body["posts"]) == 3

