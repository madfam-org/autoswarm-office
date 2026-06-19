"""Tool registry — singleton for discovering, registering, and retrieving tools."""

from __future__ import annotations

import logging
from typing import Any

from .audience import Audience, can_access
from .base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry for all available tools.

    Supports manual registration, auto-discovery from built-in modules,
    and generating OpenAI function-calling specs for a subset of tools.
    """

    _instance: ToolRegistry | None = None

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._initialized = False

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.debug("Overwriting tool '%s' in registry", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, audience: Audience | None = None) -> list[str]:
        """List registered tool names, optionally filtered by audience.

        If ``audience`` is None, returns every registered tool (backward
        compat with early callers). If set, returns only tools whose
        ``audience`` is accessible to the requested swarm audience —
        PLATFORM sees all, TENANT sees only TENANT-tagged.
        """
        if audience is None:
            return sorted(self._tools.keys())
        return sorted(
            name for name, tool in self._tools.items() if can_access(tool.audience, audience)
        )

    def get_specs(
        self,
        tool_names: list[str] | None = None,
        *,
        audience: Audience | None = None,
    ) -> list[dict[str, Any]]:
        """Generate OpenAI function-calling specs for the given tools.

        If ``tool_names`` is None, returns specs for all registered tools.
        If ``audience`` is set, platform-only tools are filtered out for
        tenant audiences (and for unknown ``tool_names``, those are
        already dropped silently — this just adds an audience gate on
        the matched tools). PLATFORM audience sees everything; TENANT
        sees only TENANT-tagged tools.
        """
        if tool_names is None:
            tools = list(self._tools.values())
        else:
            tools = [self._tools[n] for n in tool_names if n in self._tools]
        if audience is not None:
            tools = [t for t in tools if can_access(t.audience, audience)]
        return [t.to_openai_spec() for t in tools]

    def discover_builtins(self) -> None:
        """Auto-discover and register all built-in tools."""
        if self._initialized:
            return
        self._initialized = True

        from .builtins import get_builtin_tools

        for tool in get_builtin_tools():
            self.register(tool)

        self._discover_coupler_tools()

        logger.info("Registered %d built-in tools", len(self._tools))

    def _discover_coupler_tools(self) -> None:
        """Register Coupler proxy tools when feature flag is enabled."""
        try:
            from .backends.coupler import CouplerProxyTool, CouplerToolBackend, coupler_enabled

            if not coupler_enabled():
                return
            backend = CouplerToolBackend()
            import asyncio

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            catalog = loop.run_until_complete(backend.list_tools())
            for meta in catalog:
                self.register(CouplerProxyTool(backend, meta))
            logger.info("Registered %d Coupler proxy tools", len(catalog))
        except Exception as exc:
            logger.warning("Coupler tool discovery skipped: %s", exc)


def get_tool_registry() -> ToolRegistry:
    """Get the singleton tool registry, auto-discovering builtins on first call."""
    registry = ToolRegistry.get_instance()
    registry.discover_builtins()
    return registry
