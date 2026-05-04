"""Kustomize helpers — digest pinning + build dry-run.

Every enclii-build CI workflow's final step is 'kustomize edit set image'
committing new digests to the service's kustomization.yaml. Agents don't have
a tool for that today — they'd need a shell escape. This module wraps the
two operations agents actually need: set an image digest, and dry-run a build
to validate the result.

Reads/writes are local-file operations; the commit-back-to-git is still
delegated to the ``github_admin`` tools so the audit trail stays in one place.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover — yaml is a runtime dep
    yaml = None

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _ensure_yaml() -> str | None:
    if yaml is None:
        return "PyYAML must be installed to use kustomize tools."
    return None


def _find_kustomize() -> str | None:
    """Return kustomize binary path if discoverable, else None."""
    for cand in ("kustomize", "/usr/local/bin/kustomize"):
        if shutil.which(cand):
            return cand
    return None


class KustomizeListImagesTool(BaseTool):
    """List the images block of a kustomization.yaml."""

    name = "kustomize_list_images"
    description = (
        "Read the 'images' list from a kustomization.yaml. Returns each "
        "entry's name, newName, newTag, and digest. Use before "
        "kustomize_set_image to know the current pin."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kustomization_path": {
                    "type": "string",
                    "description": "Absolute path to the kustomization.yaml.",
                },
            },
            "required": ["kustomization_path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _ensure_yaml()
        if err:
            return ToolResult(success=False, error=err)
        path = Path(kwargs["kustomization_path"])
        if not path.is_file():
            return ToolResult(success=False, error=f"file not found: {path}")
        try:
            doc = yaml.safe_load(path.read_text()) or {}
            images = doc.get("images") or []
            return ToolResult(
                success=True,
                output=f"{len(images)} image entry/entries.",
                data={"images": images},
            )
        except Exception as e:
            logger.error("kustomize_list_images failed: %s", e)
            return ToolResult(success=False, error=str(e))


class KustomizeSetImageTool(BaseTool):
    """Pin an image to a digest in kustomization.yaml (tag OR digest supported)."""

    name = "kustomize_set_image"
    description = (
        "Edit a kustomization.yaml's 'images' block. Equivalent to "
        "'kustomize edit set image NAME=NAME@DIGEST' but implemented in-process "
        "(no kustomize binary required) so agents can run this in environments "
        "without the CLI. Pass 'digest' to pin by sha256 OR 'new_tag' to pin by "
        "tag; if both given, digest wins."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kustomization_path": {"type": "string"},
                "name": {
                    "type": "string",
                    "description": "Image name as it appears in the source "
                    "manifest (e.g. 'ghcr.io/madfam-org/subtext-api').",
                },
                "new_name": {
                    "type": "string",
                    "description": "Optional rename; defaults to the same as 'name'.",
                },
                "digest": {
                    "type": "string",
                    "description": "sha256:... to pin by digest. Preferred.",
                },
                "new_tag": {
                    "type": "string",
                    "description": "Alternative: pin by tag. Ignored if digest provided.",
                },
            },
            "required": ["kustomization_path", "name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _ensure_yaml()
        if err:
            return ToolResult(success=False, error=err)
        path = Path(kwargs["kustomization_path"])
        if not path.is_file():
            return ToolResult(success=False, error=f"file not found: {path}")
        name = kwargs["name"]
        new_name = kwargs.get("new_name") or name
        digest = kwargs.get("digest")
        new_tag = kwargs.get("new_tag")
        if not digest and not new_tag:
            return ToolResult(success=False, error="one of 'digest' or 'new_tag' is required")
        try:
            doc = yaml.safe_load(path.read_text()) or {}
            images = doc.setdefault("images", [])
            # Find existing entry by name.
            existing = next((i for i in images if i.get("name") == name), None)
            entry = existing or {"name": name}
            entry["newName"] = new_name
            if digest:
                entry["digest"] = digest
                entry.pop("newTag", None)
            else:
                entry["newTag"] = new_tag
                entry.pop("digest", None)
            if existing is None:
                images.append(entry)
            path.write_text(yaml.safe_dump(doc, sort_keys=False))
            return ToolResult(
                success=True,
                output=f"Pinned {name} → {new_name}@{digest or new_tag}",
                data={"name": name, "newName": new_name, "pin": digest or new_tag},
            )
        except Exception as e:
            logger.error("kustomize_set_image failed: %s", e)
            return ToolResult(success=False, error=str(e))


class KustomizeBuildTool(BaseTool):
    """Dry-run a kustomize build to validate manifests."""

    name = "kustomize_build"
    description = (
        "Run 'kustomize build <path>' and return the rendered YAML plus a "
        "summary of resources. Used to validate a manifest set before "
        "committing. Requires the 'kustomize' binary on PATH; if not "
        "available, returns a structured 'unavailable' error rather than "
        "crashing."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing kustomization.yaml.",
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        kbin = _find_kustomize()
        if not kbin:
            return ToolResult(
                success=False,
                error="kustomize binary not found on PATH. Install from "
                "https://kubectl.docs.kubernetes.io/installation/kustomize/",
            )
        path = kwargs["path"]
        if not os.path.isdir(path):
            return ToolResult(success=False, error=f"not a directory: {path}")
        try:
            out = subprocess.run(
                [kbin, "build", path],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if out.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"kustomize build failed (exit {out.returncode}): {out.stderr[:1000]}",
                )
            # Summarise resources.
            err = _ensure_yaml()
            if err:
                return ToolResult(success=False, error=err)
            docs = list(yaml.safe_load_all(out.stdout))
            summary = [
                {
                    "kind": d.get("kind"),
                    "name": (d.get("metadata") or {}).get("name"),
                    "namespace": (d.get("metadata") or {}).get("namespace"),
                }
                for d in docs
                if isinstance(d, dict) and d.get("kind")
            ]
            return ToolResult(
                success=True,
                output=f"Rendered {len(summary)} resource(s).",
                data={"resources": summary, "yaml": out.stdout},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="kustomize build timed out")
        except Exception as e:
            logger.error("kustomize_build failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_kustomize_tools() -> list[BaseTool]:
    return [
        KustomizeListImagesTool(),
        KustomizeSetImageTool(),
        KustomizeBuildTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    KustomizeListImagesTool,
    KustomizeSetImageTool,
    KustomizeBuildTool,
):
    _cls.audience = Audience.PLATFORM
