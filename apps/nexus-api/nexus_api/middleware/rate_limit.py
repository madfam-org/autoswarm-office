"""Redis token-bucket rate limiter middleware."""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP.

    Uses Redis INCR + EXPIRE for a simple sliding-window counter.
    Falls back to allowing all requests if Redis is unavailable.
    """

    def __init__(self, app, redis_url: str, requests_per_minute: int = 60) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.redis_url = redis_url
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        key = f"autoswarm:ratelimit:{client_ip}"

        try:
            redis_client = aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                pipe = redis_client.pipeline()
                await pipe.incr(key)
                await pipe.expire(key, 60)
                results = await pipe.execute()
                current_count: int = results[0]

                if current_count > self.requests_per_minute:
                    retry_after = 60 - int(time.time() % 60)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )
            finally:
                await redis_client.aclose()
        except Exception:
            logger.debug("Redis unavailable for rate limiting; allowing request")

        return await call_next(request)
