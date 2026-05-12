"""CRM workflow graph -- fetch context, draft, approve, send."""

from __future__ import annotations

import logging
import re
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ..event_emitter import instrumented_node
from .base import BaseGraphState
from .base import run_async as _run_async

logger = logging.getLogger(__name__)


# -- T3.2 attribution helper --------------------------------------------------


def _emit_playbook_sent_safe(
    *,
    lead_id: str,
    playbook: Any,
    task_id: str,
    to_email: str,
    utm_campaign: str,
) -> None:
    """Fire `playbook.sent` to PostHog; never raise."""
    if not lead_id:
        return
    try:
        from ..attribution import domain_of, emit_playbook_sent

        playbook_name = ""
        if isinstance(playbook, dict):
            playbook_name = str(playbook.get("name") or "")
        emit_playbook_sent(
            lead_id,
            playbook_name=playbook_name or "crm_auto",
            task_id=task_id,
            channel="email",
            recipient_domain=domain_of(to_email),
            utm_campaign=utm_campaign,
        )
    except Exception:
        logger.debug("emit_playbook_sent failed (non-fatal)", exc_info=True)


# -- State --------------------------------------------------------------------


class CRMState(BaseGraphState, TypedDict, total=False):
    """Extended state for the CRM communication workflow."""

    draft_content: str | None
    recipient: str | None
    crm_action: str | None
    contact_email: str
    contact_name: str
    contact_id: str | None
    product_interest: str
    lead_score: int | None
    playbook: dict | None
    # T3.2 — attribution chain. `lead_id` is an opaque string threaded
    # from the inbound CRM webhook through to the email tool metadata so
    # PostHog events keep a single anonymous distinct_id across the funnel.
    lead_id: str
    utm_source: str
    utm_campaign: str


# -- Node functions -----------------------------------------------------------


@instrumented_node
def fetch_context(state: CRMState) -> CRMState:
    """Fetch CRM context for the target recipient and action.

    Calls the Phynd-CRM adapter when ``PHYND_CRM_URL`` is configured,
    falling back to mock data otherwise.
    """
    messages = state.get("messages", [])
    # `recipient: str | None` in CRMState — coerce explicit None to the
    # default so downstream str-typed adapter calls don't get a None.
    recipient: str = state.get("recipient") or "unknown@example.com"
    crm_action: str = state.get("crm_action") or "email"

    context_data: dict = {
        "recipient": recipient,
        "action": crm_action,
    }
    contact_id: str | None = None

    # Try Phynd-CRM adapter for real data.
    try:
        import os

        phynd_url = os.environ.get("PHYND_CRM_URL")
        phynd_token = os.environ.get("PHYND_CRM_TOKEN", "")
        if phynd_url:
            from madfam_inference.adapters.crm import PhyndCRMAdapter

            adapter = PhyndCRMAdapter(base_url=phynd_url, token=phynd_token)
            profile = _run_async(adapter.get_unified_profile(recipient))
            contact_id = profile.contact.id
            activities = _run_async(adapter.list_activities("contact", contact_id))
            context_data["contact_history"] = [
                {"date": a.due_date or "", "type": a.type, "subject": a.title} for a in activities
            ]
            context_data["account_status"] = profile.billing_status or "active"
            context_data["last_interaction_days_ago"] = 0
        else:
            raise RuntimeError("PHYND_CRM_URL not set")
    except Exception:
        logger.debug("Using mock CRM context (Phynd-CRM unavailable)")
        context_data["contact_history"] = [
            {"date": "2026-03-01", "type": "email", "subject": "Follow-up on proposal"},
            {"date": "2026-02-15", "type": "meeting", "subject": "Initial discovery call"},
        ]
        context_data["account_status"] = "active"
        context_data["last_interaction_days_ago"] = 5

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
        "contact_id": contact_id,
        "status": "fetching_context",
    }


