"""Tests for the sales pipeline workflow graph."""

from __future__ import annotations

from unittest.mock import patch


class TestSalesGraphStructure:
    """Sales graph has correct nodes, edges, and conditional routing."""

    def test_graph_has_expected_nodes(self) -> None:
        from selva_workers.graphs.sales import build_sales_graph

        graph = build_sales_graph()
        node_names = set(graph.nodes.keys())
        assert "qualify_lead" in node_names
        assert "generate_cotizacion" in node_names
        assert "approval_gate" in node_names
        assert "send_cotizacion" in node_names
        assert "convert_to_pedido" in node_names
        assert "dispatch_billing" in node_names
        assert "track_cobranza" in node_names

    def test_graph_compiles(self) -> None:
        from selva_workers.graphs.sales import build_sales_graph

        graph = build_sales_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_sales_state_fields(self) -> None:
        from selva_workers.graphs.sales import SalesState

        annotations = SalesState.__annotations__
        assert "lead_id" in annotations
        assert "lead_data" in annotations
        assert "cotizacion" in annotations
        assert "pedido" in annotations
        assert "billing_task_id" in annotations
        assert "customer_phone" in annotations
        assert "customer_email" in annotations

    def test_graph_has_seven_nodes(self) -> None:
        from selva_workers.graphs.sales import build_sales_graph

        graph = build_sales_graph()
        # 7 nodes + __start__ + __end__
        assert len(graph.nodes) == 7


class TestQualifyLead:
    """qualify_lead() fetches and scores leads."""

    def test_qualify_lead_from_payload(self) -> None:
        from selva_workers.graphs.sales import qualify_lead

        result = qualify_lead(
            {
                "messages": [],
                "lead_id": "lead-001",
                "workflow_variables": {
                    "lead_id": "lead-001",
                    "customer_name": "Empresa SA",
                    "customer_email": "contacto@empresa.mx",
                    "lead_score": 80,
                },
            }
        )

        assert result["status"] == "qualified"
        assert result["lead_id"] == "lead-001"
        assert result["lead_data"]["name"] == "Empresa SA"
        assert result["customer_email"] == "contacto@empresa.mx"
        assert len(result["messages"]) == 1
        assert "qualified" in result["messages"][0].content.lower()

    def test_qualify_lead_unqualified_low_score(self) -> None:
        from selva_workers.graphs.sales import qualify_lead

        result = qualify_lead(
            {
                "messages": [],
                "lead_id": "lead-low",
                "workflow_variables": {
                    "lead_score": 10,
                    "customer_name": "Bad Lead",
                },
            }
        )

        assert result["status"] == "unqualified"
        assert "below threshold" in result["messages"][0].content.lower()

    def test_qualify_lead_default_score_passes(self) -> None:
        """Without explicit score, default of 50 passes threshold."""
        from selva_workers.graphs.sales import qualify_lead

        result = qualify_lead(
            {
                "messages": [],
                "lead_id": "lead-default",
                "workflow_variables": {"customer_name": "Neutral"},
            }
        )

        assert result["status"] == "qualified"

    def test_qualify_lead_extracts_contact_info(self) -> None:
        from selva_workers.graphs.sales import qualify_lead

        result = qualify_lead(
            {
                "messages": [],
                "lead_id": "lead-contact",
                "workflow_variables": {
                    "customer_phone": "+5215512345678",
                    "customer_email": "test@co.mx",
                    "customer_name": "Contacto",
                },
            }
        )

        assert result["customer_phone"] == "+5215512345678"
        assert result["customer_email"] == "test@co.mx"


