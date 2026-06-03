"""MCP client — discovers tools from MCP servers and wraps them as BaseTool instances."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class McpToolAdapter(BaseTool):
    """Wraps a remote MCP tool as a BaseTool for the registry.

    Created by the MCP discovery process when connecting to an MCP server.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        transport: McpTransport,
    ) -> None:
        self.name = tool_name
        self.description = tool_description
        self._input_schema = input_schema
        self._transport = transport

    def parameters_schema(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._transport.call_tool(self.name, kwargs)
            if isinstance(result, dict):
                content = result.get("content", "")
                if isinstance(content, list):
                    text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return ToolResult(output="\n".join(text_parts), data=result)
                return ToolResult(output=str(content), data=result)
            return ToolResult(output=str(result))
        except Exception as exc:
            logger.error("MCP tool '%s' execution failed: %s", self.name, exc)
            return ToolResult(success=False, error=str(exc))


class McpTransport:
    """Base class for MCP transport implementations."""

    async def initialize(self) -> dict[str, Any]:
        """Initialize the MCP session."""
        raise NotImplementedError

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        raise NotImplementedError

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the transport connection."""


class StdioMcpTransport(McpTransport):
    """MCP transport via subprocess stdin/stdout JSON-RPC."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        self._command = command
        self._env = env
        self._process: Any = None
        self._request_id = 0

    async def initialize(self) -> dict[str, Any]:
        import asyncio

        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

        # Send initialize request
        return await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "selva", "version": "0.1.0"},
            },
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    async def close(self) -> None:
        if self._process:
            self._process.terminate()
            await self._process.wait()

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            msg = "MCP process not started"
            raise RuntimeError(msg)

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        self._process.stdin.write((json.dumps(request) + "\n").encode())
        await self._process.stdin.drain()

        line = await self._process.stdout.readline()
        response = json.loads(line.decode())

        if "error" in response:
            msg = f"MCP error: {response['error']}"
            raise RuntimeError(msg)

        return response.get("result", {})


class HttpMcpTransport(McpTransport):
    """MCP transport via HTTP/SSE for remote MCP servers."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self._url = url.rstrip("/")
        self._headers = headers or {}

    async def initialize(self) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._url}/initialize",
                json={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "selva", "version": "0.1.0"},
                },
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_tools(self) -> list[dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._url}/tools/list",
                json={},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._url}/tools/call",
                json={"name": name, "arguments": arguments},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()


async def discover_mcp_tools(transport: McpTransport) -> list[McpToolAdapter]:
    """Connect to an MCP server and wrap its tools as BaseTool instances."""
    await transport.initialize()
    tools_list = await transport.list_tools()

    adapters: list[McpToolAdapter] = []
    for tool_def in tools_list:
        adapter = McpToolAdapter(
            tool_name=tool_def.get("name", ""),
            tool_description=tool_def.get("description", ""),
            input_schema=tool_def.get("inputSchema", {}),
            transport=transport,
        )
        adapters.append(adapter)
        logger.info("Discovered MCP tool: %s", adapter.name)

    return adapters
