"""Tests for the CRM workflow graph."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage


class TestCRMGraphStructure:
    """CRM graph has correct nodes and edges."""

    def test_graph_has_expected_nodes(self) -> None:
        from selva_workers.graphs.crm import build_crm_graph

        graph = build_crm_graph()
        node_names = set(graph.nodes.keys())
        assert "fetch_context" in node_names
        assert "draft_communication" in node_names
        assert "approval_gate" in node_names
        assert "send" in node_names

    def test_graph_compiles(self) -> None:
        from selva_workers.graphs.crm import build_crm_graph

        graph = build_crm_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_crm_state_fields(self) -> None:
        from selva_workers.graphs.crm import CRMState

        annotations = CRMState.__annotations__
        assert "draft_content" in annotations
        assert "recipient" in annotations
        assert "crm_action" in annotations


class TestFetchContext:
    """fetch_context() gathers CRM data for the recipient."""

    def test_fallback_mock_context_without_phyne(self) -> None:
        from selva_workers.graphs.crm import fetch_context

        result = fetch_context(
            {
                "messages": [],
                "recipient": "user@example.com",
                "crm_action": "email",
            }
        )

        assert result["status"] == "fetching_context"
        assert result["recipient"] == "user@example.com"
        assert len(result["messages"]) == 1
        assert "CRM context fetched" in result["messages"][0].content

    def test_context_includes_mock_history(self) -> None:
        from selva_workers.graphs.crm import fetch_context

        result = fetch_context(
            {
                "messages": [],
                "recipient": "test@co.com",
            }
        )

        msg = result["messages"][0]
        crm_ctx = msg.additional_kwargs.get("crm_context", {})
        assert "contact_history" in crm_ctx
        assert len(crm_ctx["contact_history"]) == 2

    def test_defaults_when_no_recipient(self) -> None:
        from selva_workers.graphs.crm import fetch_context

        result = fetch_context({"messages": []})
        assert result["recipient"] == "unknown@example.com"
        assert result["crm_action"] == "email"

    def test_with_phyne_configured(self) -> None:
        """When PHYNE_CRM_URL is set but adapter fails, falls back to mock."""
        from selva_workers.graphs.crm import fetch_context

        with patch.dict("os.environ", {"PHYNE_CRM_URL": "http://fake-phynd:8080"}):
            result = fetch_context(
                {
                    "messages": [],
                    "recipient": "phynd-user@test.com",
                }
            )

        # Should still succeed via fallback
        assert result["status"] == "fetching_context"


class TestDraftCommunication:
    """draft_communication() produces a draft for approval."""

    def test_fallback_draft_without_llm(self) -> None:
        from selva_workers.graphs.crm import draft_communication

        result = draft_communication(
            {
                "messages": [
                    AIMessage(
                        content="CRM context fetched",
                        additional_kwargs={"crm_context": {"contact_history": []}},
                    )
                ],
                "recipient": "user@test.com",
                "crm_action": "email",
            }
        )

        assert result["status"] == "drafted"
        assert result["draft_content"] is not None
        assert "user@test.com" in result["draft_content"]

    def test_draft_message_added(self) -> None:
        from selva_workers.graphs.crm import draft_communication

        result = draft_communication(
            {
                "messages": [],
                "recipient": "bob@co.com",
                "crm_action": "email",
            }
        )

        assert len(result["messages"]) == 1
        assert "Draft" in result["messages"][0].content


class TestApprovalGate:
    """approval_gate() uses interrupt() for HITL review."""

    def test_approved_sets_status(self) -> None:
        from selva_workers.graphs.crm import approval_gate

        with patch(
            "selva_workers.graphs.crm.interrupt",
            return_value={"approved": True},
        ):
            result = approval_gate(
                {
                    "messages": [],
                    "draft_content": "Hello",
                    "recipient": "test@co.com",
                    "crm_action": "email",
                }
            )

        assert result["status"] == "approved"

    def test_denied_sets_status(self) -> None:
        from selva_workers.graphs.crm import approval_gate

        with patch(
            "selva_workers.graphs.crm.interrupt",
            return_value={"approved": False, "feedback": "Tone is wrong"},
        ):
            result = approval_gate(
                {
                    "messages": [],
                    "draft_content": "Hello",
                    "recipient": "test@co.com",
                    "crm_action": "email",
                }
            )

        assert result["status"] == "denied"
        assert "Tone is wrong" in result["messages"][-1].content


class TestSendNode:
    """send() executes the outbound CRM action."""

    def test_skips_if_denied(self) -> None:
        from selva_workers.graphs.crm import send

        result = send(
            {
                "messages": [],
                "recipient": "user@test.com",
                "crm_action": "email",
                "status": "denied",
            }
        )

        assert result["status"] == "cancelled"

    def test_permission_deny_blocks(self) -> None:
        from selva_workers.graphs.crm import send

        mock_result = MagicMock()
        with patch("selva_workers.graphs.base.check_permission") as mock_check:
            from selva_permissions.types import PermissionLevel

            mock_result.level = PermissionLevel.DENY
            mock_check.return_value = mock_result

            result = send(
                {
                    "messages": [],
                    "recipient": "user@test.com",
                    "crm_action": "email",
                    "status": "approved",
                }
            )

        assert result["status"] == "blocked"

    def test_send_succeeds_with_allow(self) -> None:
        from selva_workers.graphs.crm import send

        mock_result = MagicMock()
        with patch("selva_workers.graphs.base.check_permission") as mock_check:
            from selva_permissions.types import PermissionLevel

            mock_result.level = PermissionLevel.ALLOW
            mock_check.return_value = mock_result

            result = send(
                {
                    "messages": [],
                    "recipient": "user@test.com",
                    "crm_action": "email",
                    "status": "approved",
                    "task_id": "task-42",
                }
            )

        assert result["status"] == "completed"
        assert result["result"]["delivered"] is True

    def test_send_result_contains_message_id(self) -> None:
        from selva_workers.graphs.crm import send

        mock_result = MagicMock()
        with patch("selva_workers.graphs.base.check_permission") as mock_check:
            from selva_permissions.types import PermissionLevel

            mock_result.level = PermissionLevel.ALLOW
            mock_check.return_value = mock_result

            result = send(
                {
                    "messages": [],
                    "recipient": "alice@co.com",
                    "crm_action": "email",
                    "status": "approved",
                    "task_id": "t-99",
                }
            )

        assert result["result"]["message_id"] == "msg-t-99"
        assert result["result"]["recipient"] == "alice@co.com"


class TestCRMRegistration:
    """CRM graph builder is importable."""

    def test_crm_in_graph_builders(self) -> None:
        from selva_workers.graphs.crm import build_crm_graph

        graph = build_crm_graph()
        assert graph is not None

    def test_crm_timeout_configured(self) -> None:
        from selva_redis_pool.timeout import DEFAULT_TIMEOUTS

        assert "crm" in DEFAULT_TIMEOUTS
        assert DEFAULT_TIMEOUTS["crm"] == 120
