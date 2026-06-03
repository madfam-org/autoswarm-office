"""Postgres database lifecycle: dump/restore to R2, staging mask-and-copy.

Staging-refresh is a recurring operator task per the PhyndCRM PP.5 spec
(see /Users/aldoruizluna/labspace/selva-office/CLAUDE.md). Each cycle
requires dumping prod, masking PII columns, and loading into staging. This
module provides the four primitives the ``staging-refresh`` skill composes.

All ops run via ``kubectl exec`` into the ``postgres`` container of the
``postgres`` Deployment in the ``data`` namespace (mirrors the
``backup_ops._exec_in_pgbackrest`` pattern but targets the primary
postgres container, not the pgBackRest sidecar). The pod is assumed to
have ``aws`` CLI available for R2 object transfer; when it isn't the
command fails with a structured error.

R2 credentials are read from ``R2_ENDPOINT`` / ``R2_ACCESS_KEY_ID`` /
``R2_SECRET_ACCESS_KEY`` env vars and injected into the pod's shell for
the duration of each command — they never land in the pod's env at rest.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")

# Conservative identifier regex — blocks shell injection through DB / bucket
# / key names. Postgres identifiers + R2 bucket-naming rules both fit in
# [A-Za-z0-9_.-], so this is strict on purpose.
_SAFE_IDENT = re.compile(r"^[A-Za-z0-9_.\-/]+$")


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


async def _exec_in_postgres(
    shell_cmd: str,
    namespace: str = "data",
    timeout: int = 600,
) -> tuple[bool, str]:
    """Run a shell command in the postgres pod's primary container.

    Uses /bin/sh -lc so callers can compose pipes (pg_dump | gzip |
    aws s3 cp -). Returns (success, stdout_or_error).
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
        out = stream(
            core.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            container="postgres",
            command=["/bin/sh", "-lc", shell_cmd],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _request_timeout=timeout,
        )
        return True, out
    except Exception as e:
        logger.error("postgres exec failed: %s", e)
        return False, str(e)


def _r2_env_prefix() -> str:
    """Build the inline env-var prefix that exports R2 creds for one command.

    We inject creds per-invocation so they never persist in the pod.
    """
    return (
        f"AWS_ACCESS_KEY_ID={R2_ACCESS_KEY_ID} "
        f"AWS_SECRET_ACCESS_KEY={R2_SECRET_ACCESS_KEY} "
        f"AWS_DEFAULT_REGION=auto "
    )


def _r2_creds_check() -> str | None:
    if not R2_ENDPOINT:
        return "R2_ENDPOINT must be set."
    if not R2_ACCESS_KEY_ID:
        return "R2_ACCESS_KEY_ID must be set."
    if not R2_SECRET_ACCESS_KEY:
        return "R2_SECRET_ACCESS_KEY must be set."
    return None


def _validate_ident(name: str, kind: str) -> str | None:
    """Return an error string if 'name' would be unsafe to interpolate."""
    if not name or not _SAFE_IDENT.match(name):
        return f"{kind} must match [A-Za-z0-9_.-/]+"
    return None


