"""Double-submit cookie CSRF protection middleware."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths exempt from CSRF checks (webhook endpoints receive external calls).
_EXEMPT_PREFIXES = (
    "/api/v1/gateway/",
    "/api/v1/billing/webhooks/",
    "/api/v1/approvals/ws",
    "/api/v1/health/",
)

_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    On every response a ``csrf-token`` cookie is set (if not already present).
    State-changing requests must include an ``X-CSRF-Token`` header whose value
    matches the cookie.  Webhook endpoints are exempted.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _STATE_CHANGING_METHODS and not any(
            request.url.path.startswith(p) for p in _EXEMPT_PREFIXES
        ):
                cookie_token = request.cookies.get("csrf-token")
                header_token = request.headers.get("x-csrf-token")
                if not cookie_token or not header_token or cookie_token != header_token:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token missing or invalid"},
                    )

        response = await call_next(request)

        if "csrf-token" not in request.cookies:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                "csrf-token",
                token,
                httponly=False,
                samesite="strict",
                secure=request.url.scheme == "https",
                max_age=86400,
            )

        return response
