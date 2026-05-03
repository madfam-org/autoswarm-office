"""Audit trail middleware -- logs state-changing requests to the audit_logs table."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from audit logging (high-frequency internal endpoints).
_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/events",
    "/metrics",
    "/health",
)

# Pattern to extract resource type and optional ID from the URL path.
# Matches /api/v1/<resource_type>/<optional_id>/...
_RESOURCE_RE = re.compile(
    r"^/api/v1/(?P<resource_type>[a-z][a-z0-9_-]+)"
    r"(?:/(?P<resource_id>[0-9a-f-]{8,36}))?"
)


def _extract_resource_info(path: str) -> tuple[str, str | None]:
    """Extract resource_type and resource_id from the URL path."""
    m = _RESOURCE_RE.match(path)
    if m:
        return m.group("resource_type"), m.group("resource_id")
    return path.split("/")[-1] or "unknown", None


def _extract_user_id(request: Request) -> str:
    """Extract user_id from JWT claims attached by auth dependencies.

    Falls back to "anonymous" if no user info is available.
    """
    # The TenantRLSMiddleware or auth dependency may set state.user
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "sub"):
        return user.sub

    # Fallback: try to parse the Authorization header manually
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import base64
            import json

            token = auth_header.split(" ", 1)[1]
            # Decode JWT payload (no verification -- just for logging)
            payload_b64 = token.split(".")[1]
            # Add padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload.get("sub", "anonymous")
        except Exception:
            logger.debug(
                "Failed to extract user_id from Bearer token for audit log",
                exc_info=True,
            )

    return "anonymous"


def _extract_org_id(request: Request) -> str:
    """Extract org_id from request state."""
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "org_id"):
        return user.org_id
    return getattr(request.state, "org_id", "default")


def _get_client_ip(request: Request) -> str:
    """Get the client IP address, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs state-changing HTTP requests to the audit_logs table.

    Only records requests that result in a 2xx response to avoid
    logging failed/unauthorized attempts.  Inserts are fire-and-forget
    to avoid impacting request latency.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Only audit state-changing methods with successful responses.
        if request.method not in _STATE_CHANGING_METHODS:
            return response

        if response.status_code < 200 or response.status_code >= 300:
            return response

        # Skip exempt paths.
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return response

        # Fire-and-forget audit insert.
        asyncio.create_task(
            _insert_audit_log(request, response),
            name=f"audit-{request.method}-{path}",
        )

        return response


async def _insert_audit_log(request: Request, response: Response) -> None:
    """Insert an audit log entry. Failures are logged and suppressed."""
    try:
        from ..database import async_session_factory
        from ..models import AuditLog

        resource_type, resource_id = _extract_resource_info(request.url.path)
        user_id = _extract_user_id(request)
        org_id = _extract_org_id(request)
        ip_address = _get_client_ip(request)

        # Build details dict with relevant info
        details: dict[str, object] = {
            "path": request.url.path,
            "status_code": response.status_code,
        }
        if request.url.query:
            details["query"] = str(request.url.query)[:500]

        async with async_session_factory() as db:
            entry = AuditLog(
                id=uuid.uuid4(),
                org_id=org_id,
                user_id=user_id,
                action=request.method,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address,
            )
            db.add(entry)
            await db.commit()
    except Exception:
        logger.debug("Failed to insert audit log entry", exc_info=True)
