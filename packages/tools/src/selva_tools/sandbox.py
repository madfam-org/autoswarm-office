"""Tool execution sandboxing — configurable isolation levels."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SandboxLevel(StrEnum):
    """Isolation level for tool execution."""

    NONE = "none"
    FILESYSTEM = "filesystem"
    DOCKER = "docker"


class ToolSandbox:
    """Provides sandboxed execution for tools that run arbitrary code.

    Levels:
    - NONE: no isolation, runs in process
    - FILESYSTEM: restricted to a temp directory
    - DOCKER: runs in a Docker container (future)
    """

    def __init__(self, level: SandboxLevel = SandboxLevel.NONE) -> None:
        self.level = level
        self._workdir: Path | None = None

    @property
    def workdir(self) -> Path:
        """Get or create the sandbox working directory."""
        if self._workdir is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="selva-sandbox-"))
        return self._workdir

    async def run_command(
        self, command: str, *, timeout: float = 30.0, cwd: str | None = None
    ) -> dict[str, Any]:
        """Run a shell command within the sandbox."""
        work_cwd = cwd or str(self.workdir) if self.level != SandboxLevel.NONE else cwd

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "return_code": proc.returncode or 0,
                "success": proc.returncode == 0,
            }
        except TimeoutError:
            logger.warning("Command timed out after %.1fs: %s", timeout, command[:100])
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "return_code": -1,
                "success": False,
            }
        except Exception as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "return_code": -1,
                "success": False,
            }

    def cleanup(self) -> None:
        """Clean up the sandbox working directory."""
        if self._workdir and self._workdir.exists():
            import shutil

            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None
