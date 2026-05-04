"""Sibling tool to ``linkedin_drafts`` — read-only listing of recent
LinkedIn drafts so the operator can browse what's queued for manual
copy-paste.

Lives in its own file (rather than alongside the create tool) because:

- Single-responsibility: create vs list are distinct read/write concerns
  and the create file is large enough already.
- Lets a future operator-side script import just the listing helper
  without pulling in the validation tables (audiences, platforms,
  tones) the create tool needs.

NO POSTING. The whole package is draft-only by design — see the
``linkedin_drafts`` module docstring for the rationale.
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import BaseTool, ToolResult
from .linkedin_drafts import (
    _drafts_index_dir,
    _parse_draft_frontmatter,
    _storage,
)

logger = logging.getLogger(__name__)


class LinkedInDraftListTool(BaseTool):
    """List recent LinkedIn drafts so the operator can browse what's queued.

    Scans the sidecar index directory (most-recent date subdirs first),
    optionally filtered by ``status`` (default ``"draft"``), and returns
    up to ``limit`` entries with their parsed frontmatter + the storage
    path the artifact lives at.

    Returns ``data["drafts"]: list[dict]``. Empty list when nothing
    matches; never raises on per-draft parse error (one corrupted index
    file shouldn't blind the operator to the rest of the queue).
    """

    name = "linkedin_draft_list"
    description = (
        "List recent LinkedIn drafts (most-recent first) so the operator can "
        "browse what's staged. Returns draft_id, audience, platform, topic, "
        "char_count, created_at, and the storage path. NO POSTING involved -- "
        "this is a read-only browse tool."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "Filter by frontmatter status. Default 'draft'. "
                        "Only drafts whose frontmatter matches are returned."
                    ),
                    "default": "draft",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max drafts to return.",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        status_filter = (kwargs.get("status") or "draft").strip()
        limit = int(kwargs.get("limit") or 20)
        if limit < 1 or limit > 200:
            return ToolResult(success=False, error="limit must be 1..200")

        index_root = _drafts_index_dir()
        if not index_root.exists():
            return ToolResult(
                success=True,
                output="No LinkedIn drafts found.",
                data={"drafts": []},
            )

        # Most-recent date dir first (string sort works because the
        # subdir names are ISO YYYY-MM-DD, lexically increasing).
        date_dirs = sorted(
            (p for p in index_root.iterdir() if p.is_dir()),
            reverse=True,
        )

        out: list[dict[str, Any]] = []
        for date_dir in date_dirs:
            if len(out) >= limit:
                break
            # Within each date, sort by mtime so the most-recently-written
            # drafts surface first. Filenames are random uuid4s which give
            # no temporal signal, but mtime does.
            idx_files = sorted(
                date_dir.glob("*.idx"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for idx_file in idx_files:
                if len(out) >= limit:
                    break
                try:
                    storage_path = idx_file.read_text(encoding="utf-8").strip()
                    if not storage_path:
                        continue
                    data = await _storage.retrieve(storage_path)
                    markdown = data.decode("utf-8", errors="replace")
                except (FileNotFoundError, PermissionError, OSError) as exc:
                    # One corrupted index file shouldn't blind the
                    # listing of the rest. Log + skip.
                    logger.warning(
                        "linkedin_draft_list: skipping unreadable index %s (%s)",
                        idx_file,
                        exc,
                    )
                    continue

                fm = _parse_draft_frontmatter(markdown)
                if fm.get("status", "draft") != status_filter:
                    continue
                draft_id = fm.get("draft_id") or idx_file.stem
                out.append(
                    {
                        "draft_id": draft_id,
                        "audience": fm.get("audience", ""),
                        "platform": fm.get("platform", ""),
                        "topic": fm.get("topic", ""),
                        "char_count": int(fm.get("char_count", "0") or 0),
                        "created_at": fm.get("created_at", ""),
                        "status": fm.get("status", "draft"),
                        "storage_path": storage_path,
                        "logical_path": f"linkedin_drafts/{date_dir.name}/{draft_id}.md",
                    }
                )

        return ToolResult(
            success=True,
            output=f"Found {len(out)} LinkedIn draft(s) with status='{status_filter}'.",
            data={"drafts": out, "status": status_filter, "limit": limit},
        )


__all__ = ["LinkedInDraftListTool"]