class DbDumpToR2Tool(BaseTool):
    """pg_dump a Postgres database and upload to R2."""

    name = "db_dump_to_r2"
    description = (
        "pg_dump the given 'database' and pipe through gzip + aws s3 cp "
        "(R2-compatible) to 's3://{bucket}/{key_prefix}/{database}-{ts}.sql.gz'. "
        "Uses the postgres pod's local socket (no network creds required). "
        "Returns the object key on success. Use as step 1 of a "
        "staging-refresh or DR snapshot."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "bucket": {"type": "string"},
                "key_prefix": {"type": "string", "default": "dumps"},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": ["database", "bucket"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _r2_creds_check()
        if err:
            return ToolResult(success=False, error=err)
        for fld in ("database", "bucket"):
            v = _validate_ident(kwargs[fld], fld)
            if v:
                return ToolResult(success=False, error=v)
        key_prefix = kwargs.get("key_prefix", "dumps")
        v = _validate_ident(key_prefix, "key_prefix")
        if v:
            return ToolResult(success=False, error=v)

        database = kwargs["database"]
        bucket = kwargs["bucket"]
        namespace = kwargs.get("namespace", "data")
        # Timestamp via `date -u +%Y%m%dT%H%M%SZ` inside the pod so we don't
        # need clock-sync between controller + cluster.
        key = f"{key_prefix}/{database}-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
        shell = (
            f"set -eo pipefail; "
            f"{_r2_env_prefix()}"
            f"pg_dump -Fp --no-owner --no-privileges {database} "
            f"| gzip -c "
            f"| aws --endpoint-url {R2_ENDPOINT} s3 cp - s3://{bucket}/{key}"
        )
        ok, out = await _exec_in_postgres(shell, namespace=namespace, timeout=1800)
        if not ok:
            return ToolResult(success=False, error=out)
        return ToolResult(
            success=True,
            output=f"pg_dump of {database} uploaded to s3://{bucket}/{key_prefix}/",
            data={
                "database": database,
                "bucket": bucket,
                "key_prefix": key_prefix,
                "log_tail": out[-2000:],
            },
        )


class DbRestoreFromR2Tool(BaseTool):
    """Download a dump from R2 and restore into Postgres."""

    name = "db_restore_from_r2"
    description = (
        "Download 's3://{bucket}/{key}' and pipe through gunzip + psql into "
        "'target_database'. 'create_if_missing=true' runs "
        "CREATE DATABASE first. Streams directly — no tmp files on disk. "
        "Use to refresh staging from a prod dump, or to recover one DB "
        "from a pre-incident snapshot."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bucket": {"type": "string"},
                "key": {"type": "string"},
                "target_database": {"type": "string"},
                "create_if_missing": {"type": "boolean", "default": False},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": ["bucket", "key", "target_database"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _r2_creds_check()
        if err:
            return ToolResult(success=False, error=err)
        for fld in ("bucket", "key", "target_database"):
            v = _validate_ident(kwargs[fld], fld)
            if v:
                return ToolResult(success=False, error=v)

        bucket = kwargs["bucket"]
        key = kwargs["key"]
        db = kwargs["target_database"]
        namespace = kwargs.get("namespace", "data")
        create = bool(kwargs.get("create_if_missing", False))

        precmd = ""
        if create:
            # Safe because db was validated against _SAFE_IDENT.
            precmd = (
                f"psql -tAc \"SELECT 1 FROM pg_database WHERE datname='{db}'\" "
                f"| grep -q 1 || createdb {db}; "
            )
        shell = (
            f"set -eo pipefail; "
            f"{_r2_env_prefix()}"
            f"{precmd}"
            f"aws --endpoint-url {R2_ENDPOINT} s3 cp s3://{bucket}/{key} - "
            f"| gunzip -c "
            f"| psql -v ON_ERROR_STOP=1 {db}"
        )
        ok, out = await _exec_in_postgres(shell, namespace=namespace, timeout=3600)
        if not ok:
            return ToolResult(success=False, error=out)
        return ToolResult(
            success=True,
            output=f"Restored s3://{bucket}/{key} into {db}.",
            data={
                "bucket": bucket,
                "key": key,
                "target_database": db,
                "log_tail": out[-2000:],
            },
        )


class DbMaskAndCopyTool(BaseTool):
    """Copy 'source_db' into 'target_db' replacing PII columns with stable SHA256 hashes."""

    name = "db_mask_and_copy"
    description = (
        "Clone 'source_db' into 'target_db' in the same cluster. For each "
        "column in 'table_mask_rules' (shape: {table: [col, col, ...]}) the "
        "value in the TARGET database is replaced with "
        "encode(sha256(col::text), 'hex'). Produces a deterministic, "
        "stable masking — same input always hashes to the same output — "
        "so referential integrity across masked columns survives. HITL-gate "
        "this tool inside the skill: it writes to target_db by design."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_db": {"type": "string"},
                "target_db": {"type": "string"},
                "table_mask_rules": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "description": "{table_name: [col1, col2, ...]}",
                },
                "namespace": {"type": "string", "default": "data"},
            },
            "required": ["source_db", "target_db", "table_mask_rules"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        for fld in ("source_db", "target_db"):
            v = _validate_ident(kwargs[fld], fld)
            if v:
                return ToolResult(success=False, error=v)
        rules = kwargs["table_mask_rules"] or {}
        if not isinstance(rules, dict) or not rules:
            return ToolResult(
                success=False,
                error="table_mask_rules must be a non-empty dict of {table: [cols]}.",
            )

        # Validate every table + column identifier.
        for table, cols in rules.items():
            v = _validate_ident(table, f"table '{table}'")
            if v:
                return ToolResult(success=False, error=v)
            if not isinstance(cols, list) or not cols:
                return ToolResult(
                    success=False,
                    error=f"table '{table}' must have at least one column",
                )
            for col in cols:
                v = _validate_ident(col, f"column '{col}'")
                if v:
                    return ToolResult(success=False, error=v)

        source = kwargs["source_db"]
        target = kwargs["target_db"]
        namespace = kwargs.get("namespace", "data")

        # Step 1: clone source → target via pg_dump | psql through the pod.
        # Step 2: run UPDATE ... SET col = encode(sha256(col::text), 'hex')
        #         against target for each (table, col).
        update_statements = []
        for table, cols in rules.items():
            assigns = ", ".join(f"{c} = encode(sha256({c}::text::bytea), 'hex')" for c in cols)
            # Only rows where at least one of the target columns is non-null.
            where = " OR ".join(f"{c} IS NOT NULL" for c in cols)
            update_statements.append(f"UPDATE {table} SET {assigns} WHERE {where};")
        updates_sql = "\n".join(update_statements)

        shell = (
            f"set -eo pipefail; "
            f"pg_dump -Fp --no-owner --no-privileges {source} "
            f"| psql -v ON_ERROR_STOP=1 {target}; "
            f"psql -v ON_ERROR_STOP=1 {target} <<'SQL'\n"
            f"{updates_sql}\n"
            f"SQL"
        )
        ok, out = await _exec_in_postgres(shell, namespace=namespace, timeout=3600)
        if not ok:
            return ToolResult(success=False, error=out)
        total_cols = sum(len(c) for c in rules.values())
        return ToolResult(
            success=True,
            output=(
                f"Cloned {source} → {target} and masked "
                f"{total_cols} column(s) across {len(rules)} table(s)."
            ),
            data={
                "source_db": source,
                "target_db": target,
                "tables_masked": list(rules.keys()),
                "columns_masked": total_cols,
                "log_tail": out[-2000:],
            },
        )


class DbSizeReportTool(BaseTool):
    """Per-table row count + on-disk size report."""

    name = "db_size_report"
    description = (
        "Return row counts (from pg_class.reltuples — accurate to within "
        "~1%, cheap to compute) and on-disk bytes (pg_total_relation_size) "
        "for every user table in 'database'. Useful as a capacity sanity "
        "check before / after a mask-and-copy or DR restore."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "namespace": {"type": "string", "default": "data"},
            },
            "required": ["database"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        v = _validate_ident(kwargs["database"], "database")
        if v:
            return ToolResult(success=False, error=v)
        db = kwargs["database"]
        namespace = kwargs.get("namespace", "data")
        sql = (
            "SELECT n.nspname AS schema, c.relname AS table, "
            "c.reltuples::bigint AS row_estimate, "
            "pg_total_relation_size(c.oid) AS bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog','information_schema') "
            "ORDER BY bytes DESC;"
        )
        # -F, sets column sep; -A disables aligned output (parseable); -t drops header.
        shell = f'set -eo pipefail; psql -v ON_ERROR_STOP=1 -A -t -F"|" {db} -c "{sql}"'
        ok, out = await _exec_in_postgres(shell, namespace=namespace, timeout=120)
        if not ok:
            return ToolResult(success=False, error=out)
        rows: list[dict[str, Any]] = []
        total_bytes = 0
        for line in out.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) != 4:
                continue
            try:
                row_est = int(parts[2])
                nbytes = int(parts[3])
            except ValueError:
                continue
            rows.append(
                {
                    "schema": parts[0],
                    "table": parts[1],
                    "row_estimate": row_est,
                    "bytes": nbytes,
                }
            )
            total_bytes += nbytes
        return ToolResult(
            success=True,
            output=(f"{db}: {len(rows)} table(s), total {total_bytes} bytes."),
            data={
                "database": db,
                "tables": rows,
                "total_bytes": total_bytes,
                "table_count": len(rows),
            },
        )


def get_db_lifecycle_tools() -> list[BaseTool]:
    """Return the DB lifecycle tool set."""
    return [
        DbDumpToR2Tool(),
        DbRestoreFromR2Tool(),
        DbMaskAndCopyTool(),
        DbSizeReportTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    DbDumpToR2Tool,
    DbRestoreFromR2Tool,
    DbMaskAndCopyTool,
    DbSizeReportTool,
):
    _cls.audience = Audience.PLATFORM
