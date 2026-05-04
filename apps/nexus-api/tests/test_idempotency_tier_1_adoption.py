"""Regression tests for the Tier 1 Idempotency-Key adoption.

Pins the contract for the four user-blocking mutation endpoints that
adopted ``Depends(get_idempotency_context)`` (see PR #127 for the
helper itself):

- ``POST /api/v1/swarms/dispatch``
- ``POST /api/v1/approvals/{id}/approve``
- ``POST /api/v1/approvals/{id}/deny``
- ``POST /api/v1/onboarding/voice-mode``

For each endpoint we assert four behaviours:

1. **First request with Idempotency-Key**: returns a normal response,
   side effects happen.
2. **Second request with same Idempotency-Key**: returns the SAME
   response body (byte-for-byte), and the side effect did NOT happen
   a second time.
3. **Second request with a DIFFERENT Idempotency-Key**: runs the
   endpoint fresh (a new task / new approval row / new ledger row).
4. **No Idempotency-Key header at all**: endpoint behaves exactly as
   before — no caching, no error.

Test wiring:
    Tests bypass the real Redis pool with a stateful in-memory mock
    (``_FakeRedisPool``) so cache GET/SET round-trips work without
    requiring a live redis-server. The mock implements just enough of
    the ``execute_with_retry(method, key, value, ex=...)`` contract
    that ``idempotency.get_idempotency_context`` and
    ``IdempotencyContext.save`` use.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from nexus_api.models import ApprovalRequest, ConsentLedger, SwarmTask
from nexus_api.routers.onboarding import CONSENT_CLAUSES

# ---------------------------------------------------------------------------
# In-memory Redis stand-in for the idempotency cache
# ---------------------------------------------------------------------------


class _FakeRedisPool:
    """Stateful stand-in for ``selva_redis_pool.RedisPool``.

    Implements only the ``execute_with_retry`` surface used by
    ``idempotency.get_idempotency_context`` (``get``) and
    ``IdempotencyContext.save`` (``set`` with ``ex=...``).
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def execute_with_retry(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if method == "get":
            key = args[0]
            return self.store.get(key)
        if method == "set":
            key, value = args[0], args[1]
            self.store[key] = value
            return True
        raise AssertionError(f"unexpected redis method: {method}")


@pytest.fixture
def fake_redis() -> _FakeRedisPool:
    """A fresh in-memory pool per test (no cross-test cache bleed)."""
    return _FakeRedisPool()


# ---------------------------------------------------------------------------
# Helpers — patches and bootstrap
# ---------------------------------------------------------------------------


def _patch_idempotency_redis(fake: _FakeRedisPool):
    """Patch the lazy ``get_redis_pool`` import inside idempotency.py."""
    return patch(
        "selva_redis_pool.get_redis_pool",
        return_value=fake,
    )


def _patch_dispatch_redis():
    """Stub the swarms-router Redis publish so dispatch succeeds offline."""
    return patch(
        "nexus_api.routers.swarms.get_redis_pool",
        return_value=AsyncMock(execute_with_retry=AsyncMock()),
    )


async def _create_pending_approval(
    *, agent_id: uuid.UUID, org_id: str, db_session: Any
) -> ApprovalRequest:
    """Insert a pending approval row directly (skips the worker route)."""
    req = ApprovalRequest(
        agent_id=agent_id,
        action_category="code_modification",
        action_type="test_action",
        payload={"file": "/tmp/test"},
        reasoning="test",
        urgency="medium",
        status="pending",
        org_id=org_id,
    )
    db_session.add(req)
    await db_session.flush()
    await db_session.refresh(req)
    await db_session.commit()
    return req


async def _bootstrap_tenant_for_onboarding(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/tenants/",
        headers=headers,
        json={"org_name": "Idempotency Test Co"},
    )
    assert resp.status_code == 201, resp.text


# ===========================================================================
# Tier 1 endpoint #1 — POST /api/v1/swarms/dispatch
# ===========================================================================


@pytest.mark.asyncio
class TestDispatchIdempotency:
    """Replay protection for swarm task dispatch."""

    async def test_first_request_dispatches_normally(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        with _patch_idempotency_redis(fake_redis), _patch_dispatch_redis():
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "dispatch test", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "first-key-1"},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] in ("queued", "pending")
        # Cache row must exist for the second call to find.
        assert any("first-key-1" in k for k in fake_redis.store), fake_redis.store

    async def test_replay_returns_same_response_no_duplicate_task(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Same Idempotency-Key twice → same body, ONE task in DB."""
        with _patch_idempotency_redis(fake_redis), _patch_dispatch_redis():
            r1 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "replay check", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "replay-key-1"},
            )
            assert r1.status_code == 201
            r2 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "replay check", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "replay-key-1"},
            )

        # The replay returns a 200-class response — fastapi default 201 on
        # the route, but the cached body is just returned via model_validate.
        # The decorator's status_code only fires for the first call; both
        # bodies must match.
        assert r2.status_code == 201, r2.text
        assert r1.json() == r2.json(), "replay body should match original"

        # Side-effect check: only ONE task row was inserted, not two.
        count_result = await db_session.execute(select(SwarmTask))
        tasks = count_result.scalars().all()
        assert len(tasks) == 1, (
            f"Expected exactly 1 task row after replay; got {len(tasks)}"
        )

    async def test_different_key_dispatches_fresh_task(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Different Idempotency-Key value → fresh dispatch, two tasks."""
        with _patch_idempotency_redis(fake_redis), _patch_dispatch_redis():
            r1 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "first", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "key-aaa"},
            )
            r2 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "second", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "key-bbb"},
            )

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        count_result = await db_session.execute(select(SwarmTask))
        assert len(count_result.scalars().all()) == 2

    async def test_no_header_dispatches_normally_no_caching(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Header absent → endpoint behaves exactly as before."""
        with _patch_idempotency_redis(fake_redis), _patch_dispatch_redis():
            r1 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "no-key", "graph_type": "research"},
                headers=auth_headers,
            )
            r2 = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "no-key", "graph_type": "research"},
                headers=auth_headers,
            )

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"], "no caching without header"
        # No idempotency rows in cache because no header was sent.
        assert fake_redis.store == {}


# ===========================================================================
# Tier 1 endpoint #2 — POST /api/v1/approvals/{id}/approve
# ===========================================================================


@pytest.mark.asyncio
class TestApproveIdempotency:
    """Replay protection for approval approve."""

    async def test_first_request_approves_normally(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )
        with _patch_idempotency_redis(fake_redis):
            resp = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "lgtm"},
                headers={**auth_headers, "Idempotency-Key": "approve-key-1"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"

    async def test_replay_returns_cached_body_no_state_change(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Replay must return the same body. Side-effect: row stays approved."""
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "first feedback"},
                headers={**auth_headers, "Idempotency-Key": "ap-replay"},
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "DIFFERENT feedback ignored on replay"},
                headers={**auth_headers, "Idempotency-Key": "ap-replay"},
            )

        assert r1.status_code == 200
        # Without idempotency the second call would 409 (already resolved).
        # With idempotency it returns the cached 200 body from the first.
        assert r2.status_code == 200, (
            f"replay should return cached 200, not {r2.status_code}: {r2.text}"
        )
        assert r1.json() == r2.json()

    async def test_different_key_against_resolved_request_returns_409(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Different key value bypasses the cache → real endpoint runs.

        The approval is already resolved by the first call, so the
        second (different-key) call hits the 409 path. This proves the
        cache IS keyed on the Idempotency-Key value, not on the URL.
        """
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "ok"},
                headers={**auth_headers, "Idempotency-Key": "ap-k1"},
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "second"},
                headers={**auth_headers, "Idempotency-Key": "ap-k2-different"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 409, r2.text

    async def test_no_header_behaves_as_before(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """No header → first 200, second 409 (no replay protection)."""
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "ok"},
                headers=auth_headers,
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/approve",
                json={"feedback": "ok"},
                headers=auth_headers,
            )

        assert r1.status_code == 200
        assert r2.status_code == 409
        # No cache row was written when header was absent.
        assert fake_redis.store == {}


# ===========================================================================
# Tier 1 endpoint #3 — POST /api/v1/approvals/{id}/deny
# ===========================================================================


@pytest.mark.asyncio
class TestDenyIdempotency:
    """Replay protection for approval deny — mirrors approve."""

    async def test_first_request_denies_normally(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )
        with _patch_idempotency_redis(fake_redis):
            resp = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "no thanks"},
                headers={**auth_headers, "Idempotency-Key": "deny-key-1"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "denied"

    async def test_replay_returns_cached_body(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "first"},
                headers={**auth_headers, "Idempotency-Key": "dn-replay"},
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "ignored on replay"},
                headers={**auth_headers, "Idempotency-Key": "dn-replay"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200, r2.text
        assert r1.json() == r2.json()

    async def test_different_key_against_resolved_request_returns_409(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "first"},
                headers={**auth_headers, "Idempotency-Key": "dn-k1"},
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "second"},
                headers={**auth_headers, "Idempotency-Key": "dn-k2-different"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 409

    async def test_no_header_behaves_as_before(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        agent_id = uuid.uuid4()
        req = await _create_pending_approval(
            agent_id=agent_id, org_id="dev-org", db_session=db_session
        )

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "ok"},
                headers=auth_headers,
            )
            r2 = await client.post(
                f"/api/v1/approvals/{req.id}/deny",
                json={"feedback": "ok"},
                headers=auth_headers,
            )

        assert r1.status_code == 200
        assert r2.status_code == 409
        assert fake_redis.store == {}


# ===========================================================================
# Tier 1 endpoint #4 — POST /api/v1/onboarding/voice-mode
# ===========================================================================


@pytest.mark.asyncio
class TestOnboardingVoiceModeIdempotency:
    """Replay protection for first-run voice-mode selection."""

    async def test_first_request_selects_normally(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        await _bootstrap_tenant_for_onboarding(client, auth_headers)
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]

        with _patch_idempotency_redis(fake_redis):
            resp = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers={**auth_headers, "Idempotency-Key": "vm-first"},
            )

        assert resp.status_code == 201, resp.text
        assert resp.json()["voice_mode"] == "dyad_selva_plus_user"

    async def test_replay_returns_same_response_no_duplicate_ledger_row(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Without idempotency the second call would 409 ("already selected").

        With idempotency the second call replays the cached 201 and the
        consent ledger has exactly ONE row.
        """
        await _bootstrap_tenant_for_onboarding(client, auth_headers)
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers={**auth_headers, "Idempotency-Key": "vm-replay"},
            )
            r2 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers={**auth_headers, "Idempotency-Key": "vm-replay"},
            )

        assert r1.status_code == 201
        # Replay would normally hit 409 ("already selected"); idempotency
        # short-circuits with the cached 201 body.
        assert r2.status_code == 201, (
            f"Replay should return cached 201, got {r2.status_code}: {r2.text}"
        )
        assert r1.json() == r2.json()

        # Side effect check: ONE consent ledger row, not two.
        ledgers = (await db_session.execute(select(ConsentLedger))).scalars().all()
        assert len(ledgers) == 1, (
            f"Replay must not append a second ledger row; got {len(ledgers)}"
        )

    async def test_different_key_returns_409_after_first_success(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Different key value bypasses cache → real endpoint runs → 409."""
        await _bootstrap_tenant_for_onboarding(client, auth_headers)
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers={**auth_headers, "Idempotency-Key": "vm-k1"},
            )
            r2 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers={**auth_headers, "Idempotency-Key": "vm-k2-different"},
            )

        assert r1.status_code == 201
        assert r2.status_code == 409, r2.text

    async def test_no_header_behaves_as_before(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """Header absent → first 201, second 409 (no replay protection)."""
        await _bootstrap_tenant_for_onboarding(client, auth_headers)
        phrase = CONSENT_CLAUSES["dyad_selva_plus_user"]["typed_phrase"]

        with _patch_idempotency_redis(fake_redis):
            r1 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers=auth_headers,
            )
            r2 = await client.post(
                "/api/v1/onboarding/voice-mode",
                json={"mode": "dyad_selva_plus_user", "typed_confirmation": phrase},
                headers=auth_headers,
            )

        assert r1.status_code == 201
        assert r2.status_code == 409
        assert fake_redis.store == {}


# ===========================================================================
# Cache invariants that span all four endpoints
# ===========================================================================


@pytest.mark.asyncio
class TestCachePayloadShape:
    """Cached payload should be valid JSON the response model can re-validate."""

    async def test_dispatch_cached_body_is_json_round_trippable(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        db_session: Any,
        fake_redis: _FakeRedisPool,
    ) -> None:
        """The body stored under the cache key must be JSON-decodable
        and shaped like a SwarmTaskResponse.
        """
        with _patch_idempotency_redis(fake_redis), _patch_dispatch_redis():
            resp = await client.post(
                "/api/v1/swarms/dispatch",
                json={"description": "shape test", "graph_type": "research"},
                headers={**auth_headers, "Idempotency-Key": "shape-1"},
            )
        assert resp.status_code == 201

        cache_keys = [k for k in fake_redis.store if "shape-1" in k]
        assert cache_keys, f"expected a cache key containing shape-1; got {fake_redis.store}"
        cached_raw = fake_redis.store[cache_keys[0]]
        cached = json.loads(cached_raw)
        # Must contain the same identifying fields the endpoint returns.
        assert cached["id"] == resp.json()["id"]
        assert cached["status"] in ("queued", "pending")
        assert cached["graph_type"] == "research"
