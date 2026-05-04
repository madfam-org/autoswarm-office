"""Postgres backup + pgBackRest operations.

During the 2026-04-18 outage, none of the pgBackRest operations had a tool
surface — agents couldn't check backup state, trigger a manual backup, or
execute a restore. This module provides the minimal set needed for DR drills
and incident recovery.

All operations run via ``kubectl exec`` into the ``pgbackrest`` sidecar of
the ``postgres`` Deployment in the ``data`` namespace. We use the same
kubernetes client library k8s_diagnostics uses.
"""

from __future__ import annotations

import logging
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _load_core_client() -> Any | None:
    try:
        from kubernetes import client, config
    except ImportError:
        return None
    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception:
            return None
    return client.CoreV1Api()


async def _exec_in_pgbackrest(
    cmd: list[str], namespace: str = "data", timeout: int = 120
) -> tuple[bool, str]:
    """Run a command in the postgres pod's pgbackrest sidecar.

    Returns (success, output_or_error).
    """
    core = _load_core_client()
    if core is None:
        return False, "kubernetes client unavailable"
    try:
        from kubernetes.stream import stream
    except ImportError:
        return False, "kubernetes.stream unavailable"
    try:
        pods = core.list_namespaced_pod(namespace=namespace, label_selector="app=postgres")
        if not pods.items:
            return False, f"no postgres pod found in namespace {namespace}"
        pod_name = pods.items[0].metadata.name
        result = stream(
            core.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            container="pgbackrest",
            command=cmd,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _request_timeout=timeout,
        )
        return True, result
    except Exception as e:
        logger.error("pgbackrest exec failed: %s", e)
        return False, str(e)


class PgbackrestInfoTool(BaseTool):
    """Show pgBackRest backup state + retention."""

    name = "pgbackrest_info"
    description = (
        "Run 'pgbackrest info' for a stanza and return the current backup "
        "set (full/diff/incr counts, repo size, last-backup timestamps). "
        "Equivalent of the sanity check at the top of any DR drill."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stanza": {"type": "string", "default": "main"},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        stanza = kwargs.get("stanza", "main")
        ns = kwargs.get("namespace", "data")
        ok, out = await _exec_in_pgbackrest(
            ["pgbackrest", "--stanza", stanza, "--output=json", "info"],
            namespace=ns,
        )
        if not ok:
            return ToolResult(success=False, error=out)
        # JSON output; keep raw + a terse summary.
        import json

        try:
            parsed = json.loads(out)
        except Exception:
            parsed = None
        summary = ""
        if isinstance(parsed, list) and parsed:
            st = parsed[0]
            backup_count = len(st.get("backup", []))
            summary = (
                f"stanza={st.get('name')} "
                f"db_count={len(st.get('db', []))} "
                f"backup_count={backup_count}"
            )
        return ToolResult(
            success=True,
            output=summary or "pgbackrest info returned data.",
            data={"raw": parsed if parsed is not None else out},
        )


class PgbackrestBackupTool(BaseTool):
    """Trigger a pgBackRest backup (full / diff / incr)."""

    name = "pgbackrest_backup"
    description = (
        "Trigger a pgBackRest backup. 'type' picks full (slowest, complete) / "
        "diff (since last full) / incr (since last backup of any type). Runs "
        "asynchronously inside the sidecar — return is the command launch "
        "status, not the completion status. Use pgbackrest_info to verify."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["full", "diff", "incr"],
                    "default": "diff",
                },
                "stanza": {"type": "string", "default": "main"},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        stanza = kwargs.get("stanza", "main")
        ns = kwargs.get("namespace", "data")
        btype = kwargs.get("type", "diff")
        ok, out = await _exec_in_pgbackrest(
            [
                "pgbackrest",
                "--stanza",
                stanza,
                "--type",
                btype,
                "--log-level-console=info",
                "backup",
            ],
            namespace=ns,
            timeout=600,  # backups can take a while
        )
        if not ok:
            return ToolResult(success=False, error=out)
        return ToolResult(
            success=True,
            output=f"pgbackrest {btype} backup triggered on stanza {stanza}.",
            data={"type": btype, "stanza": stanza, "log_tail": out[-2000:]},
        )


class PgbackrestCheckTool(BaseTool):
    """Validate pgBackRest can reach the repo + WAL archiving is flowing."""

    name = "pgbackrest_check"
    description = (
        "Run 'pgbackrest check' — verifies the stanza is reachable, the "
        "repo is readable, and WAL archiving is working. Use as a continuous "
        "smoke test or before a backup/restore op."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stanza": {"type": "string", "default": "main"},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        stanza = kwargs.get("stanza", "main")
        ns = kwargs.get("namespace", "data")
        ok, out = await _exec_in_pgbackrest(
            ["pgbackrest", "--stanza", stanza, "check"],
            namespace=ns,
        )
        if not ok:
            return ToolResult(
                success=False,
                error=out,
                data={"healthy": False, "tail": out[-1000:]},
            )
        return ToolResult(
            success=True,
            output=f"pgbackrest check OK (stanza={stanza}).",
            data={"healthy": True, "output": out[-1000:]},
        )


def get_backup_tools() -> list[BaseTool]:
    return [
        PgbackrestInfoTool(),
        PgbackrestBackupTool(),
        PgbackrestCheckTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    PgbackrestInfoTool,
    PgbackrestBackupTool,
    PgbackrestCheckTool,
):
    _cls.audience = Audience.PLATFORM
