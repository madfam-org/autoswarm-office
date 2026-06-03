"""Regression tests for artifact-path traversal containment (commit e71337c).

Pre-fix: ``RetrieveArtifactTool`` and ``DeleteArtifactTool`` passed
caller-supplied ``path`` directly to ``Path(path).read_bytes()`` with
no containment. An LLM under prompt injection could read
``/etc/passwd``, ``/run/secrets/.../token``, or
``~/.selva/org-config.yaml``.

Post-fix:
  - ``LocalFSStorage._resolve_safe()`` rejects anything outside ``_base``
    via ``.resolve() + .relative_to()`` (also rejects null bytes).
  - ``RetrieveArtifactTool`` ALSO validates the content-addressable hash
    shape upfront (``_HASH_PATH_RE``) before reaching storage.
  - ``SaveArtifactTool`` is structurally safe (path is hash-derived from
    caller-supplied content; no caller-supplied path component).

These tests pin both layers of defence so the regression cannot
silently return.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from selva_tools.builtins.artifact import RetrieveArtifactTool, _is_valid_artifact_path
from selva_tools.storage.local import LocalFSStorage


@pytest.fixture()
def storage_base() -> tempfile.TemporaryDirectory:
    """Yield a TemporaryDirectory used as the artifact storage base."""
    return tempfile.TemporaryDirectory()


# ---------------------------------------------------------------------------
# Storage-layer containment (LocalFSStorage._resolve_safe).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_rejects_absolute_path_outside_base() -> None:
    """An absolute path pointing outside _base raises PermissionError.

    Pre-fix this would have read /etc/passwd. Post-fix the
    ``_resolve_safe`` guard refuses with PermissionError.
    """
    with tempfile.TemporaryDirectory() as base:
        s = LocalFSStorage(base_dir=base)
        with pytest.raises(PermissionError):
            await s.retrieve("/etc/passwd")


@pytest.mark.asyncio
async def test_retrieve_rejects_traversal_path() -> None:
    """A relative path with ``..`` segments escaping the base raises PermissionError."""
    with tempfile.TemporaryDirectory() as base:
        s = LocalFSStorage(base_dir=base)
        with pytest.raises(PermissionError):
            await s.retrieve("../../etc/passwd")


@pytest.mark.asyncio
async def test_retrieve_rejects_null_byte() -> None:
    """A path containing a null byte raises PermissionError before any FS work."""
    with tempfile.TemporaryDirectory() as base:
        s = LocalFSStorage(base_dir=base)
        # Build a content-addressable-shaped path with a smuggled null byte.
        bad_path = "aa/bb/" + ("0" * 64) + "\x00/etc/passwd"
        with pytest.raises(PermissionError):
            await s.retrieve(bad_path)


@pytest.mark.asyncio
async def test_retrieve_accepts_valid_hash_path_after_save() -> None:
    """The happy path: save() then retrieve() round-trips correctly.

    This protects against an over-broad regression where the
    containment check accidentally rejects legitimate hash paths.
    """
    with tempfile.TemporaryDirectory() as base:
        s = LocalFSStorage(base_dir=base)
        content = b"hi"
        h = hashlib.sha256(content).hexdigest()
        path = await s.save(content, h)

        # Round-trip via the absolute path returned by save().
        result = await s.retrieve(path)
        assert result == b"hi"

        # And via a relative-to-base form.
        rel = Path(path).relative_to(Path(base))
        result_rel = await s.retrieve(str(rel))
        assert result_rel == b"hi"


# ---------------------------------------------------------------------------
# Tool-layer defence-in-depth (RetrieveArtifactTool._is_valid_artifact_path).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_artifact_tool_rejects_non_hash_path() -> None:
    """Tool rejects paths that don't match the content-addressable layout.

    Even though the storage layer would also reject this, the tool
    has its own validator so the failure mode is a clean
    ``ToolResult(success=False)`` rather than a raised exception.
    """
    tool = RetrieveArtifactTool()
    result = await tool.execute(path="aa/bb/not-a-hash")

    assert result.success is False
    assert "invalid" in (result.error or "").lower()


def test_is_valid_artifact_path_rejects_traversal() -> None:
    """Direct unit test: the validator rejects ``..`` traversal."""
    # Even when wrapped in a hash-shaped layout, ``..`` is rejected.
    bad = "../" + ("a" * 2) + "/" + ("b" * 2) + "/" + ("c" * 64)
    assert _is_valid_artifact_path(bad) is False


def test_is_valid_artifact_path_rejects_home_expansion() -> None:
    """Direct unit test: paths starting with ``~`` are rejected."""
    bad = "~/" + ("a" * 2) + "/" + ("b" * 2) + "/" + ("c" * 64)
    assert _is_valid_artifact_path(bad) is False


def test_is_valid_artifact_path_rejects_null_byte() -> None:
    """Null byte in the path is rejected at the tool layer too."""
    bad = "aa/bb/" + ("0" * 64) + "\x00"
    assert _is_valid_artifact_path(bad) is False


def test_is_valid_artifact_path_accepts_well_formed() -> None:
    """A clean hash-shaped path passes the validator (control case)."""
    good = "ab/cd/" + ("a" * 64)
    assert _is_valid_artifact_path(good) is True
