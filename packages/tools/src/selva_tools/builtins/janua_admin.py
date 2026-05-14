"""Janua admin API — OAuth client + organization CRUD.

Existing ``janua_oidc_redirect_register`` covers a single endpoint. This module
surfaces the full admin surface that tenant onboarding needs: create an OAuth
client for the tenant's app, manage its secrets, and provision the Janua
organization that the tenant's users sign in against.

API base: ``JANUA_API_URL`` (default ``https://auth.madfam.io``).
Auth: ``JANUA_INTERNAL_API_KEY`` for zero-touch client registration. Legacy
``JANUA_ADMIN_TOKEN`` remains accepted by older admin routes.
Router surfaces cover ``/api/v1/oauth/clients/*`` and ``/api/v1/organizations/*``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

JANUA_API_URL = os.environ.get("JANUA_API_URL", "https://auth.madfam.io")
JANUA_INTERNAL_API_KEY = os.environ.get("JANUA_INTERNAL_API_KEY", "")
JANUA_ADMIN_TOKEN = os.environ.get("JANUA_ADMIN_TOKEN", "")


def _headers(*, internal: bool = False) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if internal and JANUA_INTERNAL_API_KEY:
        headers["X-Internal-API-Key"] = JANUA_INTERNAL_API_KEY
    elif JANUA_ADMIN_TOKEN:
        headers["Authorization"] = f"Bearer {JANUA_ADMIN_TOKEN}"
    return headers


def _creds_check(*, internal: bool = False) -> str | None:
    if internal and not (JANUA_INTERNAL_API_KEY or JANUA_ADMIN_TOKEN):
        return "JANUA_INTERNAL_API_KEY or JANUA_ADMIN_TOKEN must be set."
    if not internal and not JANUA_ADMIN_TOKEN:
        return "JANUA_ADMIN_TOKEN must be set (service-role token)."
    return None


async def _request(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    *,
    internal: bool = False,
) -> tuple[int, Any]:
    url = f"{JANUA_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method,
            url,
            headers=_headers(internal=internal),
            json=json_body,
        )
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text


def _ok(status: int) -> bool:
    return 200 <= status < 300


def _err(status: int, body: Any) -> str:
    if isinstance(body, dict):
        return body.get("detail") or body.get("message") or str(body)
    return f"HTTP {status}: {body}"


# ---------------------------------------------------------------------------
# OAuth clients
# ---------------------------------------------------------------------------


class JanuaOauthClientCreateTool(BaseTool):
    """Register a new OAuth client. Returns client_id + client_secret (show once)."""

    name = "janua_oauth_client_create"
    description = (
        "Create a new OAuth 2.0 / OIDC client in Janua. Returns the fresh "
        "client_id and client_secret. The secret is displayed ONCE — capture "
        "it immediately into the tenant's app secret store; Janua will not "
        "re-surface it. Use ``grant_types`` = ['authorization_code', "
        "'refresh_token'] for a standard web app; add 'client_credentials' "
        "for service-to-service integrations."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable client name."},
                "description": {"type": "string"},
                "redirect_uris": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Allowed post-auth redirect URIs. Optional for "
                        "client_credentials-only machine clients."
                    ),
                },
                "grant_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["authorization_code", "refresh_token"],
                },
                "client_key": {
                    "type": "string",
                    "description": "Stable AppSpec logical key for idempotent reconciliation.",
                },
                "audience": {
                    "type": "string",
                    "description": "JWT audience for access tokens minted to this client.",
                },
                "allowed_origins": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Browser origins allowed for CORS/OIDC flows.",
                },
                "post_logout_redirect_uris": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed logout redirect URIs.",
                },
                "is_confidential": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "False for browser PKCE clients; true for server/machine clients."
                    ),
                },
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["openid", "profile", "email"],
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional — scope the client to a specific Janua org.",
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check(internal=True)
        if err:
            return ToolResult(success=False, error=err)
        payload = {
            "name": kwargs["name"],
            "description": kwargs.get("description") or "",
            "redirect_uris": kwargs.get("redirect_uris") or [],
            "grant_types": kwargs.get("grant_types", ["authorization_code", "refresh_token"]),
            "allowed_scopes": kwargs.get("scopes", ["openid", "profile", "email"]),
            "client_key": kwargs.get("client_key") or kwargs["name"],
            "audience": kwargs.get("audience"),
            "allowed_origins": kwargs.get("allowed_origins") or [],
            "post_logout_redirect_uris": kwargs.get("post_logout_redirect_uris") or [],
            "is_confidential": kwargs.get("is_confidential", True),
        }
        if kwargs.get("organization_id"):
            payload["organization_id"] = kwargs["organization_id"]
        try:
            status, body = await _request(
                "POST", "/api/v1/oauth/clients/register", json_body=payload, internal=True
            )
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=(f"OAuth client created: {body.get('name')} ({body.get('client_id')})."),
                data={
                    "client_id": body.get("client_id"),
                    "client_secret": body.get("client_secret"),
                    "issuer": JANUA_API_URL,
                    "jwks_uri": f"{JANUA_API_URL}/.well-known/jwks.json",
                    "token_endpoint": f"{JANUA_API_URL}/api/v1/oauth/token",
                    "authorization_endpoint": f"{JANUA_API_URL}/api/v1/oauth/authorize",
                },
            )
        except Exception as e:
            logger.error("janua_oauth_client_create failed: %s", e)
            return ToolResult(success=False, error=str(e))


class JanuaOauthClientUpdateTool(BaseTool):
    """Update an OAuth client's redirect URIs, scopes, or grant types."""

    name = "janua_oauth_client_update"
    description = (
        "Update a Janua OAuth client. Common use: add a new redirect URI "
        "after the tenant's app moves domains, or restrict scopes post-audit. "
        "Omit fields you don't want to change."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "redirect_uris": {"type": "array", "items": {"type": "string"}},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "grant_types": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["client_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        cid = kwargs.pop("client_id")
        payload = {k: v for k, v in kwargs.items() if v is not None}
        try:
            status, body = await _request(
                "PATCH", f"/api/v1/oauth-clients/{cid}", json_body=payload
            )
            if not _ok(status):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True, output=f"Updated OAuth client {cid}.", data={"client_id": cid}
            )
        except Exception as e:
            logger.error("janua_oauth_client_update failed: %s", e)
            return ToolResult(success=False, error=str(e))


class JanuaOauthClientRotateSecretTool(BaseTool):
    """Rotate an OAuth client's secret. Old secret stays valid for a grace window."""

    name = "janua_oauth_client_rotate_secret"
    description = (
        "Rotate the secret of an existing OAuth client. The new secret is "
        "returned ONCE; the old secret remains valid for the grace period "
        "defined by Janua (typically 24h) so the tenant can rolling-restart "
        "their apps. After the grace window, the old secret is revoked."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        cid = kwargs["client_id"]
        try:
            status, body = await _request("POST", f"/api/v1/oauth-clients/{cid}/rotate")
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=f"Rotated secret on client {cid}.",
                data={
                    "client_id": cid,
                    "client_secret": body.get("client_secret"),
                    "expires_old_secret_at": body.get("expires_old_secret_at"),
                },
            )
        except Exception as e:
            logger.error("janua_oauth_client_rotate_secret failed: %s", e)
            return ToolResult(success=False, error=str(e))


class JanuaOauthClientDeleteTool(BaseTool):
    """Delete an OAuth client. Irreversible — HITL gate."""

    name = "janua_oauth_client_delete"
    description = (
        "Delete a Janua OAuth client. Every session issued by this client "
        "is immediately invalidated. Used as the last step of tenant "
        "offboarding AFTER the tenant has confirmed account closure."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        cid = kwargs["client_id"]
        try:
            status, body = await _request("DELETE", f"/api/v1/oauth-clients/{cid}")
            if not _ok(status):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True, output=f"Deleted client {cid}.", data={"client_id": cid}
            )
        except Exception as e:
            logger.error("janua_oauth_client_delete failed: %s", e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Organizations (multi-tenant boundary)
# ---------------------------------------------------------------------------


class JanuaOrgCreateTool(BaseTool):
    """Create a Janua organization — the multi-tenant boundary for RLS."""

    name = "janua_org_create"
    description = (
        "Create a Janua organization. The returned ``org_id`` becomes the "
        "``org_id`` claim on every JWT issued to users in this org, which "
        "downstream services (nexus-api, PhyndCRM, Dhanam) use as the "
        "row-level-security tenant boundary. ``slug`` must be globally "
        "unique and lowercase-dashed."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "slug": {
                    "type": "string",
                    "description": "Lowercase-dashed globally unique identifier.",
                },
                "metadata": {
                    "type": "object",
                    "description": "Arbitrary tenant metadata (RFC, legal_name, region, …).",
                },
            },
            "required": ["name", "slug"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        payload = {
            "name": kwargs["name"],
            "slug": kwargs["slug"],
            "metadata": kwargs.get("metadata") or {},
        }
        try:
            status, body = await _request("POST", "/api/v1/organizations/", json_body=payload)
            if not _ok(status) or not isinstance(body, dict):
                return ToolResult(success=False, error=_err(status, body))
            return ToolResult(
                success=True,
                output=f"Org created: {body.get('slug')} ({body.get('id')}).",
                data={"org_id": body.get("id"), "slug": body.get("slug")},
            )
        except Exception as e:
            logger.error("janua_org_create failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_janua_admin_tools() -> list[BaseTool]:
    return [
        JanuaOauthClientCreateTool(),
        JanuaOauthClientUpdateTool(),
        JanuaOauthClientRotateSecretTool(),
        JanuaOauthClientDeleteTool(),
        JanuaOrgCreateTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    JanuaOauthClientCreateTool,
    JanuaOauthClientUpdateTool,
    JanuaOauthClientRotateSecretTool,
    JanuaOauthClientDeleteTool,
    JanuaOrgCreateTool,
):
    _cls.audience = Audience.PLATFORM
