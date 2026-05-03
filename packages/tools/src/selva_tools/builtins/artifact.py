"""Artifact management tools — save, retrieve, and list task artifacts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ..base import BaseTool, ToolResult
from ..storage import LocalFSStorage

_storage = LocalFSStorage()


# Content-addressable layout per LocalFSStorage: <hash[0:2]>/<hash[2:4]>/<hash>
# where <hash> is a SHA-256 hex digest (64 hex chars). Match either the
# relative layout, or an absolute path whose final 3 segments follow the
# same shape (this is what ``SaveArtifactTool`` returns to callers).
_HASH_PATH_RE = re.compile(r"(?:^|/)[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$")


def _is_valid_artifact_path(path: str) -> bool:
    """Reject anything that doesn't look like a content-addressable artifact path."""
    if not path:
        return False
    if "\x00" in path:
        return False
    # Reject home expansion and parent traversal regardless of position.
    if path.startswith("~") or ".." in path.split("/"):
        return False
    return bool(_HASH_PATH_RE.search(path))


class SaveArtifactTool(BaseTool):
    name = "save_artifact"
    description = "Save a task output artifact for later retrieval"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Artifact name"},
                "content": {"type": "string", "description": "Artifact content"},
                "content_type": {
                    "type": "string",
                    "default": "text/plain",
                    "description": "MIME type",
                },
            },
            "required": ["name", "content"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = kwargs.get("name", "")
        content = kwargs.get("content", "")
        content_type = kwargs.get("content_type", "text/plain")

        content_bytes = content.encode("utf-8")
        # Storage path is hash-derived from the caller-supplied content.
        # No caller-supplied path component is honored here, so this tool is
        # not vulnerable to path-traversal in the same way as retrieve/delete.
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        path = await _storage.save(content_bytes, content_hash)

        return ToolResult(
            output=f"Artifact '{name}' saved ({len(content_bytes)} bytes, {content_type})",
            data={
                "artifact_name": name,
                "content_type": content_type,
                "size_bytes": len(content_bytes),
                "content_hash": content_hash,
                "storage_path": path,
            },
        )


class RetrieveArtifactTool(BaseTool):
    name = "retrieve_artifact"
    description = "Retrieve a previously saved artifact by its storage path or hash"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Storage path of the artifact"},
                "content_hash": {
                    "type": "string",
                    "description": "SHA-256 hash of the artifact (alternative to path)",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path")
        content_hash = kwargs.get("content_hash")

        if not path and not content_hash:
            return ToolResult(
                success=False,
                error="Either 'path' or 'content_hash' must be provided",
            )

        if not path and content_hash:
            path = await _storage.exists(content_hash)
            if not path:
                return ToolResult(
                    success=False,
                    error=f"No artifact found with hash: {content_hash}",
                )

        # Defense-in-depth: reject any path that doesn't look like a
        # content-addressable artifact path before calling storage. The
        # storage layer ALSO enforces base-directory containment.
        assert path is not None  # narrowed by the checks above
        if not _is_valid_artifact_path(path):
            return ToolResult(
                success=False,
                error="Invalid artifact path; expected content-addressable layout",
            )

        try:
            data = await _storage.retrieve(path)
            return ToolResult(
                output=data.decode("utf-8", errors="replace"),
                data={"size_bytes": len(data), "path": path},
            )
        except FileNotFoundError:
            return ToolResult(success=False, error=f"Artifact not found: {path}")
        except PermissionError as exc:
            return ToolResult(success=False, error=str(exc))


class ListArtifactsTool(BaseTool):
    name = "list_artifacts"
    description = "List artifacts stored in the local artifact storage"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "default": "",
                    "description": "Hash prefix to filter by",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from pathlib import Path

        prefix = kwargs.get("prefix", "")
        base = Path(_storage._base)
        if not base.exists():
            return ToolResult(output="No artifacts found", data={"artifacts": []})

        artifacts: list[dict[str, Any]] = []
        for f in sorted(base.rglob("*")):
            if f.is_file():
                name = f.name
                if prefix and not name.startswith(prefix):
                    continue
                artifacts.append(
                    {
                        "hash": name,
                        "path": str(f),
                        "size_bytes": f.stat().st_size,
                    }
                )

        return ToolResult(
            output=f"Found {len(artifacts)} artifact(s)",
            data={"artifacts": artifacts},
        )
