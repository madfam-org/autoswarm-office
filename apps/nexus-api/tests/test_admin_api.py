"""Tests for the admin API router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
class TestAdminAuth:
    async def test_non_admin_gets_403(self) -> None:
        """A user without the admin role should be rejected."""
        from nexus_api.routers.admin import _require_admin

        with pytest.raises(HTTPException) as exc_info:
            _require_admin({"sub": "u1", "roles": ["viewer"]})
        assert exc_info.value.status_code == 403

    async def test_admin_passes(self) -> None:
        from nexus_api.routers.admin import _require_admin

        user = _require_admin({"sub": "u1", "roles": ["admin"]})
        assert user["sub"] == "u1"


@pytest.mark.asyncio
class TestListUsers:
    async def test_list_users_returns_empty_when_redis_unavailable(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/admin/users", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
class TestKickUser:
    async def test_kick_publishes_to_redis(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        mock_redis_client = AsyncMock()
        mock_redis_client.publish = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.client = AsyncMock(return_value=mock_redis_client)

        with patch("nexus_api.routers.admin.get_redis_pool", return_value=mock_pool):
            resp = await client.post(
                "/api/v1/admin/kick",
                headers=auth_headers,
                json={"session_id": "sess-123", "reason": "testing"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "kick_published"


@pytest.mark.asyncio
class TestRoomConfig:
    async def test_update_room_config(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        mock_redis_client = AsyncMock()
        mock_redis_client.publish = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.client = AsyncMock(return_value=mock_redis_client)

        with patch("nexus_api.routers.admin.get_redis_pool", return_value=mock_pool):
            resp = await client.post(
                "/api/v1/admin/room-config",
                headers=auth_headers,
                json={"motd": "Welcome to Selva!"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "config_published"
