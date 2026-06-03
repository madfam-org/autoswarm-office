"""Base tool interface and result types."""

from __future__ import annotations

import abc
import functools
from typing import Any

from pydantic import BaseModel, Field

from .audience import Audience, enforce_audience


class ToolResult(BaseModel):
    """Structured result from a tool execution."""

    success: bool = True
    output: str = ""
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class BaseTool(abc.ABC):
    """Abstract base class for all tools in the Selva tool registry.

    Each tool must define:
    - ``name``: unique identifier used in function-calling specs
    - ``description``: human-readable description for LLM context
    - ``parameters_schema()``: JSON Schema for the tool's parameters
    - ``execute(**kwargs)``: async execution method

    Optional class attribute:
    - ``audience``: ``Audience.PLATFORM`` for MADFAM-only ops (Cloudflare,
      K8s, tenant_identities, Janua admin, etc.) or ``Audience.TENANT``
      for tools a tenant swarm may use (the default). Tools that touch
      cross-tenant or platform-owned infra must be explicitly tagged
      PLATFORM — the registry's spec filter hides them from tenant
      swarms, and ``enforce_audience()`` guards at execute time.
    """

    name: str
    description: str
    audience: Audience = Audience.TENANT

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-wrap each concrete subclass's ``execute`` with an audience
        guard so tenant swarms can never invoke a platform tool at runtime.

        Runs once per subclass at class-definition time. If the subclass
        sets an explicit ``__selva_audience_enforced__ = True``, we
        still re-wrap (belt-and-braces) — the wrapper is idempotent
        via a sentinel attribute on the wrapped function.
        """
        super().__init_subclass__(**kwargs)
        execute_fn = cls.__dict__.get("execute")
        if execute_fn is None:
            return  # Intermediate base, no own execute — skip.
        if getattr(execute_fn, "_selva_audience_guarded", False):
            return  # Already wrapped (e.g. via super().__init_subclass__).

        @functools.wraps(execute_fn)
        async def _guarded(self: BaseTool, **kw: Any) -> ToolResult:
            enforce_audience(self.audience, tool_name=self.name)
            return await execute_fn(self, **kw)

        _guarded._selva_audience_guarded = True  # type: ignore[attr-defined]
        cls.execute = _guarded  # type: ignore[method-assign]

    @abc.abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """Return JSON Schema describing this tool's parameters.

        The schema follows the OpenAI function-calling format:
        ``{"type": "object", "properties": {...}, "required": [...]}``
        """

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments.

        Returns:
            A ToolResult with the output or error.
        """

    def to_openai_spec(self) -> dict[str, Any]:
        """Generate an OpenAI function-calling tool spec."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }
