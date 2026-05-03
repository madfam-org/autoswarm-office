"""Tests for the chat history API."""

from __future__ import annotations

import httpx
import pytest

# The dev auth bypass returns org_id="dev-org" — messages must match.
DEV_ORG = "dev-org"


@pytest.mark.asyncio
class TestChatMessages:
    async def test_create_message(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "office",
                "sender_session_id": "sess-1",
                "sender_name": "Alice",
                "content": "Hello world",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"

    async def test_create_system_message(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "office",
                "sender_session_id": "",
                "sender_name": "System",
                "content": "Player joined",
                "is_system": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def test_empty_content_422(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "office",
                "sender_session_id": "sess-1",
                "sender_name": "Alice",
                "content": "",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestChatHistory:
    async def test_empty_history(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get(
            "/api/v1/chat/history",
            params={"room_id": "office"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_history_returns_messages(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        for i in range(3):
            r = await client.post(
                "/api/v1/chat/messages",
                json={
                    "room_id": "test-room",
                    "sender_session_id": f"sess-{i}",
                    "sender_name": f"User{i}",
                    "content": f"Message {i}",
                },
                headers=auth_headers,
            )
            assert r.status_code == 201

        resp = await client.get(
            "/api/v1/chat/history",
            params={"room_id": "test-room"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        contents = {m["content"] for m in data}
        assert contents == {"Message 0", "Message 1", "Message 2"}

    async def test_history_limit(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        for i in range(5):
            await client.post(
                "/api/v1/chat/messages",
                json={
                    "room_id": "limit-room",
                    "sender_session_id": "s",
                    "sender_name": "Bot",
                    "content": f"Msg {i}",
                },
                headers=auth_headers,
            )

        resp = await client.get(
            "/api/v1/chat/history",
            params={"room_id": "limit-room", "limit": 2},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_history_room_scoped(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "room-a",
                "sender_session_id": "s",
                "sender_name": "Bot",
                "content": "In room A",
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "room-b",
                "sender_session_id": "s",
                "sender_name": "Bot",
                "content": "In room B",
            },
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/chat/history",
            params={"room_id": "room-a"},
            headers=auth_headers,
        )
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "In room A"
