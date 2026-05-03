"""Chat history API for persistent message storage.

Messages are written by the Colyseus server (fire-and-forget POST, authenticated
with the worker shared-secret token + ``X-Selva-Tenant-Org`` header) and read
by clients to restore chat history on reconnection.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import ChatMessage
from ..tenant import TenantContext, get_tenant

router = APIRouter(tags=["chat"])


# -- Schemas ------------------------------------------------------------------


class ChatMessageCreate(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=100)
    sender_session_id: str = Field(default="", max_length=100)
    sender_name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=500)
    is_system: bool = False
    # NOTE: org_id is NOT accepted from the request body. It is derived from
    # the authenticated caller (JWT claim or worker token X-Selva-Tenant-Org
    # header) to prevent cross-tenant chat-history poisoning.


class ChatMessageResponse(BaseModel):
    id: str
    room_id: str
    sender_session_id: str
    sender_name: str
    content: str
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    items: list[ChatMessageResponse]
    total: int
    limit: int
    offset: int


# -- Endpoints ----------------------------------------------------------------


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    room_id: str = Query(..., min_length=1),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    before: datetime | None = Query(default=None),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> ChatHistoryResponse:
    """Return recent chat messages for a room with pagination, newest first.

    Pagination: use ``limit`` and ``offset`` for standard pagination, or pass
    ``before`` with the ``created_at`` of the oldest message in your current
    batch to fetch the next page (cursor-based).

    Tenant-scoped: only messages with ``org_id == tenant.org_id`` are returned.
    """
    base_query = select(ChatMessage).where(
        ChatMessage.room_id == room_id,
        ChatMessage.org_id == tenant.org_id,
    )

    if before:
        base_query = base_query.where(ChatMessage.created_at < before)

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = count_result.scalar_one()

    # Paginated results
    result = await db.execute(
        base_query.order_by(ChatMessage.created_at.desc()).limit(limit).offset(offset)
    )
    messages = list(result.scalars().all())
    # Return oldest-first for display
    messages.reverse()

    items = [
        ChatMessageResponse(
            id=str(m.id),
            room_id=m.room_id,
            sender_session_id=m.sender_session_id,
            sender_name=m.sender_name,
            content=m.content,
            is_system=m.is_system,
            created_at=m.created_at,
        )
        for m in messages
    ]
    return ChatHistoryResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/messages", status_code=201)
async def create_chat_message(
    body: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict[str, str]:
    """Persist a chat message.

    Requires Bearer-token authentication. The persisted message's ``org_id``
    is derived server-side from the authenticated caller (``user['org_id']``)
    -- the request body does not carry an ``org_id`` field.

    Called by Colyseus (fire-and-forget) using the worker shared-secret token
    plus the ``X-Selva-Tenant-Org`` header to declare the tenant scope.
    """
    org_id = user.get("org_id") or "default"
    msg = ChatMessage(
        room_id=body.room_id,
        sender_session_id=body.sender_session_id,
        sender_name=body.sender_name,
        content=body.content,
        is_system=body.is_system,
        org_id=org_id,
    )
    db.add(msg)
    await db.flush()
    return {"status": "created", "id": str(msg.id)}
