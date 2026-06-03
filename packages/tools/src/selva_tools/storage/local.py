"""Local filesystem artifact storage with content-addressable dedup."""

from __future__ import annotations

import os
from pathlib import Path

from .base import ArtifactStorage


class LocalFSStorage(ArtifactStorage):
    """Content-addressable local filesystem storage.

    Layout: ``<base_dir>/<hash[0:2]>/<hash[2:4]>/<hash>``
    """

    def __init__(self, base_dir: str | None = None) -> None:
        self._base = Path(
            base_dir or os.environ.get("ARTIFACT_STORAGE_PATH", "/tmp/selva-artifacts")
        )

    def _hash_path(self, content_hash: str) -> Path:
        return self._base / content_hash[:2] / content_hash[2:4] / content_hash

    def _resolve_safe(self, path: str) -> Path:
        """Resolve ``path`` and verify it is contained within ``self._base``.

        Accepts either a relative path (joined with ``_base``) or an
        absolute path that already lives under ``_base`` (the layout
        returned by :meth:`save`). Any path that escapes the base
        directory -- via ``..`` traversal, an absolute path pointing
        elsewhere, or a symlink -- raises :class:`PermissionError`.
        Null bytes are also rejected.
        """
        if "\x00" in path:
            raise PermissionError("Refusing path containing null byte")

        base_resolved = self._base.resolve()

        candidate = Path(path)
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            target = (self._base / candidate).resolve()

        try:
            target.relative_to(base_resolved)
        except ValueError as exc:
            raise PermissionError(
                f"Refusing access to path outside artifact storage: {path}"
            ) from exc
        return target

    async def save(self, content: bytes, content_hash: str) -> str:
        # Path is hash-derived from caller-supplied content; no caller-controlled
        # path component, so this is safe by construction.
        dest = self._hash_path(content_hash)
        if dest.exists():
            return str(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return str(dest)

    async def retrieve(self, path: str) -> bytes:
        p = self._resolve_safe(path)
        if not p.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return p.read_bytes()

    async def delete(self, path: str) -> bool:
        p = self._resolve_safe(path)
        if p.exists():
            p.unlink()
            return True
        return False

    async def exists(self, content_hash: str) -> str | None:
        dest = self._hash_path(content_hash)
        return str(dest) if dest.exists() else None
