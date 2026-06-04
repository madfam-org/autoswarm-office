"""
Track B4: process_registry — background process management.
Mirrors Hermes' tools/process_registry.py.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import shlex
import time
from typing import Any

from .audience import Audience
from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Module-level process store: name -> {proc, command, started_at}
_PROCESSES: dict[str, dict] = {}
_FORBIDDEN_COMMAND_CHARS = {";", "&", "|", "<", ">", "`", "$", "\n", "\r"}


def _split_command(command: str) -> list[str]:
    if any(ch in command for ch in _FORBIDDEN_COMMAND_CHARS):
        raise ValueError("Shell metacharacters are not allowed for background commands.")
    parts = shlex.split(command)
    if not parts:
        raise ValueError("Empty command")
    return parts


def _collect_zombies() -> None:
    """Reap terminated processes from the registry."""
    dead = [name for name, info in _PROCESSES.items() if info["proc"].poll() is not None]
    for name in dead:
        del _PROCESSES[name]


class StartBackgroundProcessTool(BaseTool):
    name = "start_background_process"
    description = "Start a shell command as a persistent background process."
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "name": {"type": "string", "description": "Friendly name for the process"},
                "cwd": {"type": "string", "description": "Working directory"},
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs["command"]
        name: str = kwargs.get("name") or f"proc_{len(_PROCESSES) + 1}"
        cwd: str | None = kwargs.get("cwd")
        try:
            command_parts = _split_command(command)
            proc = subprocess.Popen(
                command_parts,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _PROCESSES[name] = {"proc": proc, "command": command, "started_at": time.time()}
            return ToolResult(
                output=f"Process '{name}' started (pid={proc.pid}).",
                data={"pid": proc.pid, "name": name},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class ListBackgroundProcessesTool(BaseTool):
    name = "list_background_processes"
    description = "List all registered background processes and their status."

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        _collect_zombies()
        processes = []
        for name, info in _PROCESSES.items():
            rc = info["proc"].poll()
            processes.append(
                {
                    "name": name,
                    "pid": info["proc"].pid,
                    "command": info["command"],
                    "status": "running" if rc is None else f"exited({rc})",
                    "runtime_s": round(time.time() - info["started_at"]),
                }
            )
        if not processes:
            return ToolResult(output="No background processes running.", data={"processes": []})
        lines = [
            f"{p['name']} (pid={p['pid']}) [{p['status']}] — {p['command'][:60]}" for p in processes
        ]
        return ToolResult(output="\n".join(lines), data={"processes": processes})


class KillBackgroundProcessTool(BaseTool):
    name = "kill_background_process"
    description = "Terminate a background process by name or PID."
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name_or_pid": {"type": "string", "description": "Process name or PID"},
            },
            "required": ["name_or_pid"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        target = str(kwargs.get("name_or_pid", ""))
        # Try by name first
        info = _PROCESSES.get(target)
        if info is None:
            # Try by PID
            try:
                pid = int(target)
                info = next((v for v in _PROCESSES.values() if v["proc"].pid == pid), None)
            except ValueError:
                info = None
        if info is None:
            return ToolResult(success=False, error=f"No process found: {target}")
        try:
            info["proc"].send_signal(signal.SIGTERM)
            name = next(k for k, v in _PROCESSES.items() if v is info)
            del _PROCESSES[name]
            return ToolResult(output=f"Process '{name}' (pid={info['proc'].pid}) terminated.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
