"""Admin endpoints for space management (kick, room config).

All endpoints require the ``admin`` role from the JWT. In dev mode with auth
bypass, the dummy user always has ``admin`` in its roles array.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from selva_redis_pool import get_redis_pool

from ..auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
    """Dependency that ensures the caller has the admin role."""
    roles = user.get("roles") or []
    if "admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


# -- Schemas ------------------------------------------------------------------


class KickRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)


class RoomConfigUpdate(BaseModel):
    max_players: int | None = Field(default=None, ge=1, le=100)
    motd: str | None = Field(default=None, max_length=500)


class ConnectedUser(BaseModel):
    session_id: str
    name: str
    status: str


# -- Endpoints ----------------------------------------------------------------


@router.get("/users", response_model=list[ConnectedUser])
async def list_connected_users(
    _admin: dict = Depends(_require_admin),  # noqa: B008
) -> list[ConnectedUser]:
    """List currently connected users via Redis.

    The Colyseus server publishes player state to Redis. We read the
    latest snapshot here. Returns an empty list if Redis is unavailable.
    """
    try:
        pool = get_redis_pool()
        client = await pool.client()
        # redis-py overloads `hgetall` to return either `Awaitable[dict]`
        # (async client) or `dict` (sync client) — the union breaks
        # `await`.  Our `client` is the async variant, so coerce via cast.
        data = await cast(Awaitable[dict[Any, Any]], client.hgetall("autoswarm:connected-players"))
        users: list[ConnectedUser] = []
        for session_id, raw in data.items():
            import json

            try:
                info = json.loads(raw)
                users.append(
                    ConnectedUser(
                        session_id=session_id,
                        name=info.get("name", "Unknown"),
                        status=info.get("status", "online"),
                    )
                )
            except (json.JSONDecodeError, TypeError):
                users.append(ConnectedUser(session_id=session_id, name="Unknown", status="online"))
        return users
    except Exception:
        logger.warning("Failed to fetch connected users from Redis")
        return []


@router.post("/kick", status_code=200)
async def kick_user(
    body: KickRequest,
    _admin: dict = Depends(_require_admin),  # noqa: B008
) -> dict[str, str]:
    """Publish a kick action to Redis for the Colyseus server to execute."""
    try:
        pool = get_redis_pool()
        client = await pool.client()
        import json

        await client.publish(
            "autoswarm:admin-actions",
            json.dumps({"action": "kick", "session_id": body.session_id, "reason": body.reason}),
        )
        return {"status": "kick_published", "session_id": body.session_id}
    except Exception as exc:
        logger.exception("Failed to publish kick action")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to communicate with game server",
        ) from exc


@router.post("/room-config", status_code=200)
async def update_room_config(
    body: RoomConfigUpdate,
    _admin: dict = Depends(_require_admin),  # noqa: B008
) -> dict[str, str]:
    """Update room configuration via Redis pub/sub."""
    try:
        pool = get_redis_pool()
        client = await pool.client()
        import json

        config = body.model_dump(exclude_unset=True)
        await client.publish(
            "autoswarm:admin-actions",
            json.dumps({"action": "room_config", "config": config}),
        )
        return {"status": "config_published"}
    except Exception as exc:
        logger.exception("Failed to publish room config")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to communicate with game server",
        ) from exc
