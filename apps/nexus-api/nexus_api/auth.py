"""Janua OIDC JWT verification and FastAPI authentication dependencies."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()

# In-memory JWKS cache to avoid fetching on every request.
_jwks_cache: dict[str, Any] | None = None


async def _fetch_jwks(issuer_url: str) -> dict[str, Any]:
    """Fetch the JSON Web Key Set from the Janua OIDC well-known endpoint.

    Results are cached in-module for the lifetime of the process.  A full
    production deployment should add TTL-based expiration or background
    refresh, but for an MVP the process-level cache is sufficient.
    """
    global _jwks_cache  # noqa: PLW0603
    if _jwks_cache is not None:
        return _jwks_cache

    jwks_url = f"{issuer_url.rstrip('/')}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
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
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """FastAPI dependency that extracts and verifies the Bearer token.

    Returns a user dict containing at minimum ``sub``, ``roles``, and
    ``org_id`` from the JWT claims.
    """
    if settings.environment == "development":
        return {
            "sub": "dev-user-00000000",
            "roles": ["admin", "tactician"],
            "org_id": "dev-org",
            "email": "dev@autoswarm.local",
        }

    payload = await verify_jwt(credentials.credentials, settings)

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
