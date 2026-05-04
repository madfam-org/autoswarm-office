"""Selva Vault — Secure secret management for the Swarm.

Provides encrypted storage and retrieval of API keys, tokens, and
credentials. Secrets are stored in the MADFAM K8s cluster via Enclii's
secret management API (backed by ESO + HashiCorp Vault in production,
encrypted-at-rest Redis in development).

Security model:
- Secrets are NEVER logged or included in ToolResult.output
- Retrieval returns masked values by default (last 4 chars visible)
- Full values available only via execute() data dict (not displayed to user)
- All operations require HITL approval via the permission engine
- Audit trail: every read/write is logged with agent_id and timestamp

Env vars:
- ENCLII_API_URL: Enclii Switchyard API base URL
- ENCLII_API_TOKEN: Bearer token for API authentication
- SELVA_VAULT_NAMESPACE: K8s namespace for vault secrets (default: autoswarm)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ENCLII_API_URL = os.environ.get("ENCLII_API_URL", "")
ENCLII_API_TOKEN = os.environ.get("ENCLII_API_TOKEN", "")
VAULT_NAMESPACE = os.environ.get("SELVA_VAULT_NAMESPACE", "autoswarm")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {ENCLII_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _mask(value: str) -> str:
    """Mask a secret value, showing only the last 4 characters."""
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


class VaultStoreTool(BaseTool):
    """Store a secret securely in the Selva Vault.

    Category: SECRET_WRITE — requires HITL approval.
    """

    name = "selva_vault_store"
    description = (
        "Store a secret (API key, token, password) securely in the Selva Vault. "
        "The secret is encrypted at rest and accessible only to authorized agents. "
        "Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Secret key name (e.g. 'PORKBUN_API_KEY', 'STRIPE_SECRET_KEY')",
                    "pattern": "^[A-Z][A-Z0-9_]*$",
                },
                "value": {
                    "type": "string",
                    "description": "The secret value to store",
                },
                "namespace": {
                    "type": "string",
                    "description": "K8s namespace (default: autoswarm)",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of this secret",
                },
            },
            "required": ["key", "value"],
        }

    async def execute(  # type: ignore[override]
        self,
        *,
        key: str,
        value: str,
        namespace: str | None = None,
        description: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not ENCLII_API_URL:
            return ToolResult(success=False, error="ENCLII_API_URL not configured")

        ns = namespace or VAULT_NAMESPACE
        masked = _mask(value)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}",
                    headers=_headers(),
                    json={
                        "key": key,
                        "value": value,
                        "description": description,
                    },
                )
                resp.raise_for_status()

            # NEVER log the actual value
            logger.info("Vault: stored secret %s in namespace %s", key, ns)
            return ToolResult(
                success=True,
                output=f"Stored secret {key} in {ns} (value: {masked})",
                data={"key": key, "namespace": ns, "stored": True},
            )
        except httpx.HTTPError as exc:
            logger.error("Vault store failed for %s: %s", key, exc)
            return ToolResult(success=False, error=f"Vault store failed: {exc}")


class VaultRetrieveTool(BaseTool):
    """Retrieve a secret from the Selva Vault.

    Category: SECRET_READ — requires HITL approval.
    Returns masked value in output, full value in data dict.
    """

    name = "selva_vault_retrieve"
    description = (
        "Retrieve a secret from the Selva Vault. Returns the secret value "
        "for use in other tool calls. Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Secret key name (e.g. 'PORKBUN_API_KEY')",
                },
                "namespace": {
                    "type": "string",
                    "description": "K8s namespace (default: autoswarm)",
                },
            },
            "required": ["key"],
        }

    async def execute(self, *, key: str, namespace: str | None = None, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if not ENCLII_API_URL:
            return ToolResult(success=False, error="ENCLII_API_URL not configured")

        ns = namespace or VAULT_NAMESPACE

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}/{key}",
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            value = data.get("value", "")
            masked = _mask(value)

            logger.info("Vault: retrieved secret %s from namespace %s", key, ns)
            return ToolResult(
                success=True,
                output=f"Retrieved secret {key} from {ns} (value: {masked})",
                # Full value in data dict — available to calling code but not displayed
                data={"key": key, "namespace": ns, "value": value},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ToolResult(success=False, error=f"Secret {key} not found in {ns}")
            return ToolResult(success=False, error=f"Vault retrieve failed: {exc}")
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Vault retrieve failed: {exc}")


class VaultListTool(BaseTool):
    """List all secret keys in a vault namespace (values are never exposed)."""

    name = "selva_vault_list"
    description = (
        "List all secret key names in a vault namespace. "
        "Only key names are returned, never values. Safe to call."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "K8s namespace (default: autoswarm)",
                },
            },
            "required": [],
        }

    async def execute(self, *, namespace: str | None = None, **kwargs: Any) -> ToolResult:
        if not ENCLII_API_URL:
            return ToolResult(success=False, error="ENCLII_API_URL not configured")

        ns = namespace or VAULT_NAMESPACE

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}",
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            keys = data.get("keys", [])
            output = f"Secrets in {ns}: {len(keys)}\n" + "\n".join(f"  - {k}" for k in keys)
            return ToolResult(
                success=True,
                output=output,
                data={"namespace": ns, "keys": keys, "count": len(keys)},
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Vault list failed: {exc}")


class VaultDeleteTool(BaseTool):
    """Delete a secret from the Selva Vault.

    Category: SECRET_WRITE — requires HITL approval.
    """

    name = "selva_vault_delete"
    description = "Delete a secret from the Selva Vault. Requires approval. Irreversible."

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Secret key name to delete",
                },
                "namespace": {
                    "type": "string",
                    "description": "K8s namespace (default: autoswarm)",
                },
            },
            "required": ["key"],
        }

    async def execute(self, *, key: str, namespace: str | None = None, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if not ENCLII_API_URL:
            return ToolResult(success=False, error="ENCLII_API_URL not configured")

        ns = namespace or VAULT_NAMESPACE

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}/{key}",
                    headers=_headers(),
                )
                resp.raise_for_status()

            logger.info("Vault: deleted secret %s from namespace %s", key, ns)
            return ToolResult(
                success=True,
                output=f"Deleted secret {key} from {ns}",
                data={"key": key, "namespace": ns, "deleted": True},
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Vault delete failed: {exc}")


class VaultRotateTool(BaseTool):
    """Rotate a secret — store new value and return the old one for cleanup.

    Category: SECRET_WRITE — requires HITL approval.
    """

    name = "selva_vault_rotate"
    description = (
        "Rotate a secret: read current value, store new value, return old value "
        "for cleanup (e.g., revoking old API keys). Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Secret key name to rotate",
                },
                "new_value": {
                    "type": "string",
                    "description": "The new secret value",
                },
                "namespace": {
                    "type": "string",
                    "description": "K8s namespace (default: autoswarm)",
                },
            },
            "required": ["key", "new_value"],
        }

    async def execute(  # type: ignore[override]
        self,
        *,
        key: str,
        new_value: str,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not ENCLII_API_URL:
            return ToolResult(success=False, error="ENCLII_API_URL not configured")

        ns = namespace or VAULT_NAMESPACE

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Read old value
                old_resp = await client.get(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}/{key}",
                    headers=_headers(),
                )
                old_value = ""
                if old_resp.status_code == 200:
                    old_value = old_resp.json().get("value", "")

                # Store new value
                store_resp = await client.post(
                    f"{ENCLII_API_URL}/v1/secrets/{ns}",
                    headers=_headers(),
                    json={"key": key, "value": new_value},
                )
                store_resp.raise_for_status()

            masked_old = _mask(old_value) if old_value else "(none)"
            masked_new = _mask(new_value)
            logger.info("Vault: rotated secret %s in namespace %s", key, ns)

            return ToolResult(
                success=True,
                output=f"Rotated {key} in {ns}: old={masked_old} → new={masked_new}",
                data={
                    "key": key,
                    "namespace": ns,
                    "old_value": old_value,
                    "rotated": True,
                },
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Vault rotate failed: {exc}")


def get_vault_tools() -> list[BaseTool]:
    """Return all Selva Vault tools for registration in the tool registry."""
    return [
        VaultStoreTool(),
        VaultRetrieveTool(),
        VaultListTool(),
        VaultDeleteTool(),
        VaultRotateTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    VaultStoreTool,
    VaultRetrieveTool,
    VaultListTool,
    VaultDeleteTool,
    VaultRotateTool,
):
    _cls.audience = Audience.PLATFORM
