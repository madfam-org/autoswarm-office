"""Coupler Agent Tool Plane backend for Selva."""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Set by worker/graph when executing on behalf of a user.
coupler_user_jwt: ContextVar[str | None] = ContextVar("coupler_user_jwt", default=None)


def set_coupler_user_jwt(token: str | None) -> None:
    coupler_user_jwt.set(token)


def get_coupler_user_jwt() -> str | None:
    return coupler_user_jwt.get()


class CouplerToolBackend:
    """HTTP client for Coupler gateway tool catalog and execute."""

    def __init__(self, base_url: str | None = None, audience: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("COUPLER_BASE_URL", "http://localhost:8787")).rstrip("/")
        self.audience = audience or os.environ.get("COUPLER_AUDIENCE", "coupler-api")

    async def list_tools(self, *, user_jwt: str | None = None) -> list[dict[str, Any]]:
        headers = _auth_headers(user_jwt)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.base_url}/v1/tools", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return list(data.get("tools", []))

    async def search_tools(self, query: str, *, user_jwt: str | None = None) -> list[dict[str, Any]]:
        headers = _auth_headers(user_jwt)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/v1/tools/search",
                params={"q": query},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return list(data.get("tools", []))

    async def execute_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        user_jwt: str | None = None,
        connection_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        headers = {**_auth_headers(user_jwt), "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "tool": tool_id,
            "arguments": arguments,
            "dry_run": dry_run,
        }
        if connection_id:
            payload["connection_id"] = connection_id

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{self.base_url}/v1/tools/execute", json=payload, headers=headers)
            if resp.status_code >= 400:
                return {"error": resp.text, "status": resp.status_code, "tool": tool_id}
            return resp.json()


class CouplerProxyTool(BaseTool):
    """Registry adapter — one Coupler catalog tool as a Selva BaseTool."""

    audience = Audience.TENANT

    def __init__(self, backend: CouplerToolBackend, tool_meta: dict[str, Any]) -> None:
        self._backend = backend
        self.name = tool_meta["name"]
        self.description = tool_meta.get("description", "")
        self._schema = tool_meta.get("parameters") or {"type": "object", "properties": {}}

    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_jwt = kwargs.pop("_user_jwt", None) or get_coupler_user_jwt()
        connection_id = kwargs.pop("_connection_id", None)
        dry_run = bool(kwargs.pop("dry_run", False))

        if not dry_run and not user_jwt:
            return ToolResult(
                success=False,
                error="user_jwt_required",
                output="Coupler execute requires end-user Janua JWT in execution context",
            )

        result = await self._backend.execute_tool(
            self.name,
            kwargs,
            user_jwt=user_jwt,
            connection_id=connection_id,
            dry_run=dry_run,
        )
        if result.get("error"):
            return ToolResult(
                success=False,
                error=str(result.get("error")),
                output=result.get("message", ""),
                data=result,
            )
        return ToolResult(
            success=True,
            output=result.get("message", f"Executed {self.name}"),
            data=result,
        )


def coupler_enabled() -> bool:
    return os.environ.get("SELVA_COUPLER_TOOLS_ENABLED", "false").lower() in ("1", "true", "yes")


def _auth_headers(user_jwt: str | None) -> dict[str, str]:
    if user_jwt:
        return {"Authorization": f"Bearer {user_jwt}"}
    return {}
