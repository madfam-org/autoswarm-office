"""Tests for the Idempotency-Key dependency.

Pinned contract per ``apps/nexus-api/nexus_api/idempotency.py``:

| Header sent? | Key seen before? | cached | save() effect |
|--------------|------------------|--------|---------------|
| no           | n/a              | None   | no-op         |
| yes          | no               | None   | stores body   |
| yes          | yes              | dict   | overwrites    |

Plus failure-mode coverage:
- Redis unavailable → graceful degrade (cached=None, save no-ops)
- Corrupted cache row → cache miss + warning
- Cross-org isolation: same Idempotency-Key value from two different
  orgs MUST NOT share a cache row.
- Cross-method isolation: same key against /a vs /b MUST NOT share.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_request(method: str = "POST", path: str = "/api/v1/swarms/dispatch"):
    req = MagicMock()
    req.method = method
    req.url.path = path
    return req


def _mock_user(org_id: str = "org-A", sub: str = "user-1") -> dict:
    return {"sub": sub, "org_id": org_id, "roles": ["user"]}


class TestKeyComposition:
    """Cross-tenant + cross-endpoint isolation."""

    def test_org_id_in_key(self) -> None:
        from nexus_api.idempotency import _build_redis_key

        k = _build_redis_key("org-A", "POST", "/api/v1/swarms/dispatch", "k1")
        assert "org-A" in k
        assert "POST" in k
        assert "/api/v1/swarms/dispatch" in k
        assert "k1" in k

    def test_different_orgs_get_different_keys(self) -> None:
        """Same key value, different orgs → different Redis keys.

        This is the cross-tenant data-leak prevention. Without org_id
        in the cache key, tenant B replaying tenant A's response would
        return A's response body (which may contain A's task_id, etc).
        """
        from nexus_api.idempotency import _build_redis_key

        k_a = _build_redis_key("org-A", "POST", "/api/v1/x", "shared-key")
        k_b = _build_redis_key("org-B", "POST", "/api/v1/x", "shared-key")
        assert k_a != k_b

    def test_different_methods_get_different_keys(self) -> None:
        from nexus_api.idempotency import _build_redis_key

        k_post = _build_redis_key("org-A", "POST", "/api/v1/x", "k")
        k_put = _build_redis_key("org-A", "PUT", "/api/v1/x", "k")
        assert k_post != k_put

    def test_different_paths_get_different_keys(self) -> None:
        from nexus_api.idempotency import _build_redis_key

        k_a = _build_redis_key("org-A", "POST", "/api/v1/x", "k")
        k_b = _build_redis_key("org-A", "POST", "/api/v1/y", "k")
        assert k_a != k_b


class TestNoHeaderPath:
    """Caller didn't send Idempotency-Key — dependency yields no-op."""

    @pytest.mark.asyncio
    async def test_no_header_yields_inert_context(self) -> None:
        from nexus_api.idempotency import get_idempotency_context

        ctx = await get_idempotency_context(
            request=_mock_request(),
            idempotency_key=None,
            user=_mock_user(),
        )
        assert ctx.key is None
        assert ctx.cached is None
        assert ctx.is_replay is False

    @pytest.mark.asyncio
    async def test_no_header_save_is_noop(self) -> None:
        """save() must NOT crash when there's no key to save under."""
        from nexus_api.idempotency import get_idempotency_context

        ctx = await get_idempotency_context(
            request=_mock_request(),
            idempotency_key=None,
            user=_mock_user(),
        )
        # Must not raise.
        await ctx.save({"task_id": "t-1"})


class TestFirstTimeRequest:
    """Header sent, key never seen → cached=None, save() stores."""

    @pytest.mark.asyncio
    async def test_first_request_returns_cached_none_and_saves(self) -> None:
        from nexus_api.idempotency import get_idempotency_context

        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock()
        # First call to GET returns None (no cache row yet).
        mock_redis.execute_with_retry.return_value = None

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="abc-123",
                user=_mock_user(),
            )

        assert ctx.key == "abc-123"
        assert ctx.cached is None
        assert ctx.is_replay is False

        # Now save and verify SET is called with the right key + TTL.
        await ctx.save({"task_id": "new-task-1"})
        # Two calls: GET (during dependency resolution) + SET (after save).
        assert mock_redis.execute_with_retry.await_count == 2
        set_call = mock_redis.execute_with_retry.await_args_list[1]
        assert set_call.args[0] == "set"
        assert "org-A" in set_call.args[1]
        assert "POST" in set_call.args[1]
        assert "abc-123" in set_call.args[1]
        body_arg = set_call.args[2]
        assert json.loads(body_arg) == {"task_id": "new-task-1"}
        assert set_call.kwargs["ex"] == 86400  # 24h default


