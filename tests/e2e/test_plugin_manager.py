"""
E2E tests — Gap 3: Plugin Architecture
"""

from pathlib import Path

MINIMAL_PLUGIN_PY = """
from selva_plugins.plugin_base import SelvaPlugin, HookType

class Plugin(SelvaPlugin):
    def setup(self):
        self.hooks[HookType.PRE_PHASE] = self._pre_phase_hook

    def register_tools(self):
        return [{"name": "test_tool", "description": "A tool from the test plugin"}]

    def get_context_addenda(self, phase: str):
        if phase == "phase_i_analyst":
            return ["## TestPlugin Context\\nThis is injected by the test plugin."]
        return []

    def _pre_phase_hook(self, **kwargs):
        return {"hook_fired": True, "phase": kwargs.get("phase")}
"""

MINIMAL_PLUGIN_YAML = """
name: test-plugin
version: "1.0.0"
entrypoint: plugin.py
class: Plugin
"""


class TestPluginManager:
    def _create_plugin_dir(self, tmp_path: Path) -> Path:
        plugin_dir = tmp_path / "test-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(MINIMAL_PLUGIN_PY)
        (plugin_dir / "plugin.yaml").write_text(MINIMAL_PLUGIN_YAML)
        return tmp_path

    def test_discover_from_project_dir(self, tmp_path):
        """Plugin in .selva/plugins/ is discovered and loaded."""
        plugin_root = self._create_plugin_dir(tmp_path)

        from selva_plugins.manager import PluginManager

        manager = PluginManager(extra_dirs=[str(plugin_root)])
        count = manager.discover()
        assert count == 1

    def test_register_tools_returns_tool(self, tmp_path):
        """Plugin's tool is returned by get_all_tools()."""
        plugin_root = self._create_plugin_dir(tmp_path)
        from selva_plugins.manager import PluginManager

        manager = PluginManager(extra_dirs=[str(plugin_root)])
        manager.discover()
        tools = manager.get_all_tools()
        assert any(t["name"] == "test_tool" for t in tools)

    def test_context_addenda_injected_for_phase(self, tmp_path):
        """Context addenda from plugin are returned for the correct phase."""
        plugin_root = self._create_plugin_dir(tmp_path)
        from selva_plugins.manager import PluginManager

        manager = PluginManager(extra_dirs=[str(plugin_root)])
        manager.discover()
        addenda = manager.get_context_addenda("phase_i_analyst")
        assert any("TestPlugin" in a for a in addenda)

    def test_hook_fires_at_declared_phase(self, tmp_path):
        """PRE_PHASE hook fires and returns result."""
        plugin_root = self._create_plugin_dir(tmp_path)
        from selva_plugins.manager import PluginManager
        from selva_plugins.plugin_base import HookType

        manager = PluginManager(extra_dirs=[str(plugin_root)])
        manager.discover()
        results = manager.dispatch_hook(HookType.PRE_PHASE, phase="phase_i_analyst")
        assert any(r and r.get("hook_fired") for r in results)

    def test_empty_dir_loads_zero_plugins(self, tmp_path):
        """No plugins found in an empty directory."""
        from selva_plugins.manager import PluginManager

        manager = PluginManager(extra_dirs=[str(tmp_path)])
        count = manager.discover()
        assert count == 0
