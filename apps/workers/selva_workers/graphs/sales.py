"""Sales pipeline graph -- qualify, quote, approve, send, order, bill, collect."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..event_emitter import instrumented_node
from .base import BaseGraphState
from .base import run_async as _run_async

logger = logging.getLogger(__name__)

LEAD_SCORE_THRESHOLD = 30  # Minimum lead score to proceed


# -- State --------------------------------------------------------------------


class SalesState(BaseGraphState, TypedDict, total=False):
    """Extended state for the sales pipeline workflow."""

    lead_id: str
    lead_data: dict[str, Any] | None
    cotizacion: dict[str, Any] | None
    pedido: dict[str, Any] | None
    billing_task_id: str | None
    customer_phone: str | None
    customer_email: str | None


# -- Node functions -----------------------------------------------------------


@instrumented_node
def qualify_lead(state: SalesState) -> SalesState:
    """Fetch and qualify lead from PhyndCRM.

    Retrieves lead data, checks scoring, and extracts contact info.
    Sets status to ``"unqualified"`` if the lead score is below threshold.
    """
    messages = state.get("messages", [])
    payload = state.get("workflow_variables", {})

    lead_id = state.get("lead_id", payload.get("lead_id", ""))
    lead_data: dict[str, Any] = {}
    customer_phone = state.get("customer_phone")
    customer_email = state.get("customer_email")

    # Try PhyndCRM adapter for real lead data.
    try:
        import os

        phyne_url = os.environ.get("PHYNE_CRM_URL")
        phyne_token = os.environ.get("PHYNE_CRM_TOKEN", "")
        if phyne_url and lead_id:
            from madfam_inference.adapters.crm import PhyndCRMAdapter

            adapter = PhyndCRMAdapter(base_url=phyne_url, token=phyne_token)
            profile = _run_async(adapter.get_unified_profile(lead_id))
            lead_data = {
                "lead_id": lead_id,
                "name": getattr(profile.contact, "name", ""),
                "email": getattr(profile.contact, "email", ""),
                "phone": getattr(profile.contact, "phone", ""),
                "rfc": getattr(profile.contact, "rfc", ""),
                "score": getattr(profile, "lead_score", 50),
                "pipeline_stage": getattr(profile, "pipeline_stage", "new"),
            }
            customer_phone = customer_phone or lead_data.get("phone")
            customer_email = customer_email or lead_data.get("email")
        else:
            raise RuntimeError("PHYNE_CRM_URL not set or lead_id empty")
    except Exception:
        logger.debug("PhyndCRM unavailable; using payload values for lead data")
        lead_data = {
            "lead_id": lead_id or payload.get("lead_id", "unknown"),
            "name": payload.get("customer_name", "Prospecto"),
            "email": payload.get("customer_email", ""),
            "phone": payload.get("customer_phone", ""),
            "rfc": payload.get("rfc", ""),
            "score": payload.get("lead_score", 50),
            "pipeline_stage": payload.get("pipeline_stage", "new"),
        }
        customer_phone = customer_phone or lead_data.get("phone")
        customer_email = customer_email or lead_data.get("email")

    score = lead_data.get("score", 50)
    if isinstance(score, str):
        try:
            score = int(score)
        except ValueError:
            score = 50

    if score < LEAD_SCORE_THRESHOLD:
        unqual_msg = AIMessage(
            content=(
                f"Lead {lead_id} has score {score} (below threshold "
                f"{LEAD_SCORE_THRESHOLD}). Marked as unqualified."
            ),
        )
        return {
            **state,
            "messages": [*messages, unqual_msg],
            "lead_id": lead_id,
            "lead_data": lead_data,
            "customer_phone": customer_phone,
            "customer_email": customer_email,
            "status": "unqualified",
        }

    qual_msg = AIMessage(
        content=(
            f"Lead {lead_id} qualified: name={lead_data.get('name')}, "
            f"score={score}, stage={lead_data.get('pipeline_stage')}."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "lead_data": lead_data,
        },
    )

    return {
        **state,
        "messages": [*messages, qual_msg],
        "lead_id": lead_id,
        "lead_data": lead_data,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "status": "qualified",
    }


@instrumented_node
def generate_cotizacion(state: SalesState) -> SalesState:
    """Generate a professional quotation using LLM based on lead context.

    Drafts a cotizacion in Mexican business format with line items,
    pricing, payment terms, and validity period. Falls back to a
    template when no LLM is available.
    """
    messages = state.get("messages", [])
    lead_data = state.get("lead_data", {})

    # Derive locale from state or workflow_variables.
    locale = state.get("locale", "")
    if not locale:
        wf_vars = state.get("workflow_variables", {})
        locale = wf_vars.get("locale", "es-MX") if isinstance(wf_vars, dict) else "es-MX"

    wf_vars = state.get("workflow_variables", {}) or {}
    line_items = wf_vars.get("line_items", [])
    payment_terms = wf_vars.get("payment_terms", "contado")
    validity_days = wf_vars.get("validity_days", 15)

    cotizacion: dict[str, Any] | None = None

    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()

        experience_ctx = ""
        try:
            from ..prompts import build_experience_context

            experience_ctx = _run_async(
                build_experience_context(
                    agent_id=state.get("agent_id", "unknown"),
                    agent_role="sales",
                    task_description=state.get("description", ""),
                )
            )
        except Exception:
            logger.debug("Failed to retrieve experience context", exc_info=True)

        skill_ctx = state.get("agent_system_prompt", "")
        parts = [p for p in [skill_ctx, experience_ctx] if p]

        if locale == "es-MX":
            base_prompt = (
                "Genere una cotizacion profesional en formato de negocios mexicano. "
                "Incluya: partidas con precios, subtotal, IVA (16%), total, "
                "condiciones de pago y vigencia. Use el registro formal (usted). "
                "Responda en JSON con las claves: items, subtotal, iva, total, "
                "payment_terms, validity_days, notes."
            )
        else:
            base_prompt = (
                "Generate a professional quotation in Mexican business format. "
                "Include: line items with prices, subtotal, IVA (16%), total, "
                "payment terms, and validity period. "
                "Respond in JSON with keys: items, subtotal, iva, total, "
                "payment_terms, validity_days, notes."
            )
        parts.append(base_prompt)
        system_prompt = "\n\n".join(parts)

        customer_name = lead_data.get("name", "Cliente") if lead_data else "Cliente"
        user_content = (
            f"Cotizacion para: {customer_name}\n"
            f"RFC: {lead_data.get('rfc', 'N/A') if lead_data else 'N/A'}\n"
            f"Partidas: {line_items or 'Determinar segun descripcion'}\n"
            f"Condiciones de pago: {payment_terms}\n"
            f"Vigencia: {validity_days} dias\n"
            f"Descripcion: {state.get('description', '')}"
        )

        import json as _json

        raw = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": user_content}],
                system_prompt=system_prompt,
                task_type="crm",
            )
        )
        try:
            cotizacion = _json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            cotizacion = {"raw_draft": raw}
    except Exception:
        logger.debug("LLM unavailable for cotizacion; using template")

    if cotizacion is None:
        # Fallback template cotizacion.
        subtotal = (
            sum(float(item.get("price", 0)) * float(item.get("quantity", 1)) for item in line_items)
            if line_items
            else 0.0
        )
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        cotizacion = {
            "items": line_items
            or [
                {"description": "Servicio profesional", "quantity": 1, "price": 0},
            ],
            "subtotal": subtotal,
            "iva": iva,
            "total": total,
            "payment_terms": payment_terms,
            "validity_days": validity_days,
            "notes": "Cotizacion generada automaticamente. Precios sujetos a confirmacion.",
        }

    cot_msg = AIMessage(
        content=(
            f"Cotizacion generated for "
            f"{lead_data.get('name', 'cliente') if lead_data else 'cliente'}: "
            f"total={cotizacion.get('total', 'N/A')}."
        ),
        additional_kwargs={
            "action_category": "crm_update",
            "cotizacion": cotizacion,
        },
    )

    return {
        **state,
        "messages": [*messages, cot_msg],
        "cotizacion": cotizacion,
        "status": "cotizacion_ready",
    }


@instrumented_node
def approval_gate(state: SalesState) -> SalesState:
    """Interrupt execution to require human approval for the cotizacion.

    The Tactician must review pricing, terms, and discounts before
    the cotizacion is sent to the customer.
    """
    cotizacion = state.get("cotizacion", {})
    lead_data = state.get("lead_data", {})

    approval_context = {
        "action": "send_cotizacion",
        "customer": lead_data.get("name", "unknown") if lead_data else "unknown",
        "cotizacion": cotizacion,
        "category": "crm_update",
    }

    decision = interrupt(approval_context)

    if decision.get("approved", False):
        approve_msg = AIMessage(
            content="Cotizacion approved for sending.",
            additional_kwargs={"action_category": "crm_update"},
        )
        return {
            **state,
            "messages": [*state.get("messages", []), approve_msg],
            "status": "approved",
        }

    feedback = decision.get("feedback", "Sin retroalimentacion")
    deny_msg = AIMessage(
        content=f"Cotizacion denied. Feedback: {feedback}",
        additional_kwargs={"action_category": "crm_update"},
    )
    return {
        **state,
        "messages": [*state.get("messages", []), deny_msg],
        "status": "denied",
    }


@instrumented_node
def send_cotizacion(state: SalesState) -> SalesState:
    """Send the approved cotizacion to the customer via WhatsApp or email.

    Tries WhatsApp Business template ``cotizacion_lista`` first, then
    falls back to email. Updates PhyndCRM activity log.
    """
    messages = state.get("messages", [])
    customer_phone = state.get("customer_phone")
    customer_email = state.get("customer_email")
    cotizacion = state.get("cotizacion", {})
    lead_data = state.get("lead_data", {})

    if state.get("status") == "denied":
        return {**state, "status": "cancelled"}

    notification_channel = "none"
    customer_name = lead_data.get("name", "Cliente") if lead_data else "Cliente"
    total = cotizacion.get("total", "0") if cotizacion else "0"

    # Try WhatsApp Business template first.
    if customer_phone:
        try:
            from selva_tools.builtins.whatsapp import WhatsAppTemplateTool

            wa_tool = WhatsAppTemplateTool()
            wa_result = _run_async(
                wa_tool.execute(
                    phone=customer_phone,
                    template_name="cotizacion_lista",
                    parameters=[
                        customer_name,
                        str(total),
                        f"{cotizacion.get('validity_days', 15) if cotizacion else 15} dias",
                    ],
                )
            )
            if wa_result.success:
                notification_channel = "whatsapp_template"
        except Exception:
            logger.debug("WhatsApp template send failed", exc_info=True)

    # Email fallback.
    if notification_channel == "none" and customer_email:
        try:
            import os

            if os.environ.get("SMTP_HOST"):
                notification_channel = "email"
        except Exception:
            logger.debug("Email send failed")

    if notification_channel == "none":
        notification_channel = "log_only"
        logger.info("Cotizacion ready but no notification channel available")

    # Log activity in PhyndCRM.
    try:
        import os

        phyne_url = os.environ.get("PHYNE_CRM_URL")
        phyne_token = os.environ.get("PHYNE_CRM_TOKEN", "")
        if phyne_url:
            from madfam_inference.adapters.crm import PhyndCRMAdapter

            adapter = PhyndCRMAdapter(base_url=phyne_url, token=phyne_token)
            _run_async(
                adapter.create_activity(
                    type="cotizacion",
                    title=f"Cotizacion enviada a {customer_name}",
                    description=f"Total: {total}, via {notification_channel}",
                    entity_type="contact",
                    entity_id=state.get("lead_id", ""),
                )
            )
    except Exception:
        logger.debug("PhyndCRM activity logging skipped")

    send_msg = AIMessage(
        content=(f"Cotizacion sent to {customer_name} via {notification_channel}. Total: {total}."),
        additional_kwargs={
            "action_category": "crm_update",
            "notification_channel": notification_channel,
        },
    )

    return {
        **state,
        "messages": [*messages, send_msg],
        "status": "cotizacion_sent",
    }


@instrumented_node
def convert_to_pedido(state: SalesState) -> SalesState:
    """Convert the accepted cotizacion to a pedido (order) in PhyndCRM.

    Creates or updates the opportunity / pipeline stage in the CRM.
    """
    messages = state.get("messages", [])
    lead_data = state.get("lead_data", {})
    cotizacion = state.get("cotizacion", {})

    pedido: dict[str, Any] = {
        "lead_id": state.get("lead_id", ""),
        "customer_name": lead_data.get("name", "") if lead_data else "",
        "rfc": lead_data.get("rfc", "") if lead_data else "",
        "items": cotizacion.get("items", []) if cotizacion else [],
        "total": cotizacion.get("total", 0) if cotizacion else 0,
        "payment_terms": cotizacion.get("payment_terms", "contado") if cotizacion else "contado",
    }

    # Try PhyndCRM to update pipeline.
    try:
        import os

        phyne_url = os.environ.get("PHYNE_CRM_URL")
        phyne_token = os.environ.get("PHYNE_CRM_TOKEN", "")
        if phyne_url:
            from madfam_inference.adapters.crm import PhyndCRMAdapter

            adapter = PhyndCRMAdapter(base_url=phyne_url, token=phyne_token)
            _run_async(
                adapter.create_activity(
                    type="pedido",
                    title=f"Pedido creado: {pedido['customer_name']}",
                    description=f"Total: {pedido['total']}",
                    entity_type="contact",
                    entity_id=state.get("lead_id", ""),
                )
            )
    except Exception:
        logger.debug("PhyndCRM pipeline update skipped")

    pedido_msg = AIMessage(
        content=(f"Pedido created for {pedido['customer_name']}: total={pedido['total']}."),
        additional_kwargs={
            "action_category": "crm_update",
            "pedido": pedido,
        },
    )

    return {
        **state,
        "messages": [*messages, pedido_msg],
        "pedido": pedido,
        "status": "pedido_created",
    }


@instrumented_node
def dispatch_billing(state: SalesState) -> SalesState:
    """Dispatch a billing graph to generate CFDI for the order.

    Creates a child task with ``graph_type="billing"`` and passes
    receptor RFC, conceptos from the pedido, and customer contact info.
    Reuses the billing graph end-to-end.
    """
    messages = state.get("messages", [])
    pedido = state.get("pedido", {})
    lead_data = state.get("lead_data", {})

    billing_task_id: str | None = None

    # Build conceptos from pedido items.
    items = pedido.get("items", []) if pedido else []
    conceptos = []
    for item in items:
        if isinstance(item, dict):
            conceptos.append(
                {
                    "descripcion": item.get("description", item.get("descripcion", "")),
                    "valor_unitario": item.get("price", item.get("valor_unitario", 0)),
                    "cantidad": item.get("quantity", item.get("cantidad", 1)),
                }
            )

    receptor_rfc = (lead_data.get("rfc", "") if lead_data else "") or (
        pedido.get("rfc", "") if pedido else ""
    )

    # Try dispatching via nexus-api.
    try:
        import os

        from ..auth import get_worker_auth_headers
        from ..http_retry import fire_and_forget_request

        nexus_url = os.environ.get("NEXUS_API_URL", "http://localhost:4300")
        import uuid

        child_task_id = str(uuid.uuid4())
        # Pull org_id off graph state so the dispatch posts under the
        # owning tenant's scope (not the platform default).
        _state_org_id = state.get("org_id")
        state_org_id: str | None = (
            _state_org_id if isinstance(_state_org_id, str) and _state_org_id else None
        )
        _run_async(
            fire_and_forget_request(
                "POST",
                f"{nexus_url}/api/v1/swarms/dispatch",
                json={
                    "description": (
                        f"Facturacion: pedido para "
                        f"{pedido.get('customer_name', 'N/A') if pedido else 'N/A'}"
                    ),
                    "graph_type": "billing",
                    "payload": {
                        "emisor_rfc": os.environ.get("MADFAM_EMISOR_RFC", ""),
                        "receptor_rfc": receptor_rfc,
                        "conceptos": conceptos,
                        "customer_phone": state.get("customer_phone"),
                        "customer_email": state.get("customer_email"),
                    },
                },
                headers=get_worker_auth_headers(org_id=state_org_id),
                timeout=5.0,
            )
        )
        billing_task_id = child_task_id
    except Exception:
        logger.debug("Failed to dispatch billing task; flagging for manual invoice")

    bill_msg = AIMessage(
        content=(
            f"Billing dispatched: task_id={billing_task_id or 'manual'}, "
            f"receptor_rfc={receptor_rfc}, {len(conceptos)} concepto(s)."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "billing_task_id": billing_task_id,
        },
    )

    return {
        **state,
        "messages": [*messages, bill_msg],
        "billing_task_id": billing_task_id,
        "status": "billing_dispatched",
    }


@instrumented_node
def track_cobranza(state: SalesState) -> SalesState:
    """Track payment collection status.

    Checks Dhanam for payment receipt. Sends follow-up reminders
    via WhatsApp if unpaid. Flags overdue payments for manual intervention.
    """
    messages = state.get("messages", [])
    pedido = state.get("pedido", {})
    customer_phone = state.get("customer_phone")

    payment_status = "pending"

    # Try Dhanam adapter for payment status.
    try:
        import os

        dhanam_url = os.environ.get("DHANAM_API_URL")
        dhanam_token = os.environ.get("DHANAM_API_TOKEN", "")
        if dhanam_url:
            from madfam_inference.adapters.billing import DhanamAdapter

            adapter = DhanamAdapter(base_url=dhanam_url, token=dhanam_token)
            task_id = state.get("task_id", "")
            txn = _run_async(adapter.get_transaction(task_id))
            if txn and txn.get("status") == "paid":
                payment_status = "paid"
            elif txn and txn.get("status") == "overdue":
                payment_status = "overdue"
        else:
            raise RuntimeError("DHANAM_API_URL not set")
    except Exception:
        logger.debug("Dhanam unavailable; payment status unknown")

    # Send reminder if unpaid and customer has phone.
    if payment_status == "pending" and customer_phone:
        try:
            from selva_tools.builtins.whatsapp import WhatsAppTemplateTool

            wa_tool = WhatsAppTemplateTool()
            customer_name = pedido.get("customer_name", "Cliente") if pedido else "Cliente"
            total = pedido.get("total", "0") if pedido else "0"
            _run_async(
                wa_tool.execute(
                    phone=customer_phone,
                    template_name="recordatorio_pago",
                    parameters=[customer_name, str(total)],
                )
            )
        except Exception:
            logger.debug("WhatsApp payment reminder failed")

    if payment_status == "paid":
        final_status = "completed"
    elif payment_status == "overdue":
        final_status = "overdue"
    else:
        final_status = "completed"  # Pipeline completes; cobranza tracked separately.

    track_msg = AIMessage(
        content=(
            f"Cobranza tracking: payment_status={payment_status}, "
            f"total={pedido.get('total', 'N/A') if pedido else 'N/A'}."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "payment_status": payment_status,
        },
    )

    return {
        **state,
        "messages": [*messages, track_msg],
        "status": final_status,
        "result": {
            "lead_id": state.get("lead_id", ""),
            "pedido": pedido,
            "billing_task_id": state.get("billing_task_id"),
            "payment_status": payment_status,
        },
    }


# -- Conditional edge routing -------------------------------------------------


def _route_after_qualify(state: SalesState) -> str:
    """Route to END if lead is unqualified, otherwise continue."""
    if state.get("status") == "unqualified":
        return END
    return "generate_cotizacion"


def _route_after_approval(state: SalesState) -> str:
    """Route to END if cotizacion was denied, otherwise continue."""
    if state.get("status") == "denied":
        return END
    return "send_cotizacion"


# -- Graph construction -------------------------------------------------------


def build_sales_graph() -> StateGraph:
    """Construct and compile the sales pipeline state graph.

    Flow::

        qualify_lead --(unqualified)--> END
                    \\--> generate_cotizacion
                          -> approval_gate (interrupt) --(denied)--> END
                                                       \\--> send_cotizacion
                                                              -> convert_to_pedido
                                                              -> dispatch_billing
                                                              -> track_cobranza
                                                              -> END
    """
    graph = StateGraph(SalesState)

    graph.add_node("qualify_lead", qualify_lead)
    graph.add_node("generate_cotizacion", generate_cotizacion)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("send_cotizacion", send_cotizacion)
    graph.add_node("convert_to_pedido", convert_to_pedido)
    graph.add_node("dispatch_billing", dispatch_billing)
    graph.add_node("track_cobranza", track_cobranza)

    graph.add_edge(START, "qualify_lead")
    graph.add_conditional_edges("qualify_lead", _route_after_qualify)
    graph.add_edge("generate_cotizacion", "approval_gate")
    graph.add_conditional_edges("approval_gate", _route_after_approval)
    graph.add_edge("send_cotizacion", "convert_to_pedido")
    graph.add_edge("convert_to_pedido", "dispatch_billing")
    graph.add_edge("dispatch_billing", "track_cobranza")
    graph.add_edge("track_cobranza", END)

    return graph
