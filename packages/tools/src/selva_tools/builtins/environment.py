"""Environment tools: system info and package management."""

from __future__ import annotations

import os
import platform
import sys
from typing import Any

from ..base import BaseTool, ToolResult


class EnvInfoTool(BaseTool):
    name = "env_info"
    description = "Get system environment information (OS, Python version, env vars)"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_env_vars": {
                    "type": "boolean",
                    "description": "Include environment variable names (not values)",
                    "default": False,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        include_env_vars = kwargs.get("include_env_vars", False)
        info: dict[str, Any] = {
            "os": platform.system(),
            "os_version": platform.version(),
            "python_version": sys.version,
            "architecture": platform.machine(),
            "cwd": os.getcwd(),
        }
        if include_env_vars:
            info["env_var_names"] = sorted(os.environ.keys())
        import json

        return ToolResult(output=json.dumps(info, indent=2), data=info)


class PackageInstallTool(BaseTool):
    name = "package_install"
    description = "Install a Python package using pip"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "Package name (e.g. 'requests')"},
                "version": {"type": "string", "description": "Version spec", "default": ""},
            },
            "required": ["package"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..sandbox import ToolSandbox

        package = kwargs.get("package", "")
        version = kwargs.get("version", "")
        spec = f"{package}=={version}" if version else package

        sandbox = ToolSandbox()
        result = await sandbox.run_command(
            f"{sys.executable} -m pip install {spec}",
            timeout=120.0,
        )
        if result["success"]:
            return ToolResult(output=f"Installed {spec}")
        return ToolResult(success=False, error=result["stderr"])
