"""WebSocket connection manager for real-time approval notifications."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages.

    Connections are keyed by a ``client_id`` (typically the authenticated
    user's ``sub`` claim or a session identifier).

    Optionally tracks each connection's tenant ``org_id`` so the manager
    can deliver per-tenant broadcasts via ``broadcast_to_org``. This is
    the load-bearing primitive for tenant-scoped real-time streams: even
    if a worker token writes events, only WS clients in the same tenant
    will receive the live relay.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        # client_id -> org_id, populated when connect() is called with org_id.
        # Connections without a recorded org_id are NOT included in
        # broadcast_to_org() to avoid information leak when a client failed
        # to declare its tenant.
        self.connection_org: dict[str, str] = {}

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        *,
        org_id: str | None = None,
    ) -> None:
        """Accept an incoming WebSocket and register it under *client_id*.

        Pass ``org_id`` to scope subsequent ``broadcast_to_org`` deliveries
        to this client's tenant. Connections registered without an org_id
        will not receive tenant-scoped broadcasts.
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        if org_id is not None:
            self.connection_org[client_id] = org_id
        logger.info(
            "WebSocket connected: %s (org=%s, total: %d)",
            client_id,
            org_id or "<unscoped>",
            len(self.active_connections),
        )

    def disconnect(self, client_id: str) -> None:
        """Remove a connection by *client_id*."""
        self.active_connections.pop(client_id, None)
        self.connection_org.pop(client_id, None)
        logger.info(
            "WebSocket disconnected: %s (total: %d)", client_id, len(self.active_connections)
        )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to every connected client.

        Broken connections are silently pruned during broadcast.

        WARNING: This is unscoped and will deliver the message to every
        tenant. Use ``broadcast_to_org`` for tenant-scoped streams.
        """
        stale: list[str] = []
        for client_id, ws in self.active_connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("Failed to send to %s; pruning connection", client_id)
                stale.append(client_id)

        for client_id in stale:
            self.disconnect(client_id)

    async def broadcast_to_org(self, org_id: str, message: dict[str, Any]) -> None:
        """Send a JSON message only to clients registered under ``org_id``.

        Unscoped connections (those connected without an org_id) are NOT
        included -- they cannot be safely matched to a tenant, so excluding
        them is the conservative default that prevents cross-tenant leak.

        Broken connections are silently pruned during broadcast.
        """
        stale: list[str] = []
        for client_id, ws in self.active_connections.items():
            if self.connection_org.get(client_id) != org_id:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning(
                    "Failed to send to %s (org=%s); pruning connection", client_id, org_id
                )
                stale.append(client_id)

        for client_id in stale:
            self.disconnect(client_id)

    async def send_to(self, client_id: str, message: dict[str, Any]) -> None:
        """Send a JSON message to a specific client."""
        ws = self.active_connections.get(client_id)
        if ws is not None:
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("Failed to send to %s; pruning connection", client_id)
                self.disconnect(client_id)

    async def send_approval_request(
        self, request: dict[str, Any], *, org_id: str | None = None
    ) -> None:
        """Broadcast an approval request notification to connected clients.

        When ``org_id`` is provided, only clients in that tenant receive the
        message (preferred). When omitted, falls back to a global broadcast
        for backwards compatibility -- this should be considered a bug; all
        callers should supply the org_id.
        """
        msg = {"type": "approval_request", "payload": request}
        if org_id is not None:
            await self.broadcast_to_org(org_id, msg)
        else:
            logger.warning("send_approval_request called without org_id (unscoped broadcast)")
            await self.broadcast(msg)

    async def send_approval_response(
        self, response: dict[str, Any], *, org_id: str | None = None
    ) -> None:
        """Broadcast an approval response notification to connected clients.

        Same scoping semantics as ``send_approval_request``.
        """
        msg = {"type": "approval_resolved", "payload": response}
        if org_id is not None:
            await self.broadcast_to_org(org_id, msg)
        else:
            logger.warning("send_approval_response called without org_id (unscoped broadcast)")
            await self.broadcast(msg)


class MessageRateLimiter:
    """Sliding-window rate limiter for WebSocket messages.

    Each client is tracked independently.  Messages older than
    *window_seconds* are purged on every ``check()`` call so that
    memory stays bounded even for long-lived connections.
    """

    def __init__(self, max_messages: int = 30, window_seconds: float = 60.0) -> None:
        self._max = max_messages
        self._window = window_seconds
        self._messages: dict[str, deque[float]] = {}

    def check(self, client_id: str) -> bool:
        """Return ``True`` if the message is allowed, ``False`` if rate-limited."""
        now = time.monotonic()
        q = self._messages.setdefault(client_id, deque())
        # Purge expired entries
        while q and (now - q[0]) > self._window:
            q.popleft()
        if len(q) >= self._max:
            return False
        q.append(now)
        return True

    def remove(self, client_id: str) -> None:
        """Clean up state for a disconnected client."""
        self._messages.pop(client_id, None)


# Singleton instance shared across the application.
manager = ConnectionManager()

# Event stream WebSocket manager (observability).
event_manager = ConnectionManager()