class TestGenerateCotizacion:
    """generate_cotizacion() drafts a quotation."""

    def test_generate_cotizacion_template_fallback(self) -> None:
        """Without LLM, generates a template cotizacion."""
        from selva_workers.graphs.sales import generate_cotizacion

        # Force the template fallback by blocking inference import.
        with patch.dict("sys.modules", {"selva_workers.inference": None}):
            result = generate_cotizacion(
                {
                    "messages": [],
                    "lead_data": {"name": "Cliente Test", "rfc": "XAXX010101000"},
                    "workflow_variables": {
                        "line_items": [
                            {"description": "Servicio A", "price": 1000, "quantity": 2},
                        ],
                        "payment_terms": "30 dias",
                        "validity_days": 15,
                    },
                }
            )

        assert result["status"] == "cotizacion_ready"
        assert result["cotizacion"] is not None
        cot = result["cotizacion"]
        assert cot["subtotal"] == 2000.0
        assert cot["iva"] == 320.0
        assert cot["total"] == 2320.0
        assert cot["payment_terms"] == "30 dias"
        assert "Cotizacion generated" in result["messages"][0].content

    def test_generate_cotizacion_empty_items(self) -> None:
        from selva_workers.graphs.sales import generate_cotizacion

        with patch.dict("sys.modules", {"selva_workers.inference": None}):
            result = generate_cotizacion(
                {
                    "messages": [],
                    "lead_data": {"name": "Empty"},
                    "workflow_variables": {},
                }
            )

        assert result["status"] == "cotizacion_ready"
        assert result["cotizacion"]["subtotal"] == 0.0

    def test_generate_cotizacion_preserves_messages(self) -> None:
        from langchain_core.messages import AIMessage

        from selva_workers.graphs.sales import generate_cotizacion

        existing = AIMessage(content="prior message")
        with patch.dict("sys.modules", {"selva_workers.inference": None}):
            result = generate_cotizacion(
                {
                    "messages": [existing],
                    "lead_data": {"name": "Test"},
                    "workflow_variables": {},
                }
            )

        assert len(result["messages"]) == 2
        assert result["messages"][0].content == "prior message"


class TestApprovalGate:
    """approval_gate() interrupts for HITL approval."""

    def test_approval_gate_is_callable(self) -> None:
        """Verify the function exists and has correct signature."""
        from selva_workers.graphs.sales import approval_gate

        assert callable(approval_gate)


class TestSendCotizacion:
    """send_cotizacion() sends via WhatsApp or email."""

    def test_send_cotizacion_log_only_without_contact(self) -> None:
        from selva_workers.graphs.sales import send_cotizacion

        result = send_cotizacion(
            {
                "messages": [],
                "cotizacion": {"total": 5000},
                "lead_data": {"name": "No Contact"},
                "status": "approved",
            }
        )

        assert result["status"] == "cotizacion_sent"
        assert "log_only" in result["messages"][0].content

    def test_send_cotizacion_skips_on_denied(self) -> None:
        from selva_workers.graphs.sales import send_cotizacion

        result = send_cotizacion(
            {
                "messages": [],
                "cotizacion": {"total": 5000},
                "lead_data": {"name": "Denied"},
                "status": "denied",
            }
        )

        assert result["status"] == "cancelled"

    def test_send_cotizacion_with_email(self) -> None:
        from selva_workers.graphs.sales import send_cotizacion

        with patch.dict("os.environ", {"SMTP_HOST": "smtp.test.com"}):
            result = send_cotizacion(
                {
                    "messages": [],
                    "cotizacion": {"total": 3000, "validity_days": 15},
                    "lead_data": {"name": "Email Client"},
                    "customer_email": "client@co.mx",
                    "status": "approved",
                }
            )

        assert result["status"] == "cotizacion_sent"
        assert "email" in result["messages"][0].content


class TestConvertToPedido:
    """convert_to_pedido() creates an order from the cotizacion."""

    def test_convert_to_pedido_creates_order(self) -> None:
        from selva_workers.graphs.sales import convert_to_pedido

        result = convert_to_pedido(
            {
                "messages": [],
                "lead_id": "lead-pedido",
                "lead_data": {"name": "Empresa SA", "rfc": "XAXX010101000"},
                "cotizacion": {
                    "items": [{"description": "Servicio", "price": 1000, "quantity": 1}],
                    "total": 1160,
                    "payment_terms": "contado",
                },
            }
        )

        assert result["status"] == "pedido_created"
        assert result["pedido"] is not None
        assert result["pedido"]["customer_name"] == "Empresa SA"
        assert result["pedido"]["total"] == 1160
        assert "Pedido created" in result["messages"][0].content

    def test_convert_to_pedido_without_crm(self) -> None:
        """Without PhyndCRM, still creates the pedido locally."""
        from selva_workers.graphs.sales import convert_to_pedido

        result = convert_to_pedido(
            {
                "messages": [],
                "lead_id": "lead-no-crm",
                "lead_data": {"name": "Local", "rfc": ""},
                "cotizacion": {"items": [], "total": 0, "payment_terms": "contado"},
            }
        )

        assert result["status"] == "pedido_created"
        assert result["pedido"]["customer_name"] == "Local"


