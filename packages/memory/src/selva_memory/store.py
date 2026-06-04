"""Per-agent memory store backed by pgvector for semantic search."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, String, delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from .embeddings import DEFAULT_DIM, EmbeddingProvider

logger = logging.getLogger(__name__)

# ``declarative_base()`` returns a dynamically generated class; mypy can't
# trace it as a valid base. The whole module is SA 1.4-style ORM, kept for
# backwards compat with the ``MemoryEntryModel`` schema in the wild.
Base = declarative_base()


class MemoryEntryModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "agent_memories"
    id = Column(String, primary_key=True)
    agent_id = Column(String, index=True, nullable=False)
    text = Column(String, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=False)
    created_at = Column(String, nullable=False)
    embedding = Column(Vector(DEFAULT_DIM))


@dataclass
class MemoryEntry:
    """A single memory entry with text, metadata, and vector embedding."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    agent_id: str = ""


class MemoryStore:
    """Per-agent semantic memory store using pgvector for similarity search.

    Replaces previous FAISS implementation to handle scaling and persistence
    natively via PostgreSQL.
    """

    def __init__(
        self,
        agent_id: str,
        embedding_provider: EmbeddingProvider,
        dim: int = DEFAULT_DIM,
        persist_dir: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._embedder = embedding_provider
        self._dim = dim

        # Read database url from env, fallback to default docker-compose url
        db_url = os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://selva:selva@localhost:5432/selva"
        )
        # Ensure driver is asyncpg
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        self._engine = create_async_engine(db_url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._count_cache: int | None = None

    def _normalize_vector(self, vector: Any) -> list[float]:
        """Fit an embedder vector to the storage column dimension.

        The database schema stores ``vector(DEFAULT_DIM)`` for production
        index compatibility. Tests and some local embedders use smaller
        dimensions; pad those with zeroes so search and insert vectors stay
        comparable without changing the persisted schema.
        """
        values = [float(value) for value in vector]
        if len(values) > DEFAULT_DIM:
            return values[:DEFAULT_DIM]
        if len(values) < DEFAULT_DIM:
            return values + [0.0] * (DEFAULT_DIM - len(values))
        return values

    async def _init_db(self) -> None:
        async with self._engine.begin() as conn:
            # Check if pgvector extension is available, create if needed
            await conn.execute(select(1))  # Just a ping
            # Note: Extension creation requires superuser, assuming it's done via migration or root
            await conn.run_sync(Base.metadata.create_all)

    async def store(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """Store a memory entry. Returns the entry ID."""
        await self._init_db()
        entry_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()

        vector = self._normalize_vector(await self._embedder.embed_single(text))

        db_entry = MemoryEntryModel(
            id=entry_id,
            agent_id=self.agent_id,
            text=text,
            metadata_=metadata or {},
            created_at=created_at,
            embedding=vector,
        )

        async with self._session_factory() as session:
            session.add(db_entry)
            await session.commit()
        self._count_cache = (self._count_cache or 0) + 1

        logger.debug("Stored memory for agent %s: %s", self.agent_id, entry_id)
        return entry_id

    async def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Search for memories similar to the query text."""
        await self._init_db()
        query_vector = self._normalize_vector(await self._embedder.embed_single(query))

        async with self._session_factory() as session:
            # Using inner product (<#>) which matches FAISS IndexFlatIP
            stmt = (
                select(MemoryEntryModel)
                .filter(MemoryEntryModel.agent_id == self.agent_id)
                .order_by(MemoryEntryModel.embedding.cosine_distance(query_vector))
                .limit(top_k)
            )
            result = await session.execute(stmt)
            result.scalars().all()

            # pgvector doesn't return distance directly in simple
            # selects, so we need a tuple. Adjust to get distance:
            dist_col = MemoryEntryModel.embedding.cosine_distance(
                query_vector,
            ).label("distance")
            stmt_with_dist = (
                select(MemoryEntryModel, dist_col)
                .filter(MemoryEntryModel.agent_id == self.agent_id)
                .order_by("distance")
                .limit(top_k)
            )
            result_dist = await session.execute(stmt_with_dist)

            results = []
            for row, distance in result_dist:
                meta = dict(row.metadata_)
                # Convert cosine distance back to a similarity score if matched FAISS
                meta["_similarity_score"] = 1.0 - float(distance)

                results.append(
                    MemoryEntry(
                        id=row.id,
                        text=row.text,
                        metadata=meta,
                        created_at=row.created_at,
                        agent_id=row.agent_id,
                    )
                )

            return results

    async def list_entries(
        self, filter_metadata: dict[str, Any] | None = None
    ) -> list[MemoryEntry]:
        """List all entries, optionally filtered by metadata keys.

        In an async pgvector context, this signature is ideally
        awaited. But if keeping synchronous signature compatibility
        is strict, this might fail unless used safely. Here we
        implement the async version assuming clients will adapt.
        """
        await self._init_db()
        async with self._session_factory() as session:
            stmt = select(MemoryEntryModel).filter(MemoryEntryModel.agent_id == self.agent_id)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if filter_metadata is None:
                self._count_cache = len(rows)

            entries = []
            for row in rows:
                # ``row`` is a MemoryEntryModel instance; mypy types the
                # column descriptors as ``Column[X]`` due to the SA 1.4
                # legacy declarative pattern, but at runtime they hold ``X``.
                row_id: str = row.id  # type: ignore[assignment]
                row_text: str = row.text  # type: ignore[assignment]
                row_metadata: dict[str, Any] = row.metadata_  # type: ignore[assignment]
                row_created_at: str = row.created_at  # type: ignore[assignment]
                row_agent_id: str = row.agent_id  # type: ignore[assignment]
                if filter_metadata and not all(
                    row_metadata.get(k) == v for k, v in filter_metadata.items()
                ):
                    continue
                entries.append(
                    MemoryEntry(
                        id=row_id,
                        text=row_text,
                        metadata=row_metadata,
                        created_at=row_created_at,
                        agent_id=row_agent_id,
                    )
                )
            return entries

    async def delete(self, entry_ids: list[str]) -> int:
        """Delete entries by ID. Returns count of deleted entries."""
        if not entry_ids:
            return 0
        await self._init_db()
        async with self._session_factory() as session:
            stmt = (
                delete(MemoryEntryModel)
                .where(MemoryEntryModel.id.in_(entry_ids))
                .where(MemoryEntryModel.agent_id == self.agent_id)
            )
            result = await session.execute(stmt)
            await session.commit()
            # ``execute(delete(...))`` returns a CursorResult exposing
            # ``rowcount``; mypy widens to the base ``Result`` which lacks it.
            deleted_count = int(result.rowcount)  # type: ignore[attr-defined]
            if self._count_cache is not None:
                self._count_cache = max(0, self._count_cache - deleted_count)
            return deleted_count

    async def get_count(self) -> int:
        """Return the current number of entries for this agent from the DB."""
        await self._init_db()
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(MemoryEntryModel).where(
                    MemoryEntryModel.agent_id == self.agent_id
                )
            )
            count = int(result.scalar_one())
            self._count_cache = count
            return count

    @property
    def count(self) -> int:
        """Best-effort cached count for legacy synchronous callers.

        Async runtime paths should call ``await get_count()`` so they do not
        suppress memory injection because of an uninitialized cache.
        """
        return self._count_cache or 0

    def _save(self) -> None:
        pass

    def _load(self) -> None:
        pass
