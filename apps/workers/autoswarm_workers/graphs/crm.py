"""CRM workflow graph -- fetch context, draft, approve, send."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .base import BaseGraphState

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class CRMState(BaseGraphState, TypedDict, total=False):
    """Extended state for the CRM communication workflow."""

    draft_content: str | None
    recipient: str | None
    crm_action: str | None


# -- Node functions -----------------------------------------------------------


def fetch_context(state: CRMState) -> CRMState:
    """Fetch CRM context for the target recipient and action.

    Retrieves contact history, recent interactions, and relevant
    business context to inform the draft.
    """
    messages = state.get("messages", [])
    recipient = state.get("recipient", "unknown@example.com")
    crm_action = state.get("crm_action", "email")

    context_data = {
        "recipient": recipient,
        "action": crm_action,
        "contact_history": [
            {"date": "2026-03-01", "type": "email", "subject": "Follow-up on proposal"},
            {"date": "2026-02-15", "type": "meeting", "subject": "Initial discovery call"},
        ],
        "account_status": "active",
        "last_interaction_days_ago": 5,
    }

    context_message = AIMessage(
        content=f"CRM context fetched for {recipient}: {len(context_data['contact_history'])} "
        f"prior interactions found.",
        additional_kwargs={"action_category": "api_call", "crm_context": context_data},
    )

    return {
        **state,
        "messages": [*messages, context_message],
        "recipient": recipient,
        "crm_action": crm_action,
        "status": "fetching_context",
    }


def draft_communication(state: CRMState) -> CRMState:
    """Draft the outbound communication based on CRM context.

    Uses the inference engine to generate an appropriate email, message,
    or CRM update based on the fetched context and task instructions.
    """
    messages = state.get("messages", [])
    recipient = state.get("recipient", "unknown")
    crm_action = state.get("crm_action", "email")

    # In production the inference engine generates the actual content.
    draft = (
        f"Subject: Follow-up on our recent discussion\n\n"
        f"Dear {recipient},\n\n"
        f"Thank you for your time during our recent conversation. "
        f"I wanted to follow up on the key points we discussed.\n\n"
        f"Looking forward to hearing from you.\n\n"
        f"Best regards,\n"
        f"AutoSwarm CRM Agent"
    )

    draft_message = AIMessage(
        content=f"Draft {crm_action} prepared for {recipient}.",
        additional_kwargs={
            "action_category": "email_send" if crm_action == "email" else "crm_update",
            "draft": draft,
        },
    )

    return {
        **state,
        "messages": [*messages, draft_message],
        "draft_content": draft,
        "status": "drafted",
    }


def approval_gate(state: CRMState) -> CRMState:
    """Interrupt execution to require human approval for outbound CRM actions.

    The Tactician must review the drafted communication and approve or
    deny it before it is sent.
    """
    draft = state.get("draft_content", "")
    recipient = state.get("recipient", "unknown")
    crm_action = state.get("crm_action", "email")

    approval_context = {
        "action": crm_action,
        "recipient": recipient,
        "draft_content": draft,
        "category": "email_send" if crm_action == "email" else "crm_update",
    }

    # Pause graph execution until the human responds.
    decision = interrupt(approval_context)

    if decision.get("approved", False):
        approve_message = AIMessage(
            content=f"CRM action approved: {crm_action} to {recipient}.",
            additional_kwargs={"action_category": "email_send"},
        )
        return {
            **state,
            "messages": [*state.get("messages", []), approve_message],
            "status": "approved",
        }

    # Denied.
    feedback = decision.get("feedback", "No feedback provided")
    deny_message = AIMessage(
        content=f"CRM action denied. Feedback: {feedback}",
        additional_kwargs={"action_category": "email_send"},
    )
    return {
        **state,
        "messages": [*state.get("messages", []), deny_message],
        "status": "denied",
    }


def send(state: CRMState) -> CRMState:
    """Execute the approved outbound CRM action.

    Only reached if the approval gate was passed.  In production this
    node dispatches the actual email or CRM API call.
    """
    messages = state.get("messages", [])
    recipient = state.get("recipient", "unknown")
    crm_action = state.get("crm_action", "email")

    # Skip sending if the action was denied at the gate.
    if state.get("status") == "denied":
        return {**state, "status": "cancelled"}

    send_result = {
        "action": crm_action,
        "recipient": recipient,
        "delivered": True,
        "message_id": f"msg-{state.get('task_id', 'unknown')}",
    }

    send_message = AIMessage(
        content=f"CRM {crm_action} sent to {recipient} successfully.",
        additional_kwargs={"action_category": "email_send", "send_result": send_result},
    )

    return {
        **state,
        "messages": [*messages, send_message],
        "status": "completed",
        "result": send_result,
    }


# -- Graph construction -------------------------------------------------------


def build_crm_graph() -> StateGraph:
    """Construct and compile the CRM workflow state graph.

    Flow::

        fetch_context -> draft_communication -> approval_gate (interrupt) -> send -> END
    """
    graph = StateGraph(CRMState)

    graph.add_node("fetch_context", fetch_context)
    graph.add_node("draft_communication", draft_communication)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("send", send)

    graph.set_entry_point("fetch_context")
    graph.add_edge("fetch_context", "draft_communication")
    graph.add_edge("draft_communication", "approval_gate")
    graph.add_edge("approval_gate", "send")
    graph.add_edge("send", END)

    return graph
