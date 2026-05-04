"""Tests for the billing workflow graph (CFDI 4.0 via Karafiel)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestBillingGraphStructure:
    """Billing graph has correct nodes, edges, and conditional routing."""

    def test_graph_has_expected_nodes(self) -> None:
        from selva_workers.graphs.billing import build_billing_graph

        graph = build_billing_graph()
        node_names = set(graph.nodes.keys())
        assert "fetch_context" in node_names
        assert "validate_rfcs" in node_names
        assert "check_blacklist" in node_names
        assert "generate_cfdi" in node_names
        assert "stamp_cfdi" in node_names
        assert "notify_customer" in node_names

    def test_graph_compiles(self) -> None:
        from selva_workers.graphs.billing import build_billing_graph

        graph = build_billing_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_billing_state_fields(self) -> None:
        from selva_workers.graphs.billing import BillingState

        annotations = BillingState.__annotations__
        assert "emisor_rfc" in annotations
        assert "receptor_rfc" in annotations
        assert "conceptos" in annotations
        assert "cfdi_xml" in annotations
        assert "cfdi_uuid" in annotations
        assert "stamp_result" in annotations
        assert "customer_phone" in annotations
        assert "customer_email" in annotations


class TestFetchContext:
    """fetch_context() gathers billing data from adapters or state."""

    def test_fetch_context_populates_state(self) -> None:
        from selva_workers.graphs.billing import fetch_context

        result = fetch_context(
            {
                "messages": [],
                "emisor_rfc": "XAXX010101000",
                "receptor_rfc": "XEXX010101000",
                "conceptos": [{"descripcion": "Servicio", "importe": 1000}],
                "customer_email": "test@example.com",
            }
        )

        assert result["status"] == "fetching_context"
        assert result["emisor_rfc"] == "XAXX010101000"
        assert result["receptor_rfc"] == "XEXX010101000"
        assert len(result["conceptos"]) == 1
        assert result["customer_email"] == "test@example.com"
        assert len(result["messages"]) == 1
        assert "Billing context fetched" in result["messages"][0].content

    def test_fetch_context_reads_from_workflow_variables(self) -> None:
        from selva_workers.graphs.billing import fetch_context

        result = fetch_context(
            {
                "messages": [],
                "workflow_variables": {
                    "emisor_rfc": "FROM_VARS",
                    "receptor_rfc": "FROM_VARS_R",
                    "conceptos": [{"desc": "item"}],
                },
            }
        )

        assert result["emisor_rfc"] == "FROM_VARS"
        assert result["receptor_rfc"] == "FROM_VARS_R"
        assert len(result["conceptos"]) == 1

    def test_fetch_context_without_adapters(self) -> None:
        """Without DHANAM or PHYNE env vars, falls back to state values."""
        from selva_workers.graphs.billing import fetch_context

        result = fetch_context(
            {
                "messages": [],
                "emisor_rfc": "AAA010101AAA",
                "receptor_rfc": "BBB020202BBB",
                "conceptos": [],
            }
        )

        assert result["status"] == "fetching_context"
        assert result["emisor_rfc"] == "AAA010101AAA"


class TestValidateRfcs:
    """validate_rfcs() blocks on invalid or missing RFCs."""

    def test_validate_rfcs_blocks_on_empty_emisor(self) -> None:
        from selva_workers.graphs.billing import validate_rfcs

        result = validate_rfcs(
            {
                "messages": [],
                "emisor_rfc": "",
                "receptor_rfc": "XEXX010101000",
            }
        )

        assert result["status"] == "error"
        assert "Missing" in result["result"]["error"]

    def test_validate_rfcs_blocks_on_empty_receptor(self) -> None:
        from selva_workers.graphs.billing import validate_rfcs

        result = validate_rfcs(
            {
                "messages": [],
                "emisor_rfc": "XAXX010101000",
                "receptor_rfc": "",
            }
        )

        assert result["status"] == "error"

    def test_validate_rfcs_passes_without_karafiel(self) -> None:
        """Without KARAFIEL_API_URL, validation is skipped (passes)."""
        from selva_workers.graphs.billing import validate_rfcs

        result = validate_rfcs(
            {
                "messages": [],
                "emisor_rfc": "XAXX010101000",
                "receptor_rfc": "XEXX010101000",
            }
        )

        assert result["status"] == "rfcs_validated"
        assert len(result["messages"]) == 1
        assert "validated" in result["messages"][0].content.lower()

    def test_validate_rfcs_blocks_on_invalid_emisor_with_karafiel(self) -> None:
        import sys

        from selva_workers.graphs.billing import validate_rfcs

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.validate_rfc.return_value = False

        mock_module = MagicMock()
        mock_module.KarafielAdapter.return_value = mock_adapter_instance

        with (
            patch.dict("os.environ", {"KARAFIEL_API_URL": "http://fake-karafiel:8080"}),
            patch.dict(sys.modules, {"madfam_inference.adapters.karafiel": mock_module}),
            patch("selva_workers.graphs.billing._run_async", side_effect=lambda x: x),
        ):
            result = validate_rfcs(
                {
                    "messages": [],
                    "emisor_rfc": "INVALID",
                    "receptor_rfc": "XEXX010101000",
                }
            )

        assert result["status"] == "error"
        assert "Invalid emisor RFC" in result["result"]["error"]


class TestCheckBlacklist:
    """check_blacklist() blocks listed RFCs."""

    def test_blacklist_passes_without_karafiel(self) -> None:
        from selva_workers.graphs.billing import check_blacklist

        result = check_blacklist(
            {
                "messages": [],
                "receptor_rfc": "XEXX010101000",
            }
        )

        assert result["status"] == "blacklist_clear"
        assert "not on the 69-B blacklist" in result["messages"][0].content

    def test_blacklist_blocks_listed_rfc(self) -> None:
        import sys

        from selva_workers.graphs.billing import check_blacklist

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.check_blacklist.return_value = True

        mock_module = MagicMock()
        mock_module.KarafielAdapter.return_value = mock_adapter_instance

        with (
            patch.dict("os.environ", {"KARAFIEL_API_URL": "http://fake-karafiel:8080"}),
            patch.dict(sys.modules, {"madfam_inference.adapters.karafiel": mock_module}),
            patch("selva_workers.graphs.billing._run_async", side_effect=lambda x: x),
        ):
            result = check_blacklist(
                {
                    "messages": [],
                    "receptor_rfc": "BLACKLISTED_RFC",
                }
            )

        assert result["status"] == "blocked"
        assert "69-B" in result["messages"][0].content

    def test_blacklist_clear_continues(self) -> None:
        import sys

        from selva_workers.graphs.billing import check_blacklist

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.check_blacklist.return_value = False

        mock_module = MagicMock()
        mock_module.KarafielAdapter.return_value = mock_adapter_instance

        with (
            patch.dict("os.environ", {"KARAFIEL_API_URL": "http://fake-karafiel:8080"}),
            patch.dict(sys.modules, {"madfam_inference.adapters.karafiel": mock_module}),
            patch("selva_workers.graphs.billing._run_async", side_effect=lambda x: x),
        ):
            result = check_blacklist(
                {
                    "messages": [],
                    "receptor_rfc": "CLEAN_RFC",
                }
            )

        assert result["status"] == "blacklist_clear"


class TestGenerateCfdi:
    """generate_cfdi() produces CFDI XML."""

    def test_generate_cfdi_creates_xml_placeholder(self) -> None:
        """Without Karafiel, generates a placeholder XML."""
        from selva_workers.graphs.billing import generate_cfdi

        result = generate_cfdi(
            {
                "messages": [],
                "emisor_rfc": "XAXX010101000",
                "receptor_rfc": "XEXX010101000",
                "conceptos": [{"descripcion": "Test"}],
                "task_id": "task-42",
            }
        )

        assert result["status"] == "cfdi_generated"
        assert result["cfdi_xml"] is not None
        assert "4.0" in result["cfdi_xml"]
        assert result["cfdi_uuid"] == "placeholder-task-42"
        assert "CFDI generated" in result["messages"][0].content

    def test_generate_cfdi_with_karafiel(self) -> None:
        import sys

        from selva_workers.graphs.billing import generate_cfdi

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.generate_cfdi.return_value = {
            "xml": "<cfdi>real-xml</cfdi>",
            "uuid": "real-uuid-1234",
        }

        mock_module = MagicMock()
        mock_module.KarafielAdapter.return_value = mock_adapter_instance

        with (
            patch.dict("os.environ", {"KARAFIEL_API_URL": "http://fake-karafiel:8080"}),
            patch.dict(sys.modules, {"madfam_inference.adapters.karafiel": mock_module}),
            patch("selva_workers.graphs.billing._run_async", side_effect=lambda x: x),
        ):
            result = generate_cfdi(
                {
                    "messages": [],
                    "emisor_rfc": "XAXX010101000",
                    "receptor_rfc": "XEXX010101000",
                    "conceptos": [{"descripcion": "Service"}],
                }
            )

        assert result["cfdi_xml"] == "<cfdi>real-xml</cfdi>"
        assert result["cfdi_uuid"] == "real-uuid-1234"


class TestStampCfdi:
    """stamp_cfdi() stamps the CFDI XML via PAC."""

    def test_stamp_cfdi_returns_folio_placeholder(self) -> None:
        """Without Karafiel, returns a placeholder stamp result."""
        from selva_workers.graphs.billing import stamp_cfdi

        result = stamp_cfdi(
            {
                "messages": [],
                "cfdi_xml": "<cfdi>test</cfdi>",
                "cfdi_uuid": "test-uuid",
            }
        )

        assert result["status"] == "stamped"
        assert result["stamp_result"] is not None
        assert result["stamp_result"]["folio_fiscal"] == "test-uuid"
        assert "stamped" in result["messages"][0].content.lower()

    def test_stamp_cfdi_fails_without_xml(self) -> None:
        from selva_workers.graphs.billing import stamp_cfdi

        result = stamp_cfdi(
            {
                "messages": [],
                "cfdi_xml": None,
            }
        )

        assert result["status"] == "error"
        assert "No cfdi_xml" in result["result"]["error"]

    def test_stamp_cfdi_fails_with_empty_xml(self) -> None:
        from selva_workers.graphs.billing import stamp_cfdi

        result = stamp_cfdi(
            {
                "messages": [],
                "cfdi_xml": "",
            }
        )

        assert result["status"] == "error"

    def test_stamp_cfdi_with_karafiel(self) -> None:
        import sys

        from selva_workers.graphs.billing import stamp_cfdi

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.stamp_cfdi.return_value = {
            "folio_fiscal": "ABC-123-DEF",
            "fecha_timbrado": "2026-04-14T12:00:00",
        }

        mock_module = MagicMock()
        mock_module.KarafielAdapter.return_value = mock_adapter_instance

        with (
            patch.dict("os.environ", {"KARAFIEL_API_URL": "http://fake-karafiel:8080"}),
            patch.dict(sys.modules, {"madfam_inference.adapters.karafiel": mock_module}),
            patch("selva_workers.graphs.billing._run_async", side_effect=lambda x: x),
        ):
            result = stamp_cfdi(
                {
                    "messages": [],
                    "cfdi_xml": "<cfdi>real</cfdi>",
                    "cfdi_uuid": "uuid-1",
                }
            )

        assert result["status"] == "stamped"
        assert result["stamp_result"]["folio_fiscal"] == "ABC-123-DEF"


class TestNotifyCustomer:
    """notify_customer() sends CFDI notification."""

    def test_notify_customer_sends_via_log_only(self) -> None:
        """Without contact info, defaults to log_only."""
        from selva_workers.graphs.billing import notify_customer

        result = notify_customer(
            {
                "messages": [],
                "cfdi_uuid": "uuid-test",
                "receptor_rfc": "XEXX010101000",
                "stamp_result": {"folio_fiscal": "F1"},
            }
        )

        assert result["status"] == "completed"
        assert result["result"]["notification_channel"] == "log_only"
        assert result["result"]["cfdi_uuid"] == "uuid-test"

    def test_notify_customer_with_email(self) -> None:
        """With customer_email and SMTP_HOST set, uses email channel."""
        from selva_workers.graphs.billing import notify_customer

        with patch.dict("os.environ", {"SMTP_HOST": "smtp.test.com"}):
            result = notify_customer(
                {
                    "messages": [],
                    "cfdi_uuid": "uuid-email",
                    "receptor_rfc": "RFC123",
                    "customer_email": "client@co.mx",
                    "stamp_result": {"folio_fiscal": "F2"},
                }
            )

        assert result["status"] == "completed"
        assert result["result"]["notification_channel"] == "email"

    def test_notify_customer_with_phone_fallback_to_email(self) -> None:
        """Phone notification fails, falls back to email."""
        from selva_workers.graphs.billing import notify_customer

        with patch.dict("os.environ", {"SMTP_HOST": "smtp.test.com"}):
            result = notify_customer(
                {
                    "messages": [],
                    "cfdi_uuid": "uuid-fallback",
                    "receptor_rfc": "RFC456",
                    "customer_phone": "+5215512345678",
                    "customer_email": "fallback@co.mx",
                    "stamp_result": {"folio_fiscal": "F3"},
                }
            )

        # WhatsApp not configured, falls back to email
        assert result["status"] == "completed"
        assert result["result"]["notification_channel"] == "email"

    def test_notify_customer_result_structure(self) -> None:
        from selva_workers.graphs.billing import notify_customer

        result = notify_customer(
            {
                "messages": [],
                "cfdi_uuid": "uuid-struct",
                "receptor_rfc": "RFC_STRUCT",
                "stamp_result": {"folio_fiscal": "FS"},
            }
        )

        assert "cfdi_uuid" in result["result"]
        assert "stamp_result" in result["result"]
        assert "notification_channel" in result["result"]
        assert len(result["messages"]) == 1


class TestConditionalEdges:
    """Conditional edge routing functions."""

    def test_route_after_validate_error_goes_to_end(self) -> None:
        from selva_workers.graphs.billing import _route_after_validate

        result = _route_after_validate({"status": "error"})
        assert result == "__end__"

    def test_route_after_validate_ok_goes_to_blacklist(self) -> None:
        from selva_workers.graphs.billing import _route_after_validate

        result = _route_after_validate({"status": "rfcs_validated"})
        assert result == "check_blacklist"

    def test_route_after_blacklist_blocked_goes_to_end(self) -> None:
        from selva_workers.graphs.billing import _route_after_blacklist

        result = _route_after_blacklist({"status": "blocked"})
        assert result == "__end__"

    def test_route_after_blacklist_clear_goes_to_generate(self) -> None:
        from selva_workers.graphs.billing import _route_after_blacklist

        result = _route_after_blacklist({"status": "blacklist_clear"})
        assert result == "generate_cfdi"


class TestBillingRegistration:
    """Billing graph is properly registered in the system."""

    def test_billing_in_graph_builders(self) -> None:
        from selva_workers.__main__ import GRAPH_BUILDERS

        assert "billing" in GRAPH_BUILDERS

    def test_billing_timeout_configured(self) -> None:
        from selva_redis_pool.timeout import DEFAULT_TIMEOUTS

        assert "billing" in DEFAULT_TIMEOUTS
        assert DEFAULT_TIMEOUTS["billing"] == 300

    def test_billing_builder_returns_graph(self) -> None:
        from selva_workers.graphs.billing import build_billing_graph

        graph = build_billing_graph()
        assert graph is not None
        assert hasattr(graph, "nodes")
