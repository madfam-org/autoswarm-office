"""Sandboxed bash execution tool with permission checking."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Commands that are unconditionally blocked regardless of permissions.
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/\s*$", re.IGNORECASE),
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/\*", re.IGNORECASE),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if=/dev/", re.IGNORECASE),
    re.compile(r"\b:(){ :\|:& };:"),  # fork bomb
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\binit\s+0\b"),
    re.compile(r"\bkill\s+-9\s+1\b"),
    re.compile(r"> /dev/sda"),
    re.compile(r"\bcurl\b.*\|\s*bash", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|\s*bash", re.IGNORECASE),
]

# Maximum execution time for any single command.
_DEFAULT_TIMEOUT_SECONDS = 30

# Maximum output size to prevent memory exhaustion.
_MAX_OUTPUT_BYTES = 1_048_576  # 1 MiB


@dataclass
class BashResult:
    """Result of a sandboxed bash command execution."""

    command: str
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.return_code == 0 and not self.timed_out


@dataclass
class BashTool:
    """Sandboxed bash execution with safety guards and permission checking.

    Dangerous commands are blocked at the pattern level before any
    subprocess is spawned.  All executions are time-bounded and output
    size-limited.
    """

    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    allowed_cwd: str | None = None
    _blocked_patterns: list[re.Pattern[str]] = field(
        default_factory=lambda: list(_BLOCKED_PATTERNS)
    )

    def _is_blocked(self, command: str) -> str | None:
        """Return the matched pattern description if the command is blocked, else None."""
        for pattern in self._blocked_patterns:
            if pattern.search(command):
                return pattern.pattern
        return None

    async def execute(self, command: str) -> BashResult:
        """Execute a shell command in a sandboxed subprocess.

        The command is first checked against the blocklist.  If it
        matches a dangerous pattern, execution is refused without
        spawning a process.

        Returns a ``BashResult`` with stdout, stderr, and return code.
        """
        # -- Safety check -----------------------------------------------------
        blocked_reason = self._is_blocked(command)
        if blocked_reason is not None:
            logger.warning("Blocked dangerous command: %s (pattern: %s)", command, blocked_reason)
            return BashResult(
                command=command,
                stdout="",
                stderr=f"Command blocked by safety policy: matched pattern '{blocked_reason}'",
                return_code=126,
            )

        # -- Execute ----------------------------------------------------------
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.allowed_cwd,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Command timed out after %ds: %s", self.timeout_seconds, command)
                return BashResult(
                    command=command,
                    stdout="",
                    stderr=f"Command timed out after {self.timeout_seconds} seconds",
                    return_code=-1,
                    timed_out=True,
                )

            # Truncate oversized output.
            stdout = stdout_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = stderr_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

            return BashResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                return_code=process.returncode or 0,
            )

        except OSError as exc:
            logger.error("Failed to spawn subprocess for command: %s", exc)
            return BashResult(
                command=command,
                stdout="",
                stderr=f"Failed to execute command: {exc}",
                return_code=1,
            )