@instrumented_node
def draft_communication(state: CRMState) -> CRMState:
    """Draft the outbound communication based on CRM context.

    Calls the inference router to generate a personalised draft.
    Falls back to a static template when no LLM is available.
    """
    messages = state.get("messages", [])
    recipient = state.get("recipient", "unknown")
    crm_action = state.get("crm_action", "email")

    # Gather CRM context from prior messages for the LLM prompt.
    crm_context = ""
    for msg in messages:
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if "crm_context" in kwargs:
            crm_context = str(kwargs["crm_context"])

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()

        # Retrieve experience context for prompt enrichment
        experience_ctx = ""
        try:
            from ..prompts import build_experience_context

            agent_id = state.get("agent_id", "unknown")
            description = state.get("description", "")
            experience_ctx = _run_async(
                build_experience_context(
                    agent_id=agent_id,
                    agent_role="crm",
                    task_description=description,
                )
            )
        except Exception:
            logger.debug("Failed to retrieve experience context", exc_info=True)

        locale = state.get("locale", "")
        if not locale:
            wf_vars = state.get("workflow_variables", {})
            locale = wf_vars.get("locale", "en") if isinstance(wf_vars, dict) else "en"

        skill_ctx = state.get("agent_system_prompt", "")
        if locale == "es-MX":
            base_prompt = (
                "Redacte una comunicacion profesional basada en el contexto de CRM proporcionado. "
                "Use el registro formal (usted). Redacte en espanol mexicano."
            )
        else:
            base_prompt = "Draft a professional communication based on the CRM context provided."
        parts = [p for p in [skill_ctx, experience_ctx, base_prompt] if p]
        system_prompt = "\n\n".join(parts)

        if locale == "es-MX":
            user_content = (
                f"Redacte un(a) {crm_action} para {recipient}.\nContexto CRM: {crm_context}"
            )
        else:
            user_content = f"Draft a {crm_action} for {recipient}.\nCRM context: {crm_context}"

        draft = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": user_content}],
                system_prompt=system_prompt,
                task_type="crm",
            )
        )
    except Exception:
        locale = state.get("locale", "")
        if not locale:
            wf_vars = state.get("workflow_variables", {})
            locale = wf_vars.get("locale", "en") if isinstance(wf_vars, dict) else "en"

        if locale == "es-MX":
            draft = (
                f"Asunto: Seguimiento a nuestra conversacion reciente\n\n"
                f"Estimado/a {recipient},\n\n"
                f"Agradezco su tiempo durante nuestra conversacion reciente. "
                f"Me permito dar seguimiento a los puntos clave que discutimos.\n\n"
                f"Quedo a sus ordenes para cualquier comentario.\n\n"
                f"Atentamente,\n"
                f"Agente CRM AutoSwarm"
            )
        else:
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


@instrumented_node
def approval_gate(state: CRMState) -> CRMState:
    """Interrupt execution to require human approval for outbound CRM actions.

    The Tactician must review the drafted communication and approve or
    deny it before it is sent.
    """
    draft = state.get("draft_content", "") or ""
    recipient: str = state.get("recipient") or "unknown"
    crm_action: str = state.get("crm_action") or "email"

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


