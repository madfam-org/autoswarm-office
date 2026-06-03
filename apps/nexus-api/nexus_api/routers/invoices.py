"""Invoice management -- dispatch billing graph + query CFDI status."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from selva_redis_pool import get_redis_pool

from ..auth import get_current_user, require_non_guest
from ..config import get_settings
from ..database import get_db
from ..models import SwarmTask
from ..tenant import TenantContext, get_tenant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Invoices"], dependencies=[Depends(get_current_user)])


# -- Request / Response schemas -----------------------------------------------


class InvoiceRequest(BaseModel):
    """Payload for generating a CFDI 4.0 invoice via the billing graph."""

    receptor_rfc: str = Field(
        ..., min_length=12, max_length=13, description="Receptor RFC (12 or 13 chars)"
    )
    conceptos: list[dict[str, Any]] = Field(
        ..., min_length=1, description="Line items (clave_prod_serv, descripcion, importe, ...)"
    )
    forma_pago: str = Field(default="01", description="SAT forma de pago code")
    metodo_pago: str = Field(default="PUE", description="PUE or PPD")
    moneda: str = Field(default="MXN", description="Currency code")
    emisor_rfc: str | None = Field(
        default=None, description="Override emisor RFC (defaults to org config)"
    )
    customer_email: str | None = Field(default=None, description="Email for invoice delivery")
    customer_phone: str | None = Field(default=None, description="Phone for WhatsApp delivery")


class InvoiceDispatchResponse(BaseModel):
    """Response after dispatching a billing graph task."""

    task_id: str
    status: str


class InvoiceStatusResponse(BaseModel):
    """CFDI status lookup result."""

    uuid: str
    status: str
    detail: dict[str, Any] | None = None


# -- Endpoints ----------------------------------------------------------------


@router.post(
    "/generate",
    response_model=InvoiceDispatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def generate_invoice(
    body: InvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> InvoiceDispatchResponse:
    """Dispatch a billing graph to generate and stamp a CFDI 4.0 invoice.

    Creates a ``SwarmTask`` with ``graph_type="billing"`` and enqueues it
    on the Redis task stream for worker consumption.
    """
    settings = get_settings()
    request_id = getattr(request.state, "request_id", None)

    payload: dict[str, Any] = {
        "receptor_rfc": body.receptor_rfc,
        "conceptos": body.conceptos,
        "forma_pago": body.forma_pago,
        "metodo_pago": body.metodo_pago,
        "moneda": body.moneda,
    }
    if body.emisor_rfc:
        payload["emisor_rfc"] = body.emisor_rfc
    if body.customer_email:
        payload["customer_email"] = body.customer_email
    if body.customer_phone:
        payload["customer_phone"] = body.customer_phone

    task = SwarmTask(
        description=(
            f"Generate CFDI 4.0 invoice for receptor {body.receptor_rfc} "
            f"({len(body.conceptos)} concepto(s))"
        ),
        graph_type="billing",
        assigned_agent_ids=[],
        payload=payload,
        status="queued",
        org_id=tenant.org_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    # Enqueue to Redis task stream.
    try:
        pool = get_redis_pool(url=settings.redis_url)
        task_msg_data: dict[str, Any] = {
            "task_id": str(task.id),
            "graph_type": "billing",
            "description": task.description,
            "assigned_agent_ids": [],
            "required_skills": ["invoicing"],
            "payload": payload,
            "request_id": request_id,
        }
        task_msg = json.dumps(task_msg_data)
        await pool.execute_with_retry("xadd", "selva:task-stream", {"data": task_msg})
    except Exception:
        task.status = "pending"
        await db.flush()
        logger.warning("Redis unavailable; billing task %s persisted as pending", task.id)

    # Emit task.dispatched event (direct DB insert).
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.dispatched",
            event_category="task",
            task_id=task.id,
            graph_type="billing",
            org_id=tenant.org_id,
            request_id=request_id,
            payload={"description": task.description[:200], "graph_type": "billing"},
        )
    except Exception:
        logger.debug("Failed to emit task.dispatched event", exc_info=True)

    return InvoiceDispatchResponse(task_id=str(task.id), status=task.status)


@router.get("/{uuid}/status", response_model=InvoiceStatusResponse)
async def invoice_status(
    uuid: str,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> InvoiceStatusResponse:
    """Check CFDI status via Karafiel.

    Queries the Karafiel compliance API for the stamping status of a
    given CFDI UUID.  Returns a placeholder when Karafiel is unavailable.
    """
    import os

    karafiel_url = os.environ.get("KARAFIEL_API_URL")
    karafiel_token = os.environ.get("KARAFIEL_API_TOKEN", "")

    if karafiel_url:
        try:
            from madfam_inference.adapters.karafiel import KarafielAdapter

            adapter = KarafielAdapter(base_url=karafiel_url, token=karafiel_token)

            # `get_cfdi_status` is an async coroutine returning a CFDIStatus
            # pydantic model — await it directly, do NOT thread-pool it.
            cfdi_status = await adapter.get_cfdi_status(uuid)
            detail_dict = cfdi_status.model_dump()
            return InvoiceStatusResponse(
                uuid=uuid,
                status=cfdi_status.estado or "unknown",
                detail=detail_dict,
            )
        except Exception as exc:
            logger.warning("Karafiel CFDI status lookup failed for %s", uuid, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to query CFDI status from Karafiel",
            ) from exc

    # Karafiel not configured -- return placeholder for dev.
    return InvoiceStatusResponse(
        uuid=uuid,
        status="not_configured",
        detail={"message": "KARAFIEL_API_URL not set; unable to query CFDI status"},
    )
