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
        assert resp.json()["items"] == []

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
        data = resp.json()["items"]
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
        assert len(resp.json()["items"]) == 2

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
        data = resp.json()["items"]
        assert len(data) == 1
        assert data[0]["content"] == "In room A"


# ----------------------------------------------------------------------------
# Tenant-scoping regression tests (commit f35f1b1, wave 3B-B).
#
# Pre-fix: ChatMessageCreate accepted ``org_id`` from the request body, so
# a logged-in user (or a worker token without X-Selva-Tenant-Org) could
# write chat history into another tenant's room. POST also did not require
# auth at all in some code paths.
#
# Post-fix: org_id is server-derived from get_current_user; the body
# schema does not declare the field. Auth is mandatory.
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatMessageTenantScoping:
    async def test_create_chat_message_ignores_body_org_id(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Even if a caller smuggles an ``org_id`` field into the body, the
        persisted row uses the caller's authenticated org, not the body value.

        Pydantic 2's default ignore-extra-fields behaviour drops the
        unrecognised field silently, but we add this test to assert the
        END-TO-END outcome (the persisted row is in the caller's tenant)
        so a future schema change to ``model_config = {"extra": "allow"}``
        would not silently re-open the cross-tenant write hole.
        """
        resp = await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "tenant-iso-room",
                "sender_session_id": "sess-malicious",
                "sender_name": "AttackerBot",
                "content": "Cross-tenant write attempt",
                # Hostile field — must NOT influence the persisted org_id.
                "org_id": "victim-tenant-org",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # Read it back as the dev-org caller: the message MUST appear,
        # proving it was stored under the caller's org (dev-org), not
        # under "victim-tenant-org".
        history = await client.get(
            "/api/v1/chat/history",
            params={"room_id": "tenant-iso-room"},
            headers=auth_headers,
        )
        assert history.status_code == 200
        # The history endpoint returns either a list or the
        # {items, total, limit, offset} envelope depending on which
        # version of the schema is current. Both cases prove the row
        # is in the caller's tenant (otherwise it would be invisible).
        body = history.json()
        items = body if isinstance(body, list) else body.get("items", [])
        contents = [m["content"] for m in items]
        assert "Cross-tenant write attempt" in contents

    async def test_create_chat_message_requires_auth(
        self, client: httpx.AsyncClient
    ) -> None:
        """POST /chat/messages without Bearer auth is rejected.

        Pre-fix this endpoint accepted unauthenticated POSTs from
        Colyseus, which relied on a stable X-Org-Id header that was
        never validated. Post-fix get_current_user is mandatory.
        """
        resp = await client.post(
            "/api/v1/chat/messages",
            json={
                "room_id": "anon-room",
                "sender_session_id": "anon-sess",
                "sender_name": "Anon",
                "content": "Hello",
            },
        )
        assert resp.status_code in (401, 403)