@instrumented_node
def send(state: CRMState) -> CRMState:
    """Execute the approved outbound CRM action.

    Logs the drafted communication in Phynd-CRM as an activity when
    configured, otherwise uses a placeholder result.
    """
    messages = state.get("messages", [])
    recipient: str = state.get("recipient") or "unknown"
    crm_action: str = state.get("crm_action") or "email"

    # Skip sending if the action was denied at the gate.
    if state.get("status") == "denied":
        return {**state, "status": "cancelled"}

    # Permission check before sending outbound communication.
    from selva_permissions.types import PermissionLevel

    from .base import check_permission

    perm = check_permission(state, "email_send")
    if perm.level == PermissionLevel.DENY:
        deny_msg = AIMessage(content="Email send denied by permission engine.")
        return {
            **state,
            "messages": [*messages, deny_msg],
            "status": "blocked",
        }

    send_result: dict = {
        "action": crm_action,
        "recipient": recipient,
        "delivered": True,
        "message_id": f"msg-{state.get('task_id', 'unknown')}",
    }

    # Log the activity in Phynd-CRM if available.
    try:
        import os

        phynd_url = os.environ.get("PHYND_CRM_URL")
        phynd_token = os.environ.get("PHYND_CRM_TOKEN", "")
        contact_uuid = state.get("contact_id")
        if phynd_url and contact_uuid:
            from madfam_inference.adapters.crm import PhyndCRMAdapter

            adapter = PhyndCRMAdapter(base_url=phynd_url, token=phynd_token)
            draft = state.get("draft_content", "") or ""
            activity = _run_async(
                adapter.create_activity(
                    type=crm_action,
                    title=f"AutoSwarm: {crm_action} to {recipient}",
                    description=draft[:500],
                    entity_type="contact",
                    entity_id=contact_uuid,
                )
            )
            send_result["phynd_activity_id"] = activity.id
        elif phynd_url and not contact_uuid:
            logger.debug(
                "Phynd-CRM activity logging skipped: no contact_id resolved for %s "
                "(cold outreach or unresolved profile)",
                recipient,
            )
    except Exception:
        logger.debug("Phynd-CRM activity logging skipped (unavailable)")

    # Actually send the drafted email
    _email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    draft_content = state.get("draft_content", "")
    to_email = state.get("contact_email") or state.get("recipient", "")

    # Abort if LLM returned a placeholder (e.g. due to $0 credits)
    if draft_content and "[LLM unavailable" in draft_content:
        logger.warning("LLM returned placeholder — aborting email send")
        return {
            **state,
            "messages": [*messages, AIMessage(content="Draft failed — LLM unavailable.")],
            "status": "error",
            "result": {"error": "llm_unavailable"},
        }

    # T3.2 — thread lead_id through the email hop. Tool call metadata
    # carries the attribution chain so downstream (Stripe / Dhanam) can
    # read it back from the UTM cookie on the customer's browser.
    lead_id = state.get("lead_id", "") or ""
    utm_campaign = state.get("utm_campaign", "hot_lead_auto") or "hot_lead_auto"

    if to_email and _email_re.match(to_email) and draft_content:
        try:
            from selva_tools.builtins.marketing_tools import SendMarketingEmailTool

            tool = SendMarketingEmailTool()
            subject = f"Oportunidad para {state.get('contact_name', 'usted')}"
            # If we have a lead_id, append it to utm_campaign so the
            # tracking pixel on the recipient's browser carries it
            # through to Dhanam checkout. Dhanam reads `utm_campaign`
            # from the cookie at checkout time.
            effective_utm = f"{utm_campaign}__{lead_id}" if lead_id else utm_campaign
            email_result = _run_async(
                tool.execute(
                    to_email=to_email,
                    subject=subject,
                    body_html=draft_content,
                    utm_campaign=effective_utm,
                    lead_id=lead_id,
                    org_id=state.get("org_id"),
                )
            )
            send_result["email_id"] = (
                email_result.data.get("email_id") if email_result.success else None
            )
            send_result["email_sent"] = email_result.success
            send_result["lead_id"] = lead_id
            if email_result.success:
                masked = (
                    to_email[:3] + "***@" + to_email.split("@")[-1] if "@" in to_email else "***"
                )
                logger.info(
                    "Email sent to %s (id: %s, lead_id: %s)",
                    masked,
                    send_result.get("email_id"),
                    lead_id or "-",
                )
                # T3.2 — emit `playbook.sent` on successful send. Done
                # here (not in the tool) so the tool stays reusable by
                # non-attribution flows (e.g. direct agent outreach).
                _emit_playbook_sent_safe(
                    lead_id=lead_id,
                    playbook=state.get("playbook"),
                    task_id=state.get("task_id", ""),
                    to_email=to_email,
                    utm_campaign=effective_utm,
                )
            else:
                logger.warning("Email send failed: %s", email_result.error)
        except Exception as e:
            logger.warning("Email send failed (non-fatal): %s", e)
            send_result["email_sent"] = False

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


def _should_skip_approval(state: CRMState) -> str:
    """Skip HITL approval when playbook allows autonomous execution."""
    playbook = state.get("playbook")
    if playbook and isinstance(playbook, dict) and not playbook.get("require_approval", True):
        return "send"
    return "approval_gate"


def build_crm_graph() -> StateGraph:
    """Construct and compile the CRM workflow state graph.

    Flow::

        fetch_context -> draft_communication -+-> approval_gate (interrupt) -> send -> END
                                              |                                ^
                                              +-- (playbook autonomous) -------+
    """
    graph = StateGraph(CRMState)

    graph.add_node("fetch_context", fetch_context)
    graph.add_node("draft_communication", draft_communication)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("send", send)

    graph.set_entry_point("fetch_context")
    graph.add_edge("fetch_context", "draft_communication")
    graph.add_conditional_edges(
        "draft_communication",
        _should_skip_approval,
        {
            "send": "send",
            "approval_gate": "approval_gate",
        },
    )
    graph.add_edge("approval_gate", "send")
    graph.add_edge("send", END)

    return graph
