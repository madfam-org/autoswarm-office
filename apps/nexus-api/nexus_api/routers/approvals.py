"""Approval request management and real-time WebSocket stream."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import ApprovalRequest
from ..ws import manager

router = APIRouter(tags=["approvals"])


# -- Request / Response schemas -----------------------------------------------


class CreateApprovalRequest(BaseModel):
    agent_id: str
    action_category: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    urgency: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    diff: str | None = None


class ApprovalAction(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)


class ApprovalRequestResponse(BaseModel):
    id: str
    agent_id: str
    action_category: str
    action_type: str
    payload: dict[str, Any]
    diff: str | None
    reasoning: str
    urgency: str
    status: str
    feedback: str | None
    created_at: datetime
    responded_at: datetime | None

    model_config = {"from_attributes": True}


# -- Helpers ------------------------------------------------------------------


def _approval_to_response(req: ApprovalRequest) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=str(req.id),
        agent_id=str(req.agent_id),
        action_category=req.action_category,
        action_type=req.action_type,
        payload=req.payload,
        diff=req.diff,
        reasoning=req.reasoning,
        urgency=req.urgency,
        status=req.status,
        feedback=req.feedback,
        created_at=req.created_at,
        responded_at=req.responded_at,
    )


async def _get_request_or_404(request_id: str, db: AsyncSession) -> ApprovalRequest:
    try:
        uid = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID"
        ) from exc

    result = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == uid))
    approval_req = result.scalar_one_or_none()
    if approval_req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    return approval_req


async def _respond_to_request(
    request_id: str,
    decision: str,
    feedback: str | None,
    db: AsyncSession,
) -> ApprovalRequestResponse:
    """Apply an approve/deny decision to a pending request."""
    approval_req = await _get_request_or_404(request_id, db)

    if approval_req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request already resolved with status '{approval_req.status}'",
        )

    approval_req.status = decision
    approval_req.feedback = feedback
    approval_req.responded_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(approval_req)

    response_data = _approval_to_response(approval_req)

    # Broadcast the decision to all connected WebSocket clients.
    await manager.send_approval_response(response_data.model_dump(mode="json"))

    return response_data


# -- Endpoints ----------------------------------------------------------------


@router.get("/", response_model=list[ApprovalRequestResponse], dependencies=[Depends(get_current_user)])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequestResponse]:
    """List all pending approval requests, most recent first."""
    result = await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.created_at.desc())
    )
    requests = result.scalars().all()
    return [_approval_to_response(r) for r in requests]


@router.post("/", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_approval_request(
    body: CreateApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Create a new approval request.

    Called by workers internally when an agent hits a HITL interrupt.
    No authentication required.
    """
    try:
        agent_uuid = uuid.UUID(body.agent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id UUID"
        ) from exc

    approval_req = ApprovalRequest(
        agent_id=agent_uuid,
        action_category=body.action_category,
        action_type=body.action_type,
        payload=body.payload,
        reasoning=body.reasoning,
        urgency=body.urgency,
        diff=body.diff,
        status="pending",
    )
    db.add(approval_req)
    await db.flush()
    await db.refresh(approval_req)

    response_data = _approval_to_response(approval_req)

    # Broadcast the new approval request to all connected WebSocket clients.
    await manager.send_approval_request(response_data.model_dump(mode="json"))

    return response_data


@router.get("/{request_id}", response_model=ApprovalRequestResponse)
async def get_approval_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Retrieve a single approval request by ID.

    Used by workers for polling approval status. No authentication required.
    """
    approval_req = await _get_request_or_404(request_id, db)
    return _approval_to_response(approval_req)


@router.post(
    "/{request_id}/approve",
    response_model=ApprovalRequestResponse,
    dependencies=[Depends(get_current_user)],
)
async def approve_request(
    request_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Approve a pending request (the Tactician presses 'A')."""
    feedback = body.feedback if body else None
    return await _respond_to_request(request_id, "approved", feedback, db)


@router.post(
    "/{request_id}/deny",
    response_model=ApprovalRequestResponse,
    dependencies=[Depends(get_current_user)],
)
async def deny_request(
    request_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """Deny a pending request with optional feedback (the Tactician presses 'B')."""
    feedback = body.feedback if body else None
    return await _respond_to_request(request_id, "denied", feedback, db)


@router.websocket("/ws")
async def approval_websocket(websocket: WebSocket) -> None:
    """Real-time approval event stream.

    Clients connect and receive JSON messages with ``type`` set to either
    ``approval_request`` or ``approval_response`` as events occur.
    """
    # Use a simple incrementing ID if no query param is provided.
    client_id = websocket.query_params.get("client_id", str(uuid.uuid4()))
    await manager.connect(websocket, client_id)
    try:
        while True:
            # Keep the connection alive; the client can send pings or commands.
            data = await websocket.receive_text()
            # Echo-back as a simple keep-alive acknowledgement.
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(client_id)
