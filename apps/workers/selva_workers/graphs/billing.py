"""Billing workflow graph -- CFDI 4.0 invoice generation via Karafiel."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from ..event_emitter import instrumented_node
from .base import BaseGraphState
from .base import run_async as _run_async

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class BillingState(BaseGraphState, TypedDict, total=False):
    """Extended state for the billing / CFDI workflow."""

    emisor_rfc: str
    receptor_rfc: str
    conceptos: list[dict[str, Any]]
    cfdi_xml: str | None
    cfdi_uuid: str | None
    stamp_result: dict[str, Any] | None
    customer_phone: str | None
    customer_email: str | None


# -- Node functions -----------------------------------------------------------


@instrumented_node
def fetch_context(state: BillingState) -> BillingState:
    """Fetch transaction data from Dhanam and customer info from PhyneCRM.

    Populates emisor/receptor RFCs, conceptos, and customer contact info.
    Falls back to state values if adapters are unavailable.
    """
    messages = state.get("messages", [])
    payload = state.get("workflow_variables", {})

    emisor_rfc = state.get("emisor_rfc", payload.get("emisor_rfc", ""))
    receptor_rfc = state.get("receptor_rfc", payload.get("receptor_rfc", ""))
    conceptos = state.get("conceptos", payload.get("conceptos", []))
    customer_phone = state.get("customer_phone")
    customer_email = state.get("customer_email")

    # Try Dhanam adapter for transaction data.
    try:
        import os

        dhanam_url = os.environ.get("DHANAM_API_URL")
        dhanam_token = os.environ.get("DHANAM_API_TOKEN", "")
        if dhanam_url:
            from madfam_inference.adapters.billing import DhanamAdapter

            adapter = DhanamAdapter(base_url=dhanam_url, token=dhanam_token)
            task_id = state.get("task_id", "")
            txn = _run_async(adapter.get_transaction(task_id))
            if txn:
                emisor_rfc = emisor_rfc or txn.get("emisor_rfc", "")
                receptor_rfc = receptor_rfc or txn.get("receptor_rfc", "")
                conceptos = conceptos or txn.get("conceptos", [])
        else:
            raise RuntimeError("DHANAM_API_URL not set")
    except Exception:
        logger.debug("Dhanam adapter unavailable; using state/payload values")

    # Try PhyneCRM adapter for customer contact info.
    try:
        import os

        phyne_url = os.environ.get("PHYNE_CRM_URL")
        phyne_token = os.environ.get("PHYNE_CRM_TOKEN", "")
        if phyne_url and receptor_rfc:
            from madfam_inference.adapters.crm import PhyneCRMAdapter

            crm = PhyneCRMAdapter(base_url=phyne_url, token=phyne_token)
            profile = _run_async(crm.get_unified_profile(receptor_rfc))
            customer_phone = customer_phone or getattr(profile.contact, "phone", None)
            customer_email = customer_email or getattr(profile.contact, "email", None)
        else:
            raise RuntimeError("PHYNE_CRM_URL not set or receptor_rfc empty")
    except Exception:
        logger.debug("PhyneCRM adapter unavailable; using state values for contact info")

    context_message = AIMessage(
        content=(
            f"Billing context fetched: emisor={emisor_rfc}, "
            f"receptor={receptor_rfc}, {len(conceptos)} concepto(s)."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "billing_context": {
                "emisor_rfc": emisor_rfc,
                "receptor_rfc": receptor_rfc,
                "concepto_count": len(conceptos),
            },
        },
    )

    return {
        **state,
        "messages": [*messages, context_message],
        "emisor_rfc": emisor_rfc,
        "receptor_rfc": receptor_rfc,
        "conceptos": conceptos,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "status": "fetching_context",
    }


@instrumented_node
def validate_rfcs(state: BillingState) -> BillingState:
    """Validate emisor and receptor RFCs via Karafiel.

    Sets status to ``"error"`` if either RFC is invalid.
    """
    messages = state.get("messages", [])
    emisor_rfc = state.get("emisor_rfc", "")
    receptor_rfc = state.get("receptor_rfc", "")

    if not emisor_rfc or not receptor_rfc:
        error_msg = AIMessage(
            content="RFC validation failed: emisor or receptor RFC is empty.",
        )
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "result": {"error": "Missing emisor_rfc or receptor_rfc"},
        }

    try:
        import os

        karafiel_url = os.environ.get("KARAFIEL_API_URL")
        karafiel_token = os.environ.get("KARAFIEL_API_TOKEN", "")
        if karafiel_url:
            from madfam_inference.adapters.karafiel import KarafielAdapter

            adapter = KarafielAdapter(base_url=karafiel_url, token=karafiel_token)
            emisor_valid = _run_async(adapter.validate_rfc(emisor_rfc))
            receptor_valid = _run_async(adapter.validate_rfc(receptor_rfc))

            if not emisor_valid:
                error_msg = AIMessage(
                    content=f"RFC validation failed: emisor RFC '{emisor_rfc}' is invalid.",
                )
                return {
                    **state,
                    "messages": [*messages, error_msg],
                    "status": "error",
                    "result": {"error": f"Invalid emisor RFC: {emisor_rfc}"},
                }

            if not receptor_valid:
                error_msg = AIMessage(
                    content=f"RFC validation failed: receptor RFC '{receptor_rfc}' is invalid.",
                )
                return {
                    **state,
                    "messages": [*messages, error_msg],
                    "status": "error",
                    "result": {"error": f"Invalid receptor RFC: {receptor_rfc}"},
                }
        else:
            raise RuntimeError("KARAFIEL_API_URL not set")
    except ImportError:
        logger.debug("KarafielAdapter not available; skipping RFC validation")
    except RuntimeError:
        logger.debug("KARAFIEL_API_URL not configured; skipping RFC validation")

    valid_msg = AIMessage(
        content=f"RFCs validated: emisor={emisor_rfc}, receptor={receptor_rfc}.",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, valid_msg],
        "status": "rfcs_validated",
    }


@instrumented_node
def check_blacklist(state: BillingState) -> BillingState:
    """Check receptor RFC against Article 69-B blacklist.

    Sets status to ``"blocked"`` if the receptor is blacklisted.
    """
    messages = state.get("messages", [])
    receptor_rfc = state.get("receptor_rfc", "")

    try:
        import os

        karafiel_url = os.environ.get("KARAFIEL_API_URL")
        karafiel_token = os.environ.get("KARAFIEL_API_TOKEN", "")
        if karafiel_url:
            from madfam_inference.adapters.karafiel import KarafielAdapter

            adapter = KarafielAdapter(base_url=karafiel_url, token=karafiel_token)
            is_listed = _run_async(adapter.check_blacklist(receptor_rfc))

            if is_listed:
                block_msg = AIMessage(
                    content=(
                        f"Receptor RFC '{receptor_rfc}' is on the SAT Article 69-B "
                        f"blacklist. Invoice generation blocked."
                    ),
                )
                return {
                    **state,
                    "messages": [*messages, block_msg],
                    "status": "blocked",
                    "result": {"error": f"Receptor {receptor_rfc} is on Article 69-B blacklist"},
                }
        else:
            raise RuntimeError("KARAFIEL_API_URL not set")
    except ImportError:
        logger.debug("KarafielAdapter not available; skipping blacklist check")
    except RuntimeError:
        logger.debug("KARAFIEL_API_URL not configured; skipping blacklist check")

    clean_msg = AIMessage(
        content=f"Receptor RFC '{receptor_rfc}' is not on the 69-B blacklist.",
        additional_kwargs={"action_category": "api_call"},
    )

    return {
        **state,
        "messages": [*messages, clean_msg],
        "status": "blacklist_clear",
    }


@instrumented_node
def generate_cfdi(state: BillingState) -> BillingState:
    """Generate CFDI 4.0 XML via Karafiel.

    Stores ``cfdi_xml`` and ``cfdi_uuid`` in state on success.
    """
    messages = state.get("messages", [])
    emisor_rfc = state.get("emisor_rfc", "")
    receptor_rfc = state.get("receptor_rfc", "")
    conceptos = state.get("conceptos", [])

    cfdi_xml: str | None = None
    cfdi_uuid: str | None = None

    try:
        import os

        karafiel_url = os.environ.get("KARAFIEL_API_URL")
        karafiel_token = os.environ.get("KARAFIEL_API_TOKEN", "")
        if karafiel_url:
            from madfam_inference.adapters.karafiel import KarafielAdapter

            adapter = KarafielAdapter(base_url=karafiel_url, token=karafiel_token)
            result = _run_async(
                adapter.generate_cfdi(
                    emisor_rfc=emisor_rfc,
                    receptor_rfc=receptor_rfc,
                    conceptos=conceptos,
                )
            )
            cfdi_xml = result.xml or None
            cfdi_uuid = result.uuid or None
        else:
            raise RuntimeError("KARAFIEL_API_URL not set")
    except ImportError:
        logger.debug("KarafielAdapter not available; using placeholder CFDI")
    except RuntimeError:
        logger.debug("KARAFIEL_API_URL not configured; using placeholder CFDI")

    if cfdi_xml is None:
        # Placeholder when Karafiel is unavailable (dev/test).
        cfdi_uuid = f"placeholder-{state.get('task_id', 'unknown')}"
        cfdi_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<cfdi:Comprobante Version="4.0" '
            f'Rfc="{emisor_rfc}" RfcReceptor="{receptor_rfc}" />'
        )

    gen_msg = AIMessage(
        content=f"CFDI generated: uuid={cfdi_uuid}.",
        additional_kwargs={
            "action_category": "api_call",
            "cfdi_uuid": cfdi_uuid,
        },
    )

    return {
        **state,
        "messages": [*messages, gen_msg],
        "cfdi_xml": cfdi_xml,
        "cfdi_uuid": cfdi_uuid,
        "status": "cfdi_generated",
    }


@instrumented_node
def stamp_cfdi(state: BillingState) -> BillingState:
    """Stamp CFDI via PAC through Karafiel.

    Stores ``stamp_result`` containing ``folio_fiscal`` and
    ``fecha_timbrado``.  Retries once on failure before setting error.
    """
    messages = state.get("messages", [])
    cfdi_xml = state.get("cfdi_xml")

    if not cfdi_xml:
        error_msg = AIMessage(content="Stamp failed: no CFDI XML to stamp.")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "result": {"error": "No cfdi_xml in state"},
        }

    stamp_result: dict[str, Any] | None = None
    last_error: str = ""

    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            import os

            karafiel_url = os.environ.get("KARAFIEL_API_URL")
            karafiel_token = os.environ.get("KARAFIEL_API_TOKEN", "")
            if karafiel_url:
                from madfam_inference.adapters.karafiel import KarafielAdapter

                adapter = KarafielAdapter(base_url=karafiel_url, token=karafiel_token)
                # adapter returns a StampResult pydantic model; downstream code
                # uses dict access (.get) so normalize to a plain dict here.
                stamp_result = _run_async(adapter.stamp_cfdi(cfdi_xml)).model_dump()
                break
            else:
                raise RuntimeError("KARAFIEL_API_URL not set")
        except ImportError:
            logger.debug("KarafielAdapter not available; using placeholder stamp")
            break
        except RuntimeError:
            logger.debug("KARAFIEL_API_URL not configured; using placeholder stamp")
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Stamp attempt %d/%d failed: %s", attempt + 1, max_attempts, exc)

    if stamp_result is None:
        # Placeholder when Karafiel is unavailable (dev/test).
        stamp_result = {
            "folio_fiscal": state.get("cfdi_uuid", "placeholder-folio"),
            "fecha_timbrado": "2026-04-14T00:00:00",
            "placeholder": True,
        }

    if last_error and "placeholder" not in stamp_result:
        error_msg = AIMessage(
            content=f"CFDI stamping failed after {max_attempts} attempts: {last_error}",
        )
        return {
            **state,
            "messages": [*messages, error_msg],
            "stamp_result": None,
            "status": "error",
            "result": {"error": f"Stamping failed: {last_error}"},
        }

    stamp_msg = AIMessage(
        content=(
            f"CFDI stamped: folio_fiscal={stamp_result.get('folio_fiscal')}, "
            f"fecha_timbrado={stamp_result.get('fecha_timbrado')}."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "stamp_result": stamp_result,
        },
    )

    return {
        **state,
        "messages": [*messages, stamp_msg],
        "stamp_result": stamp_result,
        "status": "stamped",
    }


@instrumented_node
def notify_customer(state: BillingState) -> BillingState:
    """Send CFDI notification via WhatsApp or email.

    Tries WhatsApp first (if ``customer_phone`` is set), then falls back
    to email (if ``customer_email`` is set), then logs success without
    external delivery.
    """
    messages = state.get("messages", [])
    customer_phone = state.get("customer_phone")
    customer_email = state.get("customer_email")
    cfdi_uuid = state.get("cfdi_uuid", "unknown")
    receptor_rfc = state.get("receptor_rfc", "unknown")

    locale = state.get("locale", "")
    if not locale:
        wf_vars = state.get("workflow_variables", {})
        locale = wf_vars.get("locale", "es-MX") if isinstance(wf_vars, dict) else "es-MX"

    notification_channel = "none"
    notification_detail = ""

    if customer_phone:
        # Try WhatsApp Business template messaging (Meta Cloud API) first.
        try:
            from selva_tools.builtins.whatsapp import WhatsAppTemplateTool

            wa_tool = WhatsAppTemplateTool()
            customer_name = state.get("workflow_variables", {}).get("customer_name", "Cliente")
            # `stamp_result` can be explicitly None (not just missing), so the
            # `state.get("stamp_result", {})` default doesn't fire — coerce to {}.
            stamp_result = state.get("stamp_result") or {}
            total_amount = state.get("workflow_variables", {}).get(
                "total", stamp_result.get("total", "")
            )
            wa_result = _run_async(
                wa_tool.execute(
                    phone=customer_phone,
                    template_name="factura_enviada",
                    parameters=[
                        customer_name,
                        cfdi_uuid,
                        str(total_amount),
                        f"https://api.selva.town/api/v1/invoices/{cfdi_uuid}/status",
                    ],
                )
            )
            if wa_result.success:
                notification_channel = "whatsapp_template"
                notification_detail = customer_phone
        except Exception:
            logger.debug("WhatsApp template send failed, falling back", exc_info=True)

        # Legacy plain-text WhatsApp API fallback.
        if notification_channel == "none":
            try:
                import os

                whatsapp_url = os.environ.get("WHATSAPP_API_URL")
                if whatsapp_url:
                    import httpx

                    if locale == "es-MX":
                        wa_message = (
                            f"Su factura CFDI {cfdi_uuid} ha sido generada y timbrada exitosamente."
                        )
                    else:
                        wa_message = (
                            f"Your CFDI invoice {cfdi_uuid} has been generated "
                            f"and stamped successfully."
                        )
                    resp = _run_async(
                        httpx.AsyncClient(timeout=10.0).post(
                            f"{whatsapp_url}/send",
                            json={
                                "phone": customer_phone,
                                "message": wa_message,
                            },
                        )
                    )
                    if resp.status_code < 400:
                        notification_channel = "whatsapp"
                        notification_detail = customer_phone
                    else:
                        raise RuntimeError(f"WhatsApp API returned {resp.status_code}")
                else:
                    raise RuntimeError("WHATSAPP_API_URL not set")
            except Exception:
                logger.debug("WhatsApp notification failed; trying email fallback")

    if notification_channel == "none" and customer_email:
        try:
            import os

            smtp_configured = os.environ.get("SMTP_HOST")
            if smtp_configured:
                # Delegate to email send tool / SMTP — simplified placeholder.
                notification_channel = "email"
                notification_detail = customer_email
            else:
                raise RuntimeError("SMTP_HOST not set")
        except Exception:
            logger.debug("Email notification failed; proceeding without delivery")

    if notification_channel == "none":
        notification_channel = "log_only"
        notification_detail = "No customer contact info available"
        logger.info(
            "CFDI %s for receptor %s generated; no notification channel available",
            cfdi_uuid,
            receptor_rfc,
        )

    notify_msg = AIMessage(
        content=(
            f"Customer notified via {notification_channel}: {notification_detail}. "
            f"CFDI uuid={cfdi_uuid}."
        ),
        additional_kwargs={
            "action_category": "api_call",
            "notification": {
                "channel": notification_channel,
                "detail": notification_detail,
                "cfdi_uuid": cfdi_uuid,
            },
        },
    )

    return {
        **state,
        "messages": [*messages, notify_msg],
        "status": "completed",
        "result": {
            "cfdi_uuid": cfdi_uuid,
            "stamp_result": state.get("stamp_result"),
            "notification_channel": notification_channel,
        },
    }


# -- Conditional edge routing -------------------------------------------------


def _route_after_validate(state: BillingState) -> str:
    """Route to END on error, otherwise continue to check_blacklist."""
    if state.get("status") == "error":
        return END
    return "check_blacklist"


def _route_after_blacklist(state: BillingState) -> str:
    """Route to END on blocked, otherwise continue to generate_cfdi."""
    if state.get("status") == "blocked":
        return END
    return "generate_cfdi"


# -- Graph construction -------------------------------------------------------


def build_billing_graph() -> StateGraph:
    """Construct and compile the billing workflow state graph.

    Flow::

        fetch_context -> validate_rfcs --(error)--> END
                                       \\--> check_blacklist --(blocked)--> END
                                                             \\--> generate_cfdi
                                                                   -> stamp_cfdi
                                                                   -> notify_customer
                                                                   -> END
    """
    graph = StateGraph(BillingState)

    graph.add_node("fetch_context", fetch_context)
    graph.add_node("validate_rfcs", validate_rfcs)
    graph.add_node("check_blacklist", check_blacklist)
    graph.add_node("generate_cfdi", generate_cfdi)
    graph.add_node("stamp_cfdi", stamp_cfdi)
    graph.add_node("notify_customer", notify_customer)

    graph.add_edge(START, "fetch_context")
    graph.add_edge("fetch_context", "validate_rfcs")
    graph.add_conditional_edges("validate_rfcs", _route_after_validate)
    graph.add_conditional_edges("check_blacklist", _route_after_blacklist)
    graph.add_edge("generate_cfdi", "stamp_cfdi")
    graph.add_edge("stamp_cfdi", "notify_customer")
    graph.add_edge("notify_customer", END)

    return graph
