"""Tests for the local filesystem artifact storage."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from selva_tools.storage.local import LocalFSStorage


@pytest.fixture()
def storage(tmp_path: Path) -> LocalFSStorage:
    return LocalFSStorage(base_dir=str(tmp_path))


@pytest.mark.asyncio()
async def test_save_creates_file(storage: LocalFSStorage) -> None:
    content = b"hello world"
    h = hashlib.sha256(content).hexdigest()
    path = await storage.save(content, h)
    assert Path(path).exists()
    assert Path(path).read_bytes() == content


@pytest.mark.asyncio()
async def test_save_is_content_addressable(storage: LocalFSStorage) -> None:
    content = b"test data"
    h = hashlib.sha256(content).hexdigest()
    path1 = await storage.save(content, h)
    path2 = await storage.save(content, h)
    assert path1 == path2


@pytest.mark.asyncio()
async def test_retrieve_returns_content(storage: LocalFSStorage) -> None:
    content = b"retrieve me"
    h = hashlib.sha256(content).hexdigest()
    path = await storage.save(content, h)
    result = await storage.retrieve(path)
    assert result == content


@pytest.mark.asyncio()
async def test_retrieve_missing_raises(storage: LocalFSStorage) -> None:
    # Use a well-formed path under _base that has no content. Post-v2.2.x,
    # absolute paths outside _base raise PermissionError instead of FileNotFoundError
    # (see test_artifact_path_containment.py for that boundary).
    missing_hash = "0" * 64
    relative_path = f"00/00/{missing_hash}"
    with pytest.raises(FileNotFoundError):
        await storage.retrieve(relative_path)


@pytest.mark.asyncio()
async def test_delete_removes_file(storage: LocalFSStorage) -> None:
    content = b"delete me"
    h = hashlib.sha256(content).hexdigest()
    path = await storage.save(content, h)
    assert Path(path).exists()
    deleted = await storage.delete(path)
    assert deleted is True
    assert not Path(path).exists()


@pytest.mark.asyncio()
async def test_delete_nonexistent_returns_false(storage: LocalFSStorage) -> None:
    # Same containment-boundary note as test_retrieve_missing_raises.
    missing_hash = "0" * 64
    relative_path = f"00/00/{missing_hash}"
    deleted = await storage.delete(relative_path)
    assert deleted is False


@pytest.mark.asyncio()
async def test_exists_finds_saved_content(storage: LocalFSStorage) -> None:
    content = b"find me"
    h = hashlib.sha256(content).hexdigest()
    await storage.save(content, h)
    result = await storage.exists(h)
    assert result is not None


@pytest.mark.asyncio()
async def test_exists_returns_none_for_missing(storage: LocalFSStorage) -> None:
    result = await storage.exists("0" * 64)
    assert result is None


@pytest.mark.asyncio()
async def test_hash_path_layout(storage: LocalFSStorage) -> None:
    h = "abcdef1234567890" + "0" * 48
    path = storage._hash_path(h)
    assert path.parts[-3] == "ab"
    assert path.parts[-2] == "cd"
    assert path.name == h
