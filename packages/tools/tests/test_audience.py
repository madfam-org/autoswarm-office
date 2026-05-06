"""Tests for the tool-audience split.

Covers:
- Default ``BaseTool.audience`` is TENANT
- ``can_access`` semantics: platform sees all, tenant sees only tenant
- Registry ``get_specs(audience=...)`` filters platform tools for tenant
- Registry ``list_tools(audience=...)`` filter behavior
- ``with_audience`` ContextVar binding + reset
- ``enforce_audience`` raises ``AudienceMismatch`` when the current
  bound audience can't access a platform tool
- Backward compat: calling ``get_specs()`` without ``audience`` returns
  all tools (no filter) and existing callers are unaffected
"""

from __future__ import annotations

from typing import Any

import pytest

# Enable enforcement for all tests in this module.
pytestmark = pytest.mark.usefixtures("_audience_enforce_on")


@pytest.fixture
def _audience_enforce_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIENCE_FILTER_ENABLED", "true")


from selva_tools import (  # noqa: E402
    Audience,
    AudienceMismatch,
    BaseTool,
    ToolRegistry,
    ToolResult,
    can_access,
    enforce_audience,
    get_current_audience,
    with_audience,
)


class _FakeTenantTool(BaseTool):
    name = "fake_tenant_read"
    description = "A fake tenant-safe tool for testing."
    audience = Audience.TENANT

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="ok")


class _FakePlatformTool(BaseTool):
    name = "fake_platform_mutate"
    description = "A fake platform-only tool for testing."
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        enforce_audience(self.audience)
        return ToolResult(success=True, output="mutated")


class _FakeDefaultTool(BaseTool):
    """No explicit audience — verifies the default."""

    name = "fake_default"
    description = "A fake tool that doesn't set audience."

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True)


# ---------------------------------------------------------------------------
# Audience + can_access semantics
# ---------------------------------------------------------------------------


class TestCanAccess:
    def test_platform_swarm_sees_platform_tools(self) -> None:
        assert can_access(Audience.PLATFORM, Audience.PLATFORM)

    def test_platform_swarm_sees_tenant_tools(self) -> None:
        assert can_access(Audience.TENANT, Audience.PLATFORM)

    def test_tenant_swarm_sees_tenant_tools(self) -> None:
        assert can_access(Audience.TENANT, Audience.TENANT)

    def test_tenant_swarm_does_not_see_platform_tools(self) -> None:
        assert not can_access(Audience.PLATFORM, Audience.TENANT)

    def test_unbound_audience_fails_closed_for_platform_tools(self) -> None:
        # Enforcement-on mode mirrors production: platform mutation tools
        # require an explicit platform binding.
        assert not can_access(Audience.PLATFORM, None)
        assert can_access(Audience.TENANT, None)


class TestBaseToolDefaults:
    def test_default_audience_is_tenant(self) -> None:
        assert _FakeDefaultTool.audience is Audience.TENANT
        assert _FakeDefaultTool().audience is Audience.TENANT

    def test_explicit_platform_audience(self) -> None:
        assert _FakePlatformTool().audience is Audience.PLATFORM


# ---------------------------------------------------------------------------
# ContextVar binding + enforce_audience
# ---------------------------------------------------------------------------


class TestWithAudience:
    def test_unbound_by_default(self) -> None:
        assert get_current_audience() is None

    def test_bind_and_restore(self) -> None:
        assert get_current_audience() is None
        with with_audience(Audience.TENANT):
            assert get_current_audience() is Audience.TENANT
        assert get_current_audience() is None

    def test_nested_bindings(self) -> None:
        with with_audience(Audience.PLATFORM):
            assert get_current_audience() is Audience.PLATFORM
            with with_audience(Audience.TENANT):
                assert get_current_audience() is Audience.TENANT
            assert get_current_audience() is Audience.PLATFORM


@pytest.mark.asyncio
class TestEnforceAudience:
    async def test_platform_tool_in_platform_context_ok(self) -> None:
        with with_audience(Audience.PLATFORM):
            res = await _FakePlatformTool().execute()
        assert res.success is True

    async def test_platform_tool_in_tenant_context_raises(self) -> None:
        with with_audience(Audience.TENANT):
            with pytest.raises(AudienceMismatch):
                await _FakePlatformTool().execute()

    async def test_platform_tool_unbound_raises_when_enforced(self) -> None:
        # No with_audience block in enforcement-on mode must fail closed.
        with pytest.raises(AudienceMismatch):
            await _FakePlatformTool().execute()


# ---------------------------------------------------------------------------
# Registry filter
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(_FakeTenantTool())
    r.register(_FakePlatformTool())
    r.register(_FakeDefaultTool())
    return r


class TestRegistryFilter:
    def test_list_tools_unfiltered(self, registry: ToolRegistry) -> None:
        names = registry.list_tools()
        assert "fake_tenant_read" in names
        assert "fake_platform_mutate" in names
        assert "fake_default" in names

    def test_list_tools_tenant_audience_hides_platform(self, registry: ToolRegistry) -> None:
        names = registry.list_tools(audience=Audience.TENANT)
        assert "fake_tenant_read" in names
        assert "fake_default" in names
        assert "fake_platform_mutate" not in names

    def test_list_tools_platform_audience_sees_all(self, registry: ToolRegistry) -> None:
        names = registry.list_tools(audience=Audience.PLATFORM)
        assert set(names) == {
            "fake_tenant_read",
            "fake_platform_mutate",
            "fake_default",
        }

    def test_get_specs_unfiltered_returns_all(self, registry: ToolRegistry) -> None:
        specs = registry.get_specs()
        names = {s["function"]["name"] for s in specs}
        assert names == {
            "fake_tenant_read",
            "fake_platform_mutate",
            "fake_default",
        }

    def test_get_specs_tenant_audience_hides_platform(self, registry: ToolRegistry) -> None:
        specs = registry.get_specs(audience=Audience.TENANT)
        names = {s["function"]["name"] for s in specs}
        assert names == {"fake_tenant_read", "fake_default"}

    def test_get_specs_platform_audience_sees_all(self, registry: ToolRegistry) -> None:
        specs = registry.get_specs(audience=Audience.PLATFORM)
        names = {s["function"]["name"] for s in specs}
        assert names == {
            "fake_tenant_read",
            "fake_platform_mutate",
            "fake_default",
        }

    def test_get_specs_named_list_still_audience_filtered(self, registry: ToolRegistry) -> None:
        # Even when the caller names the platform tool explicitly, the
        # audience filter drops it for a tenant swarm.
        specs = registry.get_specs(
            tool_names=["fake_tenant_read", "fake_platform_mutate"],
            audience=Audience.TENANT,
        )
        names = {s["function"]["name"] for s in specs}
        assert names == {"fake_tenant_read"}

    def test_get_specs_backward_compat_no_audience_arg(self, registry: ToolRegistry) -> None:
        # Existing callers that don't pass audience get every tool
        # (same behavior as before this PR).
        specs = registry.get_specs(tool_names=["fake_tenant_read", "fake_platform_mutate"])
        names = {s["function"]["name"] for s in specs}
        assert names == {"fake_tenant_read", "fake_platform_mutate"}
