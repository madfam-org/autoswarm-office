"""LangGraph checkpointer factory with durable Postgres-backed state.

Background — what was broken (PR #115 documented this; this PR fixes it):
    The previous implementation called ``PostgresSaver.from_conn_string(url)``
    as if it were a regular factory. That method is actually a
    ``@contextmanager`` that opens its own connection inside a ``with``
    block and closes it on exit. Calling it without ``with`` returns a
    generator object; calling ``.setup()`` on the generator raises
    ``AttributeError``. The broad ``except`` below caught that and
    silently fell back to ``MemorySaver``, so **every worker has been
    using MemorySaver in production** since the file was written.

    Concrete consequence: if a worker pod was killed mid-graph (between
    ``plan`` and ``implement`` in the coding graph, or between
    ``decompose`` and ``execute_parallel`` in puppeteer), the LangGraph
    state vanished with the process. HITL-approval resume after a pod
    restart could never work because there was no persisted checkpoint
    to resume from.

Fix:
    Open a ``psycopg_pool.ConnectionPool`` ourselves and pass it to the
    ``PostgresSaver(conn=pool)`` constructor. The pool gives us:

    - Real persistence across worker restarts (the original goal).
    - Automatic reconnect-on-drop (the pool transparently recreates
      connections when Postgres bounces, the worker pod's network blips,
      etc.). This is what a single bare ``Connection`` could not give us.
    - Bounded concurrency (min=1 / max=4 per worker process — sized for
      one orchestrator pod with headroom for parallel graph nodes).

    ``setup()`` is called once on first init; it's idempotent — creates
    the ``checkpoints`` schema if absent, no-ops if present. No Alembic
    migration needed because the saver bootstraps its own tables.

Lifecycle:
    The pool lives at module scope. ``close_checkpointer()`` is called
    from ``__main__.py:main()`` after the graceful drain so the worker
    releases its DB connections cleanly on SIGTERM. Safe to call
    multiple times.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from .config import get_settings

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# Module-level pool holder so close_checkpointer() can release it.
_pg_pool: ConnectionPool | None = None


def create_checkpointer() -> BaseCheckpointSaver:
    """Return a PostgresSaver wired to a real connection pool, else MemorySaver.

    MemorySaver fallback is used in two cases:
      1. ``DATABASE_URL`` is unset (typical local-dev path).
      2. The Postgres init raised — connection refused, schema-setup
         failed, etc. We log loudly in that case so ops can see the
         degraded state instead of silently shipping a worker that
         can't survive a restart.
    """
    global _pg_pool
    settings = get_settings()

    if not settings.database_url:
        logger.info("DATABASE_URL not set, using MemorySaver for checkpointing")
        return MemorySaver()

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        # PostgresSaver uses sync psycopg, not asyncpg.
        db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

        # min_size=1 / max_size=4 sized for one worker pod.
        # autocommit / prepare_threshold=0 / dict_row mirror what
        # langgraph's own from_conn_string contextmanager uses internally.
        pool = cast(
            Any,
            ConnectionPool(
                conninfo=db_url,
                min_size=1,
                max_size=4,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                open=True,
            ),
        )
        # Fail-fast at boot rather than on first task.
        pool.wait(timeout=10.0)

        _pg_pool = pool

        saver = PostgresSaver(conn=pool)
        # Idempotent: creates checkpoints + checkpoint_writes tables.
        saver.setup()

        logger.info(
            "Using PostgresSaver for graph checkpointing "
            "(pool min=1 max=4, durable across worker restarts)"
        )
        return saver
    except Exception:
        logger.error(
            "Failed to initialize PostgresSaver — falling back to MemorySaver. "
            "WARNING: graph state will NOT survive worker restart in this mode. "
            "Investigate and fix; do not leave running in production.",
            exc_info=True,
        )
        if _pg_pool is not None:
            try:
                _pg_pool.close()
            except Exception:
                logger.debug("Error closing partial pool during fallback", exc_info=True)
            _pg_pool = None
        return MemorySaver()


def close_checkpointer() -> None:
    """Close the PostgresSaver connection pool cleanly on worker shutdown.

    Called from ``__main__.py:main()`` after the graceful drain.
    Idempotent and safe even when the worker fell back to MemorySaver.
    """
    global _pg_pool
    if _pg_pool is None:
        return
    try:
        _pg_pool.close()
        logger.info("PostgresSaver connection pool closed cleanly")
    except Exception:
        logger.warning("Error closing PostgresSaver pool", exc_info=True)
    finally:
        _pg_pool = None
