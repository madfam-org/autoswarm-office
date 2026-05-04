"""
Gap 3: AutoSwarm Plugin Architecture

PluginManager — discovers and loads plugins from three sources:
  1. ~/.autoswarm/plugins/  — user-global plugins
  2. .autoswarm/plugins/    — project-local plugins (highest priority)
  3. pip entry_points under group 'autoswarm.plugins'

Each plugin declares tools, hooks, and context addenda via a plugin.yaml
manifest and a Python class extending AutoSwarmPlugin.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
from pathlib import Path
from typing import Any

import yaml

from .plugin_base import AutoSwarmPlugin, HookType

logger = logging.getLogger(__name__)

_GLOBAL_PLUGIN_DIR = Path.home() / ".autoswarm" / "plugins"
_PROJECT_PLUGIN_DIR = Path(".autoswarm") / "plugins"


class PluginManager:
    """
    Discovers, loads, and coordinates AutoSwarm plugins.

    Usage:
        manager = PluginManager()
        manager.discover()
        tools = manager.get_all_tools()
        context = manager.get_context_addenda("phase_i_analyst")
    """

    def __init__(self, extra_dirs: list[str] | None = None) -> None:
        self._plugins: list[AutoSwarmPlugin] = []
        self._extra_dirs = [Path(d) for d in (extra_dirs or [])]

    def discover(self) -> int:
        """
        Run full discovery across all three sources.
        Returns: Number of plugins loaded.
        """
        dirs = [_GLOBAL_PLUGIN_DIR, _PROJECT_PLUGIN_DIR] + self._extra_dirs
        for d in dirs:
            if d.exists():
                self._load_from_dir(d)
        self._load_from_entry_points()
        logger.info("PluginManager: loaded %d plugin(s).", len(self._plugins))
        return len(self._plugins)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return all tool definitions declared by all loaded plugins."""
        tools: list[dict[str, Any]] = []
        for plugin in self._plugins:
            try:
                tools.extend(plugin.register_tools())
            except Exception as exc:
                logger.warning("Plugin %s.register_tools() failed: %s", plugin.name, exc)
        return tools

    # ------------------------------------------------------------------
    # Hook dispatch
    # ------------------------------------------------------------------

    def dispatch_hook(self, hook: HookType, **kwargs: Any) -> list[Any]:
        """Dispatch *hook* to all plugins that handle it. Returns list of results."""
        results: list[Any] = []
        for plugin in self._plugins:
            handler = plugin.hooks.get(hook)
            if handler:
                try:
                    results.append(handler(**kwargs))
                except Exception as exc:
                    logger.warning("Plugin %s hook %s failed: %s", plugin.name, hook, exc)
        return results

    # ------------------------------------------------------------------
    # Context addenda
    # ------------------------------------------------------------------

    def get_context_addenda(self, phase: str) -> list[str]:
        """Return context strings contributed by plugins for *phase*."""
        addenda: list[str] = []
        for plugin in self._plugins:
            try:
                addenda.extend(plugin.get_context_addenda(phase))
            except Exception as exc:
                logger.warning("Plugin %s.get_context_addenda() failed: %s", plugin.name, exc)
        return addenda

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def _load_from_dir(self, directory: Path) -> None:
        """Scan *directory* for plugin.yaml manifests and load each plugin."""
        for manifest_path in directory.glob("*/plugin.yaml"):
            try:
                self._load_plugin_from_manifest(manifest_path)
            except Exception as exc:
                logger.warning("Failed to load plugin from %s: %s", manifest_path, exc)

    def _load_plugin_from_manifest(self, manifest_path: Path) -> None:
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)

        plugin_dir = manifest_path.parent
        entrypoint = manifest.get("entrypoint", "plugin.py")
        class_name = manifest.get("class", "Plugin")

        # Dynamically load the plugin module
        spec = importlib.util.spec_from_file_location(
            f"autoswarm_plugin_{plugin_dir.name}",
            plugin_dir / entrypoint,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Could not build module spec for plugin at {plugin_dir / entrypoint}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin_class = getattr(module, class_name)

        plugin: AutoSwarmPlugin = plugin_class(manifest=manifest)
        plugin.setup()
        self._plugins.append(plugin)
        logger.info("PluginManager: loaded plugin '%s' from %s.", plugin.name, plugin_dir)

    def _load_from_entry_points(self) -> None:
        """Load plugins registered via pip entry_points 'autoswarm.plugins'."""
        try:
            eps = importlib.metadata.entry_points(group="autoswarm.plugins")
        except Exception:
            return

        for ep in eps:
            try:
                plugin_class = ep.load()
                plugin: AutoSwarmPlugin = plugin_class(manifest={"name": ep.name})
                plugin.setup()
                self._plugins.append(plugin)
                logger.info("PluginManager: loaded pip plugin '%s'.", ep.name)
            except Exception as exc:
                logger.warning("Failed to load pip plugin %s: %s", ep.name, exc)

    @property
    def loaded_count(self) -> int:
        return len(self._plugins)
