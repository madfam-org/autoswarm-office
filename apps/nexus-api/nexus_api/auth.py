"""Janua OIDC JWT verification and FastAPI authentication dependencies."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import Settings, get_settings
from .middleware.security import org_id_var

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()

# In-memory JWKS cache with TTL-based expiration.
# Thread-safety note: This module runs inside a single-process ASGI server
# (uvicorn) with a single-threaded asyncio event loop.  Global dict/float
# assignments are atomic under CPython's GIL, so no lock is needed.  If
# running under a multi-threaded ASGI server, wrap _fetch_jwks() with an
# asyncio.Lock.
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_time: float | None = None
_JWKS_TTL_SECONDS = 3600.0


async def _fetch_jwks(issuer_url: str) -> dict[str, Any]:
    """Fetch the JSON Web Key Set from the Janua OIDC well-known endpoint.

    Results are cached in-module with a 1-hour TTL.  After the TTL expires
    the next request will refresh the cache.
    """
    import time

    global _jwks_cache, _jwks_cache_time  # noqa: PLW0603

    now = time.monotonic()
    if (
        _jwks_cache is not None
        and _jwks_cache_time is not None
        and (now - _jwks_cache_time) < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache

    jwks_url = f"{issuer_url.rstrip('/')}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        return _jwks_cache


def _get_signing_key(jwks: dict[str, Any], token: str) -> dict[str, Any]:
    """Extract the correct signing key from the JWKS based on the token's ``kid`` header."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if kid is None:
        raise JWTError("Token header missing 'kid' claim")

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key

    raise JWTError(f"Signing key '{kid}' not found in JWKS")


async def verify_jwt(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Decode and validate a Janua-issued RS256 JWT.

    Returns the full decoded payload on success.

    Raises:
        HTTPException(401): On any verification failure.
    """
    if settings is None:
        settings = get_settings()

    try:
        jwks = await _fetch_jwks(settings.janua_issuer_url)
        signing_key = _get_signing_key(jwks, token)

        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.janua_client_id,
            issuer=settings.janua_issuer_url,
        )
        return payload

    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch JWKS: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """FastAPI dependency that extracts and verifies the Bearer token.

    Returns a user dict containing at minimum ``sub``, ``roles``, and
    ``org_id`` from the JWT claims.

    For worker/gateway shared-secret tokens, the target tenant org_id
    MUST be declared via the ``X-Selva-Tenant-Org`` request header.
    Calls without that header resolve to ``org_id="platform"`` and the
    receiving endpoint is expected to enforce the ``service`` role.
    """
    if settings.environment == "development" and settings.dev_auth_bypass:
        org_id_var.set("dev-org")
        return {
            "sub": "dev-user-00000000",
            "roles": ["admin", "tactician", "enterprise-cleanroom"],
            "org_id": "dev-org",
            "email": "dev@autoswarm.local",
        }

    # Reject hardcoded dev token in production
    if settings.environment == "production" and credentials.credentials == "dev-bypass":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token for production environment",
        )

    # Worker/gateway service token (shared secret, not a JWT)
    if (
        settings.worker_api_token
        and settings.worker_api_token != "dev-bypass"
        and credentials.credentials == settings.worker_api_token
    ):
        # Worker token holders MUST declare their target tenant via header.
        # Falls back to "platform" only for cross-tenant maintenance ops
        # (those endpoints check for the "service" role explicitly).
        tenant_org = request.headers.get("X-Selva-Tenant-Org", "").strip()
        if not tenant_org:
            # Platform-scoped service call (e.g. /metrics, audit-log writers).
            # The endpoint itself must verify "service" role for safety.
            tenant_org = "platform"
        org_id_var.set(tenant_org)
        return {
            "sub": "service:worker",
            "roles": ["service", "worker"],
            "org_id": tenant_org,
            "email": "worker@selva.internal",
        }

    payload = await verify_jwt(credentials.credentials, settings)

    # Set the verified org_id in the context variable for RLS middleware
    org_id_var.set(payload.get("org_id", "default"))

    return {
        "sub": payload.get("sub"),
        "roles": payload.get("roles", []),
        "org_id": payload.get("org_id"),
        "email": payload.get("email"),
    }


def require_role(role: str):
    """Dependency factory that enforces a specific role on the authenticated user.

    Usage::

        @router.post("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(): ...
    """

    async def _role_checker(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if role not in user.get("roles", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' is required",
            )
        return user

    return _role_checker


async def require_non_guest(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Reject guest users from performing write/privileged operations.

    Applied per-endpoint (not router-level) to preserve GET access for guests.
    """
    if "guest" in user.get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest users cannot perform this action",
        )
    return user


async def require_non_demo(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Block demo users from performing real actions."""
    if "demo" in user.get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo users cannot perform this action",
        )
    return user


# ---------------------------------------------------------------------------
# Type alias & multi-role factory used by Wave 4 routers
# ---------------------------------------------------------------------------

#: Type alias for the user dict returned by all auth dependencies.
CurrentUser = dict[str, Any]


def require_roles(roles: list[str]):
    """Dependency factory that enforces ANY of the given roles.

    Usage::

        @router.get("/admin-or-cleanroom")
        async def endpoint(
            user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
        ): ...
    """

    async def _roles_checker(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        user_roles = user.get("roles", [])
        if not any(r in user_roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles {roles} is required",
            )
        return user

    return _roles_checker
