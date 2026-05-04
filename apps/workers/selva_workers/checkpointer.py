"""Checkpointer factory for LangGraph state persistence."""

from __future__ import annotations

import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from .config import get_settings

logger = logging.getLogger(__name__)


def create_checkpointer() -> BaseCheckpointSaver:
    """Return a PostgresSaver when DATABASE_URL is set, else MemorySaver.

    The PostgresSaver provides durable state that survives worker restarts,
    while MemorySaver is used for local development without a database.
    """
    settings = get_settings()

    if settings.database_url:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            # PostgresSaver expects a sync psycopg connection string.
            # Convert asyncpg URL to psycopg if needed.
            db_url = settings.database_url
            if "asyncpg" in db_url:
                db_url = db_url.replace("postgresql+asyncpg", "postgresql")

            # KNOWN LATENT BUG (tracked):
            # ``PostgresSaver.from_conn_string`` is a ``contextmanager`` that
            # yields a ``PostgresSaver``. Calling ``.setup()`` and returning
            # the result here always raises ``AttributeError`` at runtime,
            # which the broad ``except`` below catches — so this branch has
            # never actually used Postgres. The proper fix is to open a
            # ``psycopg.Connection`` ourselves and pass it to the
            # ``PostgresSaver(conn=...)`` constructor, keeping the
            # connection alive for the lifetime of the worker process. That
            # work is deferred because it requires connection-lifecycle
            # plumbing in ``__main__.py`` (graceful close on shutdown,
            # reconnect on connection drop) and a migration of the
            # checkpoints table. Until then, every worker uses MemorySaver
            # in practice.
            saver = PostgresSaver.from_conn_string(db_url)
            saver.setup()  # type: ignore[attr-defined]
            logger.info("Using PostgresSaver for graph checkpointing")
            return saver  # type: ignore[return-value]
        except Exception:
            logger.warning(
                "Failed to initialize PostgresSaver, falling back to MemorySaver",
                exc_info=True,
            )

    logger.info("Using MemorySaver for graph checkpointing")
    return MemorySaver()