class TestReplayRequest:
    """Header sent, key seen before → cached=dict, save() overwrites."""

    @pytest.mark.asyncio
    async def test_replay_returns_cached_response(self) -> None:
        from nexus_api.idempotency import get_idempotency_context

        cached_body = {"task_id": "previously-dispatched-1"}
        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock(
            return_value=json.dumps(cached_body).encode("utf-8")
        )

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="seen-before",
                user=_mock_user(),
            )

        assert ctx.is_replay is True
        assert ctx.cached == cached_body

    @pytest.mark.asyncio
    async def test_replay_with_string_redis_response(self) -> None:
        """Some redis client configs return str instead of bytes.

        The decode fallback should handle both. Pin the contract.
        """
        from nexus_api.idempotency import get_idempotency_context

        cached_body = {"x": 1}
        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock(
            return_value=json.dumps(cached_body)  # str, not bytes
        )

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="k",
                user=_mock_user(),
            )

        assert ctx.cached == cached_body


class TestDegradedModes:
    """Failure modes must NOT crash the request — they must degrade."""

    @pytest.mark.asyncio
    async def test_redis_unavailable_yields_inert_context(self) -> None:
        """Redis pool throwing on get_redis_pool → no replay, no cache."""
        from nexus_api.idempotency import get_idempotency_context

        with patch(
            "selva_redis_pool.get_redis_pool",
            side_effect=RuntimeError("redis down"),
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="k",
                user=_mock_user(),
            )

        # Header was present so key is preserved for logging.
        assert ctx.key == "k"
        # But cached is None and the redis ref is None too.
        assert ctx.cached is None
        assert ctx._redis is None

        # save() must no-op rather than crash on the None redis.
        await ctx.save({"x": 1})

    @pytest.mark.asyncio
    async def test_corrupted_cache_row_treated_as_miss(self) -> None:
        """A non-JSON cache row should be treated as a miss + logged."""
        from nexus_api.idempotency import get_idempotency_context

        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock(
            return_value=b"this is not valid JSON"
        )

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="corrupted",
                user=_mock_user(),
            )

        assert ctx.cached is None
        assert ctx.key == "corrupted"
        # save() works — it'll overwrite the corrupted row on success.
        await ctx.save({"valid": "json"})

    @pytest.mark.asyncio
    async def test_save_swallows_redis_set_failure(self) -> None:
        """A SET that raises during save() must not propagate.

        The user-visible response has already been computed; failing
        to cache it for replay is a defense-in-depth degradation, not
        a bug worth crashing the request over.
        """
        from nexus_api.idempotency import get_idempotency_context

        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock(
            side_effect=[None, RuntimeError("write timeout")]
        )

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="k",
                user=_mock_user(),
            )
            await ctx.save({"x": 1})  # must not raise


class TestUserOrgIdResolution:
    """org_id comes from the user dict; missing → ``platform`` fallback."""

    @pytest.mark.asyncio
    async def test_missing_org_id_falls_back_to_platform(self) -> None:
        """Defense in depth — a malformed user dict shouldn't leak.

        Falling back to ``platform`` keeps cross-tenant isolation
        because no real tenant has org_id="platform" (that's the
        MADFAM-internal scope).
        """
        from nexus_api.idempotency import get_idempotency_context

        mock_redis = MagicMock()
        mock_redis.execute_with_retry = AsyncMock(return_value=None)

        with patch(
            "selva_redis_pool.get_redis_pool", return_value=mock_redis
        ):
            ctx = await get_idempotency_context(
                request=_mock_request(),
                idempotency_key="k",
                user={"sub": "u"},  # no org_id
            )

        # GET call uses platform-scoped key.
        get_call = mock_redis.execute_with_retry.await_args_list[0]
        assert "platform" in get_call.args[1]
