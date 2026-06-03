"""Tests for the market intelligence workflow graph."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestIntelligenceGraphStructure:
    """Intelligence graph has correct nodes and edges."""

    def test_build_intelligence_graph(self) -> None:
        from selva_workers.graphs.intelligence import build_intelligence_graph

        graph = build_intelligence_graph()
        node_names = set(graph.nodes.keys())
        assert "scan_dof" in node_names
        assert "fetch_economic_data" in node_names
        assert "generate_briefing" in node_names
        assert "notify_team" in node_names

    def test_graph_compiles(self) -> None:
        from selva_workers.graphs.intelligence import build_intelligence_graph

        graph = build_intelligence_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_intelligence_state_fields(self) -> None:
        from selva_workers.graphs.intelligence import IntelligenceState

        annotations = IntelligenceState.__annotations__
        assert "org_id" in annotations
        assert "dof_results" in annotations
        assert "exchange_rate" in annotations
        assert "economic_indicators" in annotations
        assert "briefing_text" in annotations


class TestScanDOFNode:
    """scan_dof() scans the DOF for regulatory changes."""

    def test_scan_dof_fallback_when_crawler_unavailable(self) -> None:
        """When the crawler is down, scan_dof returns empty results."""
        from selva_workers.graphs.intelligence import scan_dof

        with patch(
            "madfam_inference.adapters.crawler.CrawlerAdapter.search_dof",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ):
            result = scan_dof(
                {
                    "messages": [],
                    "description": "reforma fiscal RESICO",
                }
            )

        assert result["status"] == "scanning_dof"
        assert result["dof_results"] == []
        assert len(result["messages"]) == 1

    def test_scan_dof_with_results(self) -> None:
        """When the crawler returns entries, they are stored in state."""
        from selva_workers.graphs.intelligence import scan_dof

        mock_entries = [
            {"title": "Reforma Fiscal 2026", "date": "2026-04-10"},
            {"title": "Salario Minimo", "date": "2026-04-12"},
        ]

        with patch(
            "madfam_inference.adapters.crawler.CrawlerAdapter.search_dof",
            new_callable=AsyncMock,
            return_value=mock_entries,
        ):
            result = scan_dof(
                {
                    "messages": [],
                    "description": "reforma fiscal",
                }
            )

        assert result["status"] == "scanning_dof"
        assert len(result["dof_results"]) == 2
        assert result["dof_results"][0]["title"] == "Reforma Fiscal 2026"

    def test_scan_dof_default_query_when_empty_description(self) -> None:
        """When description is empty, a default query is used."""
        from selva_workers.graphs.intelligence import scan_dof

        with patch(
            "madfam_inference.adapters.crawler.CrawlerAdapter.search_dof",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            scan_dof(
                {
                    "messages": [],
                    "description": "",
                }
            )

        # Should have called with a default query
        call_args = mock_search.call_args
        query = call_args[0][0]
        assert len(query) > 0


class TestFetchEconomicDataNode:
    """fetch_economic_data() fetches indicators via Dhanam."""

    def test_fetch_economic_data_success(self) -> None:
        """When Dhanam responds, all indicators are aggregated."""
        from madfam_inference.adapters.dhanam import EconomicIndicator, ExchangeRate
        from selva_workers.graphs.intelligence import fetch_economic_data

        with (
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_exchange_rate",
                new_callable=AsyncMock,
                return_value=ExchangeRate(date="14/04/2026", rate="17.05", currency_pair="USD/MXN"),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_tiie",
                new_callable=AsyncMock,
                return_value=EconomicIndicator(
                    series_id="SF43783", name="TIIE 28", date="14/04/2026", value="11.25"
                ),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_inflation",
                new_callable=AsyncMock,
                return_value=EconomicIndicator(
                    series_id="SP74665", name="INPC", date="14/04/2026", value="4.21"
                ),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_uma",
                new_callable=AsyncMock,
                return_value=EconomicIndicator(
                    series_id="SP74668", name="UMA", date="14/04/2026", value="113.14"
                ),
            ),
        ):
            result = fetch_economic_data({"messages": []})

        assert result["status"] == "fetching_economic_data"
        assert result["exchange_rate"] is not None
        assert result["exchange_rate"]["rate"] == "17.05"
        indicators = result["economic_indicators"]
        assert "exchange_rate" in indicators
        assert "tiie_28" in indicators
        assert "inflation" in indicators
        assert "uma" in indicators

    def test_fetch_economic_data_partial_failure(self) -> None:
        """If one indicator fails, others still succeed."""
        from madfam_inference.adapters.dhanam import EconomicIndicator, ExchangeRate
        from selva_workers.graphs.intelligence import fetch_economic_data

        with (
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_exchange_rate",
                new_callable=AsyncMock,
                return_value=ExchangeRate(date="14/04/2026", rate="17.05", currency_pair="USD/MXN"),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_tiie",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Timeout"),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_inflation",
                new_callable=AsyncMock,
                return_value=EconomicIndicator(
                    series_id="SP74665", name="INPC", date="14/04/2026", value="4.21"
                ),
            ),
            patch(
                "madfam_inference.adapters.dhanam.DhanamAdapter.get_uma",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Timeout"),
            ),
        ):
            result = fetch_economic_data({"messages": []})

        indicators = result["economic_indicators"]
        # exchange_rate and inflation should succeed; tiie and uma should be missing
        assert "exchange_rate" in indicators
        assert "inflation" in indicators
        assert "tiie_28" not in indicators
        assert "uma" not in indicators


class TestGenerateBriefingNode:
    """generate_briefing() produces an executive briefing."""

    def test_generate_briefing_fallback(self) -> None:
        """When no LLM is configured, a structured fallback is generated."""
        from selva_workers.graphs.intelligence import generate_briefing

        with patch(
            "selva_workers.inference.get_model_router",
            side_effect=RuntimeError("no providers"),
        ):
            result = generate_briefing(
                {
                    "messages": [],
                    "dof_results": [{"title": "Reforma Fiscal", "date": "2026-04-10"}],
                    "economic_indicators": {
                        "exchange_rate": {"rate": "17.05", "currency_pair": "USD/MXN"},
                        "inflation": {"value": "4.21"},
                    },
                }
            )

        assert result["status"] == "briefing_generated"
        assert result["briefing_text"]
        assert "Reforma Fiscal" in result["briefing_text"]
        assert "17.05" in result["briefing_text"]

    def test_generate_briefing_with_llm(self) -> None:
        """When an LLM is configured, it produces the briefing text."""
        from selva_workers.graphs.intelligence import generate_briefing

        mock_router = AsyncMock()
        with (
            patch(
                "selva_workers.inference.get_model_router",
                return_value=mock_router,
            ),
            patch(
                "selva_workers.inference.call_llm",
                new_callable=AsyncMock,
                return_value="Buenos dias. Hoy el tipo de cambio FIX es $17.05 MXN/USD.",
            ),
        ):
            result = generate_briefing(
                {
                    "messages": [],
                    "dof_results": [],
                    "economic_indicators": {},
                }
            )

        assert result["status"] == "briefing_generated"
        assert "17.05" in result["briefing_text"]

    def test_generate_briefing_empty_data(self) -> None:
        """With no data, the fallback still produces a valid briefing."""
        from selva_workers.graphs.intelligence import generate_briefing

        with patch(
            "selva_workers.inference.get_model_router",
            side_effect=RuntimeError("no providers"),
        ):
            result = generate_briefing(
                {
                    "messages": [],
                    "dof_results": [],
                    "economic_indicators": {},
                }
            )

        assert result["status"] == "briefing_generated"
        assert result["briefing_text"]
        assert "Sin novedades" in result["briefing_text"] or "Sin datos" in result["briefing_text"]


class TestNotifyTeamNode:
    """notify_team() delivers the briefing and stores artifacts."""

    def test_notify_team_stores_artifact(self) -> None:
        """notify_team stores the briefing as an artifact."""
        from selva_workers.graphs.intelligence import notify_team

        with patch(
            "selva_tools.storage.local.LocalFSStorage.save",
            new_callable=AsyncMock,
            return_value="/tmp/selva-artifacts/ab/cd/abcd1234",
        ):
            result = notify_team(
                {
                    "messages": [],
                    "briefing_text": "Briefing de prueba",
                    "dof_results": [{"title": "Entry"}],
                    "economic_indicators": {"exchange_rate": {"rate": "17.05"}},
                }
            )

        assert result["status"] == "completed"
        assert result["result"] is not None
        assert result["result"]["briefing"] == "Briefing de prueba"
        assert result["result"]["dof_count"] == 1
        assert len(result["result"]["delivery_channels"]) == 1
        assert result["result"]["delivery_channels"][0].startswith("artifact:")

    def test_notify_team_artifact_failure_graceful(self) -> None:
        """If artifact storage fails, notify_team still completes."""
        from selva_workers.graphs.intelligence import notify_team

        with patch(
            "selva_tools.storage.local.LocalFSStorage.save",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Storage error"),
        ):
            result = notify_team(
                {
                    "messages": [],
                    "briefing_text": "Briefing de prueba",
                    "dof_results": [],
                    "economic_indicators": {},
                }
            )

        assert result["status"] == "completed"
        assert result["result"]["delivery_channels"] == []


class TestIntelligenceRegistration:
    """Intelligence graph is registered in __main__.py and timeout config."""

    def test_intelligence_in_graph_builders(self) -> None:
        from selva_workers.__main__ import GRAPH_BUILDERS

        assert "intelligence" in GRAPH_BUILDERS

    def test_intelligence_timeout_configured(self) -> None:
        from selva_redis_pool.timeout import DEFAULT_TIMEOUTS

        assert "intelligence" in DEFAULT_TIMEOUTS
        assert DEFAULT_TIMEOUTS["intelligence"] == 300
