"""Redis token-bucket rate limiter middleware."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from selva_redis_pool import get_redis_pool

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP.

    Uses Redis INCR + EXPIRE for a simple sliding-window counter.
    Falls back to allowing all requests if Redis is unavailable.
    """

    def __init__(
        self, app: ASGIApp, redis_url: str, requests_per_minute: int = 60
    ) -> None:
        super().__init__(app)
        self.redis_url = redis_url
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exempt health endpoints from rate limiting (K8s probes)
        if request.url.path.startswith("/api/v1/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // 60
        key = f"selva:ratelimit:{client_ip}:{window}"

        try:
            pool = get_redis_pool(url=self.redis_url)
            client = await pool.client()
            try:
                pipe = client.pipeline()
                await pipe.incr(key)
                await pipe.expire(key, 120)  # 2x window so key outlives its minute
                results = await pipe.execute()
                current_count: int = results[0]

                if current_count > self.requests_per_minute:
                    retry_after = 60 - int(time.time() % 60)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )
            except Exception:
                logger.debug("Redis pipeline failed for rate limiting; allowing request")
        except Exception:
            logger.debug("Redis unavailable for rate limiting; allowing request")

        return await call_next(request)
