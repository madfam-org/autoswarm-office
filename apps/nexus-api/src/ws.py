"""WebSocket connection manager for real-time approval notifications."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages.

    Connections are keyed by a ``client_id`` (typically the authenticated
    user's ``sub`` claim or a session identifier).
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Accept an incoming WebSocket and register it under *client_id*."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info("WebSocket connected: %s (total: %d)", client_id, len(self.active_connections))

    def disconnect(self, client_id: str) -> None:
        """Remove a connection by *client_id*."""
        self.active_connections.pop(client_id, None)
        logger.info(
            "WebSocket disconnected: %s (total: %d)", client_id, len(self.active_connections)
        )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to every connected client.

        Broken connections are silently pruned during broadcast.
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

    async def send_to(self, client_id: str, message: dict[str, Any]) -> None:
        """Send a JSON message to a specific client."""
        ws = self.active_connections.get(client_id)
        if ws is not None:
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("Failed to send to %s; pruning connection", client_id)
                self.disconnect(client_id)

    async def send_approval_request(self, request: dict[str, Any]) -> None:
        """Broadcast an approval request notification to all connected clients."""
        await self.broadcast({"type": "approval_request", "data": request})

    async def send_approval_response(self, response: dict[str, Any]) -> None:
        """Broadcast an approval response notification to all connected clients."""
        await self.broadcast({"type": "approval_response", "data": response})


# Singleton instance shared across the application.
manager = ConnectionManager()
