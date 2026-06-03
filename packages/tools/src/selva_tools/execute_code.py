"""
Track B3: execute_code — single-call code execution sandbox with mandatory approval gate.
Mirrors Hermes' tools/code_execution_tool.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

from .base import BaseTool, ToolResult
from .sandbox import SandboxLevel, ToolSandbox

logger = logging.getLogger(__name__)

_OUTPUT_CAP = 10_240  # 10 KB combined stdout+stderr
_DEFAULT_TIMEOUT = 30.0
_SUPPORTED_LANGUAGES = {"python", "bash", "sh", "javascript", "node"}

# Patterns that require approval (subset of the approval.py catalogue)
_EXEC_DANGEROUS_PATTERNS = [
    "os.system",
    "subprocess",
    "open(",
    "open (",
    "shutil.rmtree",
    "rm -rf",
    "curl ",
    "wget ",
    "nc ",
    "netcat",
    "socket",
]


class ExecuteCodeTool(BaseTool):
    """
    Track B3: execute_code

    Runs arbitrary code in a sandboxed subprocess with:
    - Mandatory dangerous-pattern gate (calls request_approval for risky code)
    - SELVA_EXEC_POLICY=allow|block|approve controls gate behaviour
    - Language support: python, bash, javascript (node)
    - Optional dependency pre-installation (pip)
    - Hard 10 KB output cap and configurable timeout
    """

    name = "execute_code"
    description = (
        "Execute a code snippet and return its output. "
        "Supports Python, Bash, and Node.js. "
        "Dangerous operations require operator approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The code to execute"},
                "language": {
                    "type": "string",
                    "enum": list(_SUPPORTED_LANGUAGES),
                    "default": "python",
                    "description": "Programming language",
                },
                "timeout": {
                    "type": "number",
                    "default": _DEFAULT_TIMEOUT,
                    "description": "Execution timeout in seconds",
                },
                "install_deps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pip packages to install before execution (Python only)",
                },
                "run_id": {
                    "type": "string",
                    "description": "ACP run ID for approval tracking",
                    "default": "unknown",
                },
            },
            "required": ["code"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        code: str = kwargs.get("code", "")
        language: str = kwargs.get("language", "python").lower().strip()
        timeout: float = float(kwargs.get("timeout", _DEFAULT_TIMEOUT))
        install_deps: list[str] = kwargs.get("install_deps") or []
        run_id: str = kwargs.get("run_id", "unknown")

        if language not in _SUPPORTED_LANGUAGES:
            return ToolResult(
                success=False,
                error=(
                    f"Unsupported language '{language}'. Supported: {sorted(_SUPPORTED_LANGUAGES)}"
                ),
            )

        # ----------------------------------------------------------------
        # Approval gate
        # ----------------------------------------------------------------
        policy = os.environ.get("SELVA_EXEC_POLICY", "approve")
        if policy != "allow":
            dangerous_matches = [p for p in _EXEC_DANGEROUS_PATTERNS if p in code]
            if dangerous_matches:
                if policy == "block":
                    return ToolResult(
                        success=False,
                        error=(
                            f"Execution blocked: dangerous patterns detected: {dangerous_matches}"
                        ),
                    )
                # policy == 'approve' — request HITL
                try:
                    from .approval import request_approval

                    result = await request_approval(
                        code[:300],
                        run_id=run_id,
                        reason=f"Code contains: {', '.join(dangerous_matches[:3])}",
                    )
                    if not result.approved:
                        return ToolResult(
                            success=False,
                            error="Code execution denied by operator approval gate.",
                        )
                except ImportError:
                    logger.warning(
                        "execute_code: approval module not available — blocking by default.",
                    )
                    return ToolResult(success=False, error="Approval module unavailable; blocking.")

        sandbox = ToolSandbox(level=SandboxLevel.FILESYSTEM)
        start = time.monotonic()

        try:
            # Optional dep install (Python only)
            if install_deps and language in ("python",):
                deps_cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--prefix",
                    str(sandbox.workdir / "deps"),
                ] + install_deps
                proc = await asyncio.create_subprocess_exec(
                    *deps_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=60.0)

            # Write code to tempfile
            suffix = {
                "python": ".py",
                "bash": ".sh",
                "sh": ".sh",
                "javascript": ".js",
                "node": ".js",
            }[language]
            code_file = sandbox.workdir / f"snippet{suffix}"
            code_file.write_text(code, encoding="utf-8")

            # Select interpreter
            interpreter = {
                "python": [sys.executable],
                "bash": ["bash"],
                "sh": ["sh"],
                "javascript": ["node"],
                "node": ["node"],
            }[language]

            proc = await asyncio.create_subprocess_exec(
                *interpreter,
                str(code_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox.workdir),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            stdout = stdout_b.decode(errors="replace")
            stderr = stderr_b.decode(errors="replace")
            combined = stdout + stderr

            truncated = len(combined) > _OUTPUT_CAP
            if truncated:
                stdout = combined[:_OUTPUT_CAP] + "\n[... output truncated ...]"

            duration_ms = int((time.monotonic() - start) * 1000)

            return ToolResult(
                output=stdout if truncated else stdout[:_OUTPUT_CAP],
                data={
                    "stderr": stderr[:2048],
                    "return_code": proc.returncode or 0,
                    "duration_ms": duration_ms,
                    "language": language,
                },
                success=(proc.returncode or 0) == 0,
            )

        except TimeoutError:
            return ToolResult(
                success=False,
                error=f"Code execution timed out after {timeout}s",
                data={"language": language, "duration_ms": int(timeout * 1000)},
            )
        except FileNotFoundError as exc:
            return ToolResult(
                success=False,
                error=f"Interpreter not found for language '{language}': {exc}",
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        finally:
            sandbox.cleanup()