class TestDispatchBilling:
    """dispatch_billing() dispatches a child billing task."""

    def test_dispatch_billing_graceful_without_nexus(self) -> None:
        """Without nexus-api, flags for manual invoice."""
        from selva_workers.graphs.sales import dispatch_billing

        result = dispatch_billing(
            {
                "messages": [],
                "pedido": {
                    "customer_name": "Test",
                    "items": [{"description": "Srv", "price": 500, "quantity": 1}],
                },
                "lead_data": {"rfc": "XAXX010101000"},
            }
        )

        assert result["status"] == "billing_dispatched"
        assert "Billing dispatched" in result["messages"][0].content

    def test_dispatch_billing_builds_conceptos(self) -> None:
        from selva_workers.graphs.sales import dispatch_billing

        result = dispatch_billing(
            {
                "messages": [],
                "pedido": {
                    "customer_name": "Multi",
                    "items": [
                        {"description": "Item A", "price": 100, "quantity": 2},
                        {"description": "Item B", "price": 200, "quantity": 1},
                    ],
                },
                "lead_data": {"rfc": "RFC_TEST"},
            }
        )

        assert "2 concepto(s)" in result["messages"][0].content


class TestTrackCobranza:
    """track_cobranza() tracks payment collection."""

    def test_track_cobranza_completes_without_dhanam(self) -> None:
        from selva_workers.graphs.sales import track_cobranza

        result = track_cobranza(
            {
                "messages": [],
                "pedido": {"customer_name": "Test", "total": 1000},
                "lead_id": "lead-cobranza",
                "billing_task_id": "billing-123",
                "task_id": "task-456",
            }
        )

        assert result["status"] == "completed"
        assert result["result"]["payment_status"] == "pending"
        assert result["result"]["lead_id"] == "lead-cobranza"

    def test_track_cobranza_result_structure(self) -> None:
        from selva_workers.graphs.sales import track_cobranza

        result = track_cobranza(
            {
                "messages": [],
                "pedido": {"customer_name": "Struct", "total": 500},
                "lead_id": "lead-struct",
                "billing_task_id": None,
                "task_id": "task-struct",
            }
        )

        assert "pedido" in result["result"]
        assert "billing_task_id" in result["result"]
        assert "payment_status" in result["result"]
        assert len(result["messages"]) == 1


class TestConditionalEdges:
    """Conditional edge routing functions."""

    def test_route_after_qualify_unqualified_goes_to_end(self) -> None:
        from selva_workers.graphs.sales import _route_after_qualify

        result = _route_after_qualify({"status": "unqualified"})
        assert result == "__end__"

    def test_route_after_qualify_ok_goes_to_cotizacion(self) -> None:
        from selva_workers.graphs.sales import _route_after_qualify

        result = _route_after_qualify({"status": "qualified"})
        assert result == "generate_cotizacion"

    def test_route_after_approval_denied_goes_to_end(self) -> None:
        from selva_workers.graphs.sales import _route_after_approval

        result = _route_after_approval({"status": "denied"})
        assert result == "__end__"

    def test_route_after_approval_ok_goes_to_send(self) -> None:
        from selva_workers.graphs.sales import _route_after_approval

        result = _route_after_approval({"status": "approved"})
        assert result == "send_cotizacion"


class TestSalesRegistration:
    """Sales graph is properly registered in the system."""

    def test_sales_in_graph_builders(self) -> None:
        from selva_workers.__main__ import GRAPH_BUILDERS

        assert "sales" in GRAPH_BUILDERS

    def test_sales_timeout_configured(self) -> None:
        from selva_redis_pool.timeout import DEFAULT_TIMEOUTS

        assert "sales" in DEFAULT_TIMEOUTS
        assert DEFAULT_TIMEOUTS["sales"] == 300

    def test_sales_builder_returns_graph(self) -> None:
        from selva_workers.graphs.sales import build_sales_graph

        graph = build_sales_graph()
        assert graph is not None
        assert hasattr(graph, "nodes")
