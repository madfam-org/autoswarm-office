"""Router tests for /api/v1/dragon-eggs.

In dev_auth_bypass mode (set in conftest.py), every request resolves
to a user with email='dev@autoswarm.local' and roles=['admin', ...].
The 'admin' role is in ``_PHASE_1_BYPASS_ROLES`` so the dev user
admits to the dragon-egg surface.

For the negative test (non-admin gets 403), we override the
``get_current_user`` dependency to return a non-admin user.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nexus_api.auth import get_current_user
from nexus_api.main import app

# ---------------------------------------------------------------------------
# CRUD endpoints — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLayEggEndpoint:
    async def test_lay_bluesky_egg_returns_201_with_actions(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/api/v1/dragon-eggs",
            json={
                "persona_id": "router_p1",
                "platform": "bluesky",
                "handle": "@x.bsky.social",
                "display_name": "Router Test",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "laid"
        assert body["progress"] == 0.0
        assert body["platform"] == "bluesky"
        assert body["owner_org_id"] == "madfam"
        # Full action timeline returned inline.
        assert len(body["actions"]) == 18
        # Sorted by day_offset asc.
        days = [a["day_offset"] for a in body["actions"]]
        assert days == sorted(days)

    async def test_lay_mastodon_without_instance_url_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/api/v1/dragon-eggs",
            json={
                "persona_id": "router_p_bad",
                "platform": "mastodon",
                "handle": "@x@y",
                "display_name": "Bad",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "instance_url" in response.json()["detail"]

    async def test_lay_unsupported_platform_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/api/v1/dragon-eggs",
            json={
                "persona_id": "p",
                "platform": "tiktok",
                "handle": "x",
                "display_name": "X",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "tiktok" in response.json()["detail"].lower()

    async def test_lay_duplicate_returns_409(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        body = {
            "persona_id": "router_dup",
            "platform": "bluesky",
            "handle": "@a",
            "display_name": "A",
        }
        first = await client.post("/api/v1/dragon-eggs", json=body, headers=auth_headers)
        assert first.status_code == 201
        second = await client.post("/api/v1/dragon-eggs", json=body, headers=auth_headers)
        assert second.status_code == 409


@pytest.mark.asyncio
class TestListAndGetEgg:
    async def _lay(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        persona: str,
        platform: str = "bluesky",
    ) -> dict[str, Any]:
        body = {
            "persona_id": persona,
            "platform": platform,
            "handle": f"@{persona}",
            "display_name": persona,
        }
        if platform == "mastodon":
            body["instance_url"] = "https://fosstodon.org"
        response = await client.post("/api/v1/dragon-eggs", json=body, headers=auth_headers)
        assert response.status_code == 201, response.text
        return response.json()

    async def test_list_returns_all_eggs(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._lay(client, auth_headers, "list_a")
        await self._lay(client, auth_headers, "list_b", "reddit")
        response = await client.get("/api/v1/dragon-eggs", headers=auth_headers)
        assert response.status_code == 200
        eggs = response.json()
        ids = {e["persona_id"] for e in eggs}
        assert {"list_a", "list_b"}.issubset(ids)

    async def test_list_filtered_by_platform(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._lay(client, auth_headers, "filt_bsky", "bluesky")
        await self._lay(client, auth_headers, "filt_red", "reddit")
        response = await client.get(
            "/api/v1/dragon-eggs?platform=reddit", headers=auth_headers
        )
        assert response.status_code == 200
        eggs = response.json()
        assert all(e["platform"] == "reddit" for e in eggs)

    async def test_get_unknown_returns_404(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/api/v1/dragon-eggs/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestActionEndpoints:
    async def test_skip_action_marks_skipped_and_advances_progress(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "skip_p",
                    "platform": "reddit",
                    "handle": "u/x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()
        first_action = egg["actions"][0]

        response = await client.post(
            f"/api/v1/dragon-eggs/{egg['id']}/actions/{first_action['id']}/skip",
            json={"notes": "manual skip"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "skipped"
        assert "manual skip" in (body["notes"] or "")

        # Progress should now be > 0.
        detail = (
            await client.get(f"/api/v1/dragon-eggs/{egg['id']}", headers=auth_headers)
        ).json()
        assert detail["progress"] > 0.0

    async def test_skip_completed_action_returns_409(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "skip_done",
                    "platform": "reddit",
                    "handle": "u/x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()
        action_id = egg["actions"][0]["id"]

        # First skip succeeds.
        first = await client.post(
            f"/api/v1/dragon-eggs/{egg['id']}/actions/{action_id}/skip",
            json={},
            headers=auth_headers,
        )
        assert first.status_code == 200
        # Second skip on the same action — already skipped.
        second = await client.post(
            f"/api/v1/dragon-eggs/{egg['id']}/actions/{action_id}/skip",
            json={},
            headers=auth_headers,
        )
        assert second.status_code == 409

    async def test_execute_action_marks_in_flight(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "exec_p",
                    "platform": "bluesky",
                    "handle": "@x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()
        # Find a planned (worker-dispatchable) action.
        planned = [a for a in egg["actions"] if a["status"] == "planned"]
        assert planned, "expected at least one planned action"
        action_id = planned[0]["id"]

        response = await client.post(
            f"/api/v1/dragon-eggs/{egg['id']}/actions/{action_id}/execute",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "in_flight"
        assert body["executed_at"] is not None


@pytest.mark.asyncio
class TestTransitionEndpoint:
    async def test_transition_returns_egg_and_transitioned_flag(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "trans_p",
                    "platform": "bluesky",
                    "handle": "@x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()

        response = await client.post(
            f"/api/v1/dragon-eggs/{egg['id']}/transition",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "egg" in body
        assert "transitioned" in body
        # Nothing has happened yet — should be no-op.
        assert body["transitioned"] is False
        assert body["egg"]["status"] == "laid"


@pytest.mark.asyncio
class TestReleaseEgg:
    async def test_release_force_matured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "rel_force_p",
                    "platform": "bluesky",
                    "handle": "@x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()

        response = await client.delete(
            f"/api/v1/dragon-eggs/{egg['id']}?force_status=matured",
            headers=auth_headers,
        )
        assert response.status_code == 204

        detail = await client.get(
            f"/api/v1/dragon-eggs/{egg['id']}", headers=auth_headers
        )
        assert detail.status_code == 200  # row still exists, just promoted
        assert detail.json()["status"] == "matured"

    async def test_release_no_force_status_deletes(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        egg = (
            await client.post(
                "/api/v1/dragon-eggs",
                json={
                    "persona_id": "rel_del_p",
                    "platform": "bluesky",
                    "handle": "@x",
                    "display_name": "X",
                },
                headers=auth_headers,
            )
        ).json()

        response = await client.delete(
            f"/api/v1/dragon-eggs/{egg['id']}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        detail = await client.get(
            f"/api/v1/dragon-eggs/{egg['id']}", headers=auth_headers
        )
        assert detail.status_code == 404


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminGate:
    async def test_non_admin_user_gets_403(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Override get_current_user to return a tenant user — they
        should be rejected by ``require_dragon_egg_admin``."""

        async def _tenant_user() -> dict[str, Any]:
            return {
                "sub": "tenant-user-1",
                "roles": ["tactician"],  # NOT admin/superadmin
                "email": "tenant@example.com",
                "org_id": "some-tenant",
            }

        app.dependency_overrides[get_current_user] = _tenant_user
        try:
            response = await client.get("/api/v1/dragon-eggs", headers=auth_headers)
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    async def test_admin_email_admits_even_without_role(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """admin@madfam.io is on the email allowlist — admits even
        without the 'admin' role."""

        async def _founder_user() -> dict[str, Any]:
            return {
                "sub": "founder-1",
                "roles": ["tactician"],  # not admin
                "email": "admin@madfam.io",
                "org_id": "madfam",
            }

        app.dependency_overrides[get_current_user] = _founder_user
        try:
            response = await client.get("/api/v1/dragon-eggs", headers=auth_headers)
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user, None)
