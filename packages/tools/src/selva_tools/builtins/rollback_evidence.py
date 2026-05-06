"""Rollback pointer and evidence capture primitives.

This module intentionally does not execute rollbacks. It records the data a
caller would need to make a rollback decision and returns artifact metadata in
``ToolResult`` format.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ..base import BaseTool, ToolResult
from ..storage import LocalFSStorage

_storage = LocalFSStorage()


class RollbackEvidenceRecordTool(BaseTool):
    name = "rollback_evidence_record"
    description = (
        "Record rollback pointers and deployment evidence as a JSON artifact. "
        "Non-destructive: this tool never performs rollback execution."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service or app name."},
                "environment": {"type": "string", "description": "Target environment."},
                "deployment_id": {"type": "string", "description": "Deploy/run/change identifier."},
                "current_pointer": {
                    "type": "object",
                    "description": "Current deployment pointer, e.g. git_sha/image_digest/chart/app revision.",
                    "default": {},
                },
                "rollback_pointer": {
                    "type": "object",
                    "description": "Known-good pointer to roll back to. Required for a ready record.",
                    "default": {},
                },
                "smoke_result": {
                    "type": "object",
                    "description": "Optional ToolResult.data from endpoint_smoke_check.",
                    "default": {},
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Supporting observations, links, alert IDs, logs, metrics, or operator notes.",
                    "default": [],
                },
                "rollback_requested": {
                    "type": "boolean",
                    "description": "Must remain false. This recorder does not execute destructive rollback actions.",
                    "default": False,
                },
            },
            "required": ["service", "environment", "deployment_id", "current_pointer", "rollback_pointer"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs.get("rollback_requested") is True:
            return ToolResult(
                success=False,
                error="rollback execution is not supported by this non-destructive evidence recorder",
            )

        service = str(kwargs.get("service") or "").strip()
        environment = str(kwargs.get("environment") or "").strip()
        deployment_id = str(kwargs.get("deployment_id") or "").strip()
        current_pointer = kwargs.get("current_pointer") or {}
        rollback_pointer = kwargs.get("rollback_pointer") or {}
        smoke_result = kwargs.get("smoke_result") or {}
        evidence = kwargs.get("evidence") or []

        if not service:
            return ToolResult(success=False, error="service is required")
        if not environment:
            return ToolResult(success=False, error="environment is required")
        if not deployment_id:
            return ToolResult(success=False, error="deployment_id is required")
        if not isinstance(current_pointer, dict) or not current_pointer:
            return ToolResult(success=False, error="current_pointer must be a non-empty object")
        if not isinstance(rollback_pointer, dict) or not rollback_pointer:
            return ToolResult(success=False, error="rollback_pointer must be a non-empty object")
        if smoke_result and not isinstance(smoke_result, dict):
            return ToolResult(success=False, error="smoke_result must be an object")
        if not isinstance(evidence, list):
            return ToolResult(success=False, error="evidence must be a list")

        smoke_verdict = str(smoke_result.get("verdict") or "not_provided") if smoke_result else "not_provided"
        record = {
            "schema_version": "rollback-evidence/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "service": service,
            "environment": environment,
            "deployment_id": deployment_id,
            "current_pointer": current_pointer,
            "rollback_pointer": rollback_pointer,
            "smoke_result": smoke_result,
            "evidence": evidence,
            "rollback_execution": {
                "performed": False,
                "supported_by_tool": False,
                "note": "Evidence capture only; caller must use an explicit rollback executor if policy allows.",
            },
        }
        content = json.dumps(record, sort_keys=True, indent=2)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = await _storage.save(content.encode("utf-8"), content_hash)

        return ToolResult(
            success=True,
            output=(
                f"rollback evidence recorded for {service}/{environment} "
                f"deployment={deployment_id} smoke_verdict={smoke_verdict}"
            ),
            data={
                "verdict": "recorded",
                "artifact_name": f"rollback-evidence-{service}-{environment}-{deployment_id}.json",
                "content_type": "application/json",
                "content_hash": content_hash,
                "storage_path": path,
                "record": record,
            },
        )


def get_rollback_evidence_tools() -> list[BaseTool]:
    return [RollbackEvidenceRecordTool()]
