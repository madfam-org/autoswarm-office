"""Tests for the memory store and manager."""

from __future__ import annotations

import tempfile
import uuid

import pytest

from selva_memory.embeddings import EmbeddingProvider
from selva_memory.experience import ExperienceRecord, ExperienceStore
from selva_memory.manager import MemoryManager
from selva_memory.store import MemoryStore


@pytest.fixture
def embedder() -> EmbeddingProvider:
    """Hash-based embedding provider for testing (no API keys needed)."""
    return EmbeddingProvider(dim=64)


@pytest.fixture
def store(embedder: EmbeddingProvider) -> MemoryStore:
    return MemoryStore(
        agent_id=f"test-agent-{uuid.uuid4()}",
        embedding_provider=embedder,
        dim=64,
    )


class TestMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_search(self, store: MemoryStore) -> None:
        await store.store("The sky is blue")
        await store.store("Python is a programming language")
        await store.store("The ocean is vast")

        results = await store.search("what color is the sky", top_k=2)
        assert len(results) <= 2
        assert any("sky" in r.text for r in results)

    @pytest.mark.asyncio
    async def test_store_with_metadata(self, store: MemoryStore) -> None:
        entry_id = await store.store(
            "Important finding", metadata={"source": "research", "priority": "high"}
        )
        assert entry_id
        entries = await store.list_entries(filter_metadata={"source": "research"})
        assert len(entries) == 1
        assert entries[0].metadata["priority"] == "high"

    @pytest.mark.asyncio
    async def test_delete_entries(self, store: MemoryStore) -> None:
        id1 = await store.store("entry 1")
        await store.store("entry 2")
        assert await store.get_count() == 2

        deleted = await store.delete([id1])
        assert deleted == 1
        assert await store.get_count() == 1

    @pytest.mark.asyncio
    async def test_empty_search(self, store: MemoryStore) -> None:
        results = await store.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_persistence(self, embedder: EmbeddingProvider) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_id = f"persist-test-{uuid.uuid4()}"
            # Store some memories
            store1 = MemoryStore(
                agent_id=agent_id,
                embedding_provider=embedder,
                dim=64,
                persist_dir=tmpdir,
            )
            await store1.store("persistent memory 1")
            await store1.store("persistent memory 2")
            assert await store1.get_count() == 2

            # Load from disk
            store2 = MemoryStore(
                agent_id=agent_id,
                embedding_provider=embedder,
                dim=64,
                persist_dir=tmpdir,
            )
            assert await store2.get_count() == 2


class TestMemoryManager:
    @pytest.mark.asyncio
    async def test_get_store(self, embedder: EmbeddingProvider) -> None:
        manager = MemoryManager(embedding_provider=embedder)
        store = manager.get_store("agent-1")
        assert store.agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_store_and_retrieve_context(self, embedder: EmbeddingProvider) -> None:
        manager = MemoryManager(embedding_provider=embedder)
        agent_id = f"agent-{uuid.uuid4()}"
        await manager.store_memory(agent_id, "The deployment failed due to OOM")
        await manager.store_memory(agent_id, "Fixed by increasing memory limit to 4GB")

        context = await manager.get_relevant_context(agent_id, "deployment memory issue")
        assert "Relevant Memories" in context
        assert len(context) > 0

    @pytest.mark.asyncio
    async def test_empty_context(self, embedder: EmbeddingProvider) -> None:
        manager = MemoryManager(embedding_provider=embedder)
        context = await manager.get_relevant_context(f"new-agent-{uuid.uuid4()}", "anything")
        assert context == ""


class TestExperienceStore:
    @pytest.mark.asyncio
    async def test_record_and_search(self, embedder: EmbeddingProvider) -> None:
        store = ExperienceStore(role=f"coder-{uuid.uuid4()}", embedding_provider=embedder)
        await store.record(
            ExperienceRecord(
                task_pattern="Fix a null pointer exception in the auth module",
                approach="Check for null before accessing .user property",
                outcome="Fixed successfully, no regressions",
                score=0.95,
            )
        )
        results = await store.search_similar("null reference error in auth")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_shortcuts(self, embedder: EmbeddingProvider) -> None:
        store = ExperienceStore(role=f"reviewer-{uuid.uuid4()}", embedding_provider=embedder)
        await store.record(
            ExperienceRecord(
                task_pattern="Review PR for security vulnerabilities",
                approach="Run SAST tools first, then manual review",
                outcome="Caught XSS vulnerability",
                score=0.9,
            )
        )
        shortcuts = await store.get_shortcuts("security review of pull request")
        assert len(shortcuts) >= 1

    @pytest.mark.asyncio
    async def test_low_score_filtered(self, embedder: EmbeddingProvider) -> None:
        store = ExperienceStore(role=f"coder-{uuid.uuid4()}", embedding_provider=embedder)
        await store.record(
            ExperienceRecord(
                task_pattern="Attempt to fix database migration",
                approach="Just re-run the migration",
                outcome="Failed, made things worse",
                score=0.2,
            )
        )
        results = await store.search_similar("database migration issue", min_score=0.5)
        assert len(results) == 0
