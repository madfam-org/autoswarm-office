"""Redis connection pool with circuit breaker and retry logic."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Iterator
from enum import Enum
from typing import Any, cast

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool, Redis

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _redis_span(command: str) -> Iterator[None]:
    """Wrap a Redis command in an OTel span if OpenTelemetry is available."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("autoswarm-redis-pool")
        with tracer.start_as_current_span(
            f"redis.{command}",
            attributes={"db.system": "redis", "db.operation": command},
        ):
            yield
    except ImportError:
        yield


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RedisPool:
    """Singleton Redis connection pool with circuit breaker.

    Features:
    - Connection pooling (configurable max connections)
    - Circuit breaker (closed -> open after N failures -> half-open after cooldown)
    - Exponential backoff retry on transient failures
    - Metrics (active/idle/waiting connections)
    """

    _instance: RedisPool | None = None

    def __init__(
        self,
        url: str | None = None,
        max_connections: int | None = None,
        circuit_failure_threshold: int = 5,
        circuit_cooldown: float = 30.0,
    ) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._max_connections = max_connections or int(
            os.environ.get("REDIS_POOL_MAX_CONNECTIONS", "20")
        )
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_cooldown = circuit_cooldown

        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

        # Circuit breaker state
        self._circuit_state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @classmethod
    def get_instance(cls, **kwargs: Any) -> RedisPool:
        """Get or create the singleton pool instance."""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    async def _ensure_pool(self) -> Redis:
        """Create the pool and client if not already initialized."""
        if self._client is None:
            self._pool = ConnectionPool.from_url(
                self._url,
                max_connections=self._max_connections,
                retry_on_timeout=True,
                decode_responses=True,
            )
            self._client = Redis(connection_pool=self._pool)
        return self._client

    def _check_circuit(self) -> None:
        """Check circuit breaker state and raise if open."""
        if self._circuit_state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._circuit_cooldown:
                self._circuit_state = CircuitState.HALF_OPEN
                logger.info("Redis circuit breaker half-open, attempting recovery")
            else:
                remaining = self._circuit_cooldown - elapsed
                raise ConnectionError(f"Redis circuit breaker open, {remaining:.1f}s until retry")

    def _record_success(self) -> None:
        """Record a successful operation."""
        if self._circuit_state == CircuitState.HALF_OPEN:
            logger.info("Redis circuit breaker closed (recovery successful)")
        self._circuit_state = CircuitState.CLOSED
        self._failure_count = 0

    def _record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._circuit_failure_threshold:
            self._circuit_state = CircuitState.OPEN
            logger.warning(
                "Redis circuit breaker opened after %d failures",
                self._failure_count,
            )

    async def execute_with_retry(
        self,
        operation: str,
        *args: object,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        **kwargs: object,
    ) -> object:
        """Execute a Redis command with retry and circuit breaker.

        Args:
            operation: Redis command name (e.g., 'get', 'set', 'lpush').
            *args: Positional arguments for the command.
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay between retries (seconds).
            max_delay: Maximum delay between retries (seconds).
            **kwargs: Keyword arguments for the command.
        """
        self._check_circuit()
        client = await self._ensure_pool()

        last_exc: Exception | None = None
        with _redis_span(operation):
            for attempt in range(max_retries + 1):
                try:
                    method = getattr(client, operation)
                    result = await method(*args, **kwargs)
                    self._record_success()
                    return result
                except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as exc:
                    last_exc = exc
                    self._record_failure()
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            "Redis %s failed (attempt %d/%d), retrying in %.1fs: %s",
                            operation,
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]

    async def client(self) -> Redis:
        """Get the underlying Redis client (for pub/sub and pipelines)."""
        self._check_circuit()
        return await self._ensure_pool()

    def metrics(self) -> dict[str, object]:
        """Return connection pool metrics."""
        if self._pool is None:
            return {
                "active": 0,
                "available": 0,
                "max_connections": self._max_connections,
                "circuit_state": self._circuit_state.value,
                "failure_count": self._failure_count,
            }
        return {
            "active": len(self._pool._in_use_connections),
            "available": len(self._pool._available_connections),
            "max_connections": self._max_connections,
            "circuit_state": self._circuit_state.value,
            "failure_count": self._failure_count,
        }

    async def close(self) -> None:
        """Close the pool and release all connections."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
        logger.info("Redis pool closed")

    async def ping(self) -> bool:
        """Check connectivity."""
        try:
            client = await self._ensure_pool()
            # redis-py stubs type ``ping`` as ``Awaitable[bool] | bool`` because
            # the same method is shared with the sync client; on
            # ``redis.asyncio.Redis`` it always returns an awaitable.
            await cast(Awaitable[bool], client.ping())
            self._record_success()
            return True
        except Exception:
            self._record_failure()
            return False


def get_redis_pool(**kwargs: Any) -> RedisPool:
    """Get the singleton Redis pool instance."""
    return RedisPool.get_instance(**kwargs)
