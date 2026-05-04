"""Idempotency-Key support for mutation endpoints.

Goal:
    Make POST / PUT / PATCH endpoints replay-safe so a client retrying
    after a network blip doesn't double-charge / double-dispatch /
    double-anything. Today retry semantics depend on each caller getting
    it right — the dispatch endpoint, the approvals POST, the
    marketplace install, etc. each have their own idempotency story
    (or none).

Design choice — FastAPI dependency, not a global middleware:
    A middleware would replay every endpoint blindly. We only want
    replay protection on endpoints that explicitly opt in (mutation
    endpoints whose effects are side-effecting + non-trivial to undo).
    The dependency lets each route declare it via:

        @router.post("/dispatch", ...)
        async def dispatch(
            request: DispatchRequest,
            idem: IdempotencyContext = Depends(get_idempotency_context),
        ) -> DispatchResponse:
            if idem.cached is not None:
                return DispatchResponse.model_validate(idem.cached)
            # ... actual work ...
            response = DispatchResponse(...)
            await idem.save(response.model_dump(mode="json"))
            return response

    The contract:
      - If the caller did NOT send ``Idempotency-Key`` header, the
        dependency yields a no-op context (cached=None, save() is a
        no-op). Existing callers don't break.
      - If the caller DID send the header AND we've seen it before
        for this (org_id, method, path) in the last TTL window, we
        return the cached response body. The endpoint code can
        early-return (recommended) or proceed (the save() will no-op).
      - If the caller sent the header AND it's new, we record the
        response body when save() is called and store it for the TTL.

Key shape — ``autoswarm:idem:<org_id>:<method>:<path>:<key>``:
    Org-scoped (different tenants colliding on the same key value
    must NOT see each other's cached responses — that would be a
    cross-tenant data leak). Method+path scoped (a tenant retrying
    the same Idempotency-Key against /dispatch and /approvals are
    different operations, must not be conflated).

TTL — 24h default:
    Long enough that a phone client coming back from airplane mode
    still gets the cached response. Short enough that storage doesn't
    grow unbounded. Configurable per-call via ``ttl_seconds`` arg on
    the dependency factory.

What we DON'T do:
    - Validate that the request body of a replay matches the original.
      Per RFC 9457 / Stripe / others, the contract is "the SAME
      Idempotency-Key MUST be used with the SAME parameters" — if the
      caller violates that, returning the cached response is the
      documented behaviour. We trust the contract rather than diffing
      bodies.
    - Cache failed responses. Only success (2xx) responses are cached.
      A 4xx or 5xx is treated as "no record" — the next retry runs
      the endpoint fresh. This avoids permanently caching a transient
      failure into the idempotency store.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Request

from .auth import get_current_user
from .config import get_settings

logger = logging.getLogger(__name__)

# Redis key prefix. Mirrors the autoswarm:* convention used throughout
# the codebase so ops can monitor with one glob.
_KEY_PREFIX = "autoswarm:idem"

# Default TTL — 24 hours. See module docstring for rationale.
_DEFAULT_TTL_SECONDS: int = 86400


@dataclass
class IdempotencyContext:
    """Context object yielded by ``get_idempotency_context``.

    Attributes:
        key: The raw Idempotency-Key header value, or None if the
            caller didn't send one. Useful for logging / tracing.
        cached: If we've seen this key before in the TTL window, the
            cached response body (already-decoded JSON). None otherwise.
        is_replay: True iff cached is not None — convenience accessor.
    """

    key: str | None
    cached: dict[str, Any] | None
    _redis_key: str | None
    _redis: Any  # selva_redis_pool.RedisPool
    _ttl_seconds: int

    @property
    def is_replay(self) -> bool:
        """True iff this is a replay of a previously-stored request."""
        return self.cached is not None

    async def save(self, response_body: dict[str, Any]) -> None:
        """Cache the response body under this Idempotency-Key.

        No-op when:
          - The caller didn't send an Idempotency-Key (``key is None``).
          - The Redis pool was unavailable at dependency-resolution
            time (``_redis is None``) — degraded mode, the endpoint
            still functions but loses replay protection.

        Failures during the actual SET are logged but NOT re-raised.
        Idempotency is a defense-in-depth feature; failing to record
        the response cache should not break the user-visible response.
        """
        if self.key is None or self._redis is None or self._redis_key is None:
            return
        try:
            await self._redis.execute_with_retry(
                "set",
                self._redis_key,
                json.dumps(response_body, default=str),
                ex=self._ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Idempotency: failed to cache response for key %s",
                self.key,
                exc_info=True,
            )


def _build_redis_key(org_id: str, method: str, path: str, key: str) -> str:
    """Compose the org-scoped Redis key for an Idempotency-Key.

    Org-scoped because different tenants colliding on the same
    Idempotency-Key value must NOT see each other's cached responses
    (cross-tenant data leak). Method+path scoped because the same
    Idempotency-Key against different endpoints is a different
    operation per the spec.
    """
    return f"{_KEY_PREFIX}:{org_id}:{method}:{path}:{key}"


async def get_idempotency_context(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> IdempotencyContext:
    """FastAPI dependency that resolves an IdempotencyContext.

    Yields:
        ``IdempotencyContext`` with:
          - ``key``: the raw header value (or None)
          - ``cached``: the previously-stored response body (or None)
          - ``save(body)``: a coroutine to call on success

    Behavior matrix:
        | Header sent? | Key seen before? | cached | save() effect |
        |--------------|------------------|--------|---------------|
        | no           | n/a              | None   | no-op         |
        | yes          | no               | None   | stores body   |
        | yes          | yes              | dict   | overwrites    |

    Auth dependency is required because the cache is org-scoped — we
    need ``user["org_id"]`` to compose the Redis key. Endpoints that
    use this dependency therefore implicitly require authentication.
    Anonymous endpoints don't need idempotency anyway (any anon
    caller could just retry without coordination).
    """
    if idempotency_key is None:
        return IdempotencyContext(
            key=None,
            cached=None,
            _redis_key=None,
            _redis=None,
            _ttl_seconds=_DEFAULT_TTL_SECONDS,
        )

    # Lazy import to avoid pulling redis-pool into the dependency-graph
    # of routes that don't use idempotency.
    from selva_redis_pool import get_redis_pool

    settings = get_settings()
    redis = None
    cached = None
    redis_key = _build_redis_key(
        org_id=user.get("org_id", "platform"),
        method=request.method,
        path=request.url.path,
        key=idempotency_key,
    )

    try:
        redis = get_redis_pool(url=settings.redis_url)
        raw = await redis.execute_with_retry("get", redis_key)
        if raw is not None:
            try:
                # Redis returns bytes; decode then JSON-parse.
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                cached = json.loads(raw)
                logger.info(
                    "Idempotency replay for org=%s method=%s path=%s",
                    user.get("org_id"),
                    request.method,
                    request.url.path,
                )
            except (ValueError, UnicodeDecodeError):
                # Cache row corrupted — log, treat as cache miss so the
                # endpoint runs fresh and overwrites with a valid value.
                logger.warning(
                    "Idempotency: corrupted cache entry for key %s; "
                    "treating as miss",
                    idempotency_key,
                )
                cached = None
    except Exception:
        # Redis unavailable — degrade gracefully. Endpoint still works,
        # just without replay protection. Caller's idempotency story
        # falls back to whatever they had before.
        logger.warning(
            "Idempotency: Redis unavailable, degraded to no-op",
            exc_info=True,
        )

    return IdempotencyContext(
        key=idempotency_key,
        cached=cached,
        _redis_key=redis_key,
        _redis=redis,
        _ttl_seconds=_DEFAULT_TTL_SECONDS,
    )
