# Plugin Development Guide

This guide documents how to write, register, and publish an Selva plugin. Plugins extend the platform without touching core code — you can add new tools, inject context into any ACP phase, and react to lifecycle events.

---

## What Plugins Can Do

| Capability | How |
|---|---|
| Register new tools | `register_tools()` → list of tool dicts |
| Inject context into any phase | `get_context_addenda(phase)` → list of strings |
| React to lifecycle events | Register callables in `self.hooks` |

---

## Plugin Discovery

Selva discovers plugins from three sources, in priority order:

1. **`~/.selva/plugins/`** — user-global plugins (available across all projects)
2. **`.selva/plugins/`** — project-local plugins (scoped to this workspace)
3. **pip entry points** under the group `selva.plugins` (installable packages)

---

## Plugin Structure

```
.selva/plugins/
└── my-plugin/
    ├── plugin.yaml      # Manifest (required)
    └── plugin.py        # Python implementation (required)
```

### `plugin.yaml`

```yaml
name: my-plugin
version: "1.0.0"
entrypoint: plugin.py
class: MyPlugin
```

### `plugin.py`

```python
from selva_plugins.plugin_base import SelvaPlugin, HookType

class MyPlugin(SelvaPlugin):

    def setup(self):
        # Register hooks here
        self.hooks[HookType.PRE_PHASE] = self._on_pre_phase

    def register_tools(self) -> list[dict]:
        return [
            {
                "name": "my_custom_tool",
                "description": "Performs a custom action.",
                "parameters": {"url": {"type": "string", "description": "Target URL"}},
            }
        ]

    def get_context_addenda(self, phase: str) -> list[str]:
        if phase == "phase_i_analyst":
            return ["## Company Conventions\nAlways prefer TypeScript over JavaScript."]
        return []

    def _on_pre_phase(self, **kwargs):
        print(f"PRE_PHASE fired for phase={kwargs.get('phase')}")
```

---

## Available Hook Types

| Hook | When it fires |
|---|---|
| `HookType.PRE_PHASE` | Before any ACP phase begins |
| `HookType.POST_PHASE` | After any ACP phase completes |
| `HookType.ON_SKILL_LOAD` | When a skill is loaded from the registry |
| `HookType.ON_MEMORY_INSERT` | When a transcript row is inserted into EdgeMemoryDB |
| `HookType.ON_GATEWAY_MESSAGE` | When a message arrives on any gateway platform |

---

## Publishing a pip-Installable Plugin

To make your plugin installable via pip, add this to your `pyproject.toml`:

```toml
[project.entry-points."selva.plugins"]
my-plugin = "my_package:MyPlugin"
```

Then publish to PyPI: `python -m build && twine upload dist/*`

Users install and enable it with: `pip install selva-plugin-my-plugin`

---

## Testing Your Plugin

Selva's test suite uses `pytest` with the `tmp_path` fixture. See `tests/e2e/test_plugin_manager.py` for a full example.

```bash
pytest tests/e2e/test_plugin_manager.py -v
```
