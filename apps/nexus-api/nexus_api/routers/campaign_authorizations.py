"""Owner campaign-authorization proxy (PhyndCRM money-gate, admin-only).

Thin, honest proxy over PhyndCRM's ``campaignAuthorizations`` tRPC router
so the Selva office UI can show the owner's pending queue, the full
review (rendered production email per variant, guardrails, consent
coverage) and record authorize/reject decisions. PhyndCRM stays the
single source of truth and the fail-closed send gate; the decision is
attributed to the authenticated admin's identity and lands in phynd's
immutable ledger as ``"<operator> (via service:selva)"``.

Unconfigured (missing ``PHYND_CRM_URL`` / ``PHYND_CRM_FEDERATION_TOKEN``)
returns 503 — never an empty queue that could read as "nothing pending".
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import require_role
from ..services import phynd_campaign_authorizations as bridge

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/campaigns/authorizations",
    tags=["Campaign Authorizations"],
    dependencies=[Depends(require_role("admin"))],
)


def _map_bridge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, bridge.PhyndAuthorizationsUnconfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    if isinstance(exc, bridge.PhyndAuthorizationsError):
        upstream = exc.status_code if 400 <= exc.status_code < 500 else 502
        return HTTPException(status_code=upstream, detail=exc.detail)
    logger.error("PhyndCRM authorization bridge failure: %s", exc)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="PhyndCRM authorization bridge unreachable",
    )


class DecideRequest(BaseModel):
    decision: Literal["authorized", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


class RequestFreshRequest(BaseModel):
    campaign_id: str = Field(min_length=1)


@router.get("/pending")
async def pending() -> dict[str, Any]:
    try:
        return {"pending": await bridge.list_pending()}
    except Exception as exc:  # noqa: BLE001
        raise _map_bridge_error(exc) from exc


@router.get("/{authorization_id}/preview")
async def preview(authorization_id: str) -> dict[str, Any]:
    try:
        return await bridge.get_preview(authorization_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_bridge_error(exc) from exc


@router.post("/{authorization_id}/decide")
async def decide(
    authorization_id: str,
    body: DecideRequest,
    user: dict[str, Any] = Depends(require_role("admin")),  # noqa: B008
) -> dict[str, Any]:
    note = (body.note or "").strip()
    if body.decision == "rejected" and not note:
        raise HTTPException(
            status_code=422,
            detail="A written reason (note) is required to reject.",
        )
    operator = str(user.get("email") or user.get("sub") or "").strip()
    if not operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated operator identity unavailable; cannot attribute decision.",
        )
    try:
        record = await bridge.decide(
            authorization_id=authorization_id,
            decision=body.decision,
            operator=operator,
            note=note or None,
        )
        return record
    except Exception as exc:  # noqa: BLE001
        raise _map_bridge_error(exc) from exc


@router.post("/request")
async def request_fresh(body: RequestFreshRequest) -> dict[str, Any]:
    try:
        return await bridge.request_fresh(body.campaign_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_bridge_error(exc) from exc
