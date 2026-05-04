"""Tests for the checkpointer factory.

The previous version of this file pinned the broken behaviour:
``PostgresSaver.from_conn_string(url)`` called as a regular factory (it's
actually a ``@contextmanager``). The mocks made the bug pass tests, which
is exactly how the silent ``MemorySaver`` fallback shipped to production
unnoticed for months.

This rewrite pins the corrected contract:
- DATABASE_URL set → ``ConnectionPool`` opened, ``PostgresSaver(conn=pool)``
  constructed, ``setup()`` called once.
- DATABASE_URL unset / empty → ``MemorySaver`` (logged at INFO).
- Postgres init failure → ``MemorySaver`` fallback (logged at ERROR so
  ops can see the degraded state).
- ``close_checkpointer()`` releases the pool, is idempotent, and is safe
  in the MemorySaver fallback path.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver


@pytest.fixture(autouse=True)
def _reset_pool_holder():
    """Each test starts with a clean module-level _pg_pool."""
    import selva_workers.checkpointer as cp

    cp._pg_pool = None
    yield
    cp._pg_pool = None


class TestMemorySaverFallback:
    def test_returns_memory_saver_when_no_database_url(self) -> None:
        with patch(
            "selva_workers.checkpointer.get_settings",
            return_value=MagicMock(database_url=None),
        ):
            from selva_workers.checkpointer import create_checkpointer

            saver = create_checkpointer()
            assert isinstance(saver, MemorySaver)

    def test_returns_memory_saver_when_database_url_empty(self) -> None:
        with patch(
            "selva_workers.checkpointer.get_settings",
            return_value=MagicMock(database_url=""),
        ):
            from selva_workers.checkpointer import create_checkpointer

            saver = create_checkpointer()
            assert isinstance(saver, MemorySaver)

    def test_falls_back_to_memory_when_pool_init_raises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Connection refused / DNS failure / etc. → MemorySaver, logged at ERROR."""
        caplog.set_level(logging.ERROR, logger="selva_workers.checkpointer")
        mock_pool_cls = MagicMock(side_effect=RuntimeError("connection refused"))

        with (
            patch(
                "selva_workers.checkpointer.get_settings",
                return_value=MagicMock(database_url="postgresql://user:pass@unreachable/db"),
            ),
            patch.dict(
                "sys.modules",
                {
                    "psycopg_pool": MagicMock(ConnectionPool=mock_pool_cls),
                    "langgraph.checkpoint.postgres": MagicMock(PostgresSaver=MagicMock()),
                    "psycopg.rows": MagicMock(dict_row=MagicMock()),
                },
            ),
        ):
            from selva_workers.checkpointer import create_checkpointer

            saver = create_checkpointer()
            assert isinstance(saver, MemorySaver)
            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert any("Failed to initialize PostgresSaver" in r.message for r in error_records)


class TestPostgresSaverConstruction:
    def test_constructs_pool_and_saver_with_correct_kwargs(self) -> None:
        """Pool MUST use autocommit / prepare_threshold=0 / dict_row.

        Mismatch breaks the saver's prepared-statement caching. Pin them.
        """
        mock_pool_instance = MagicMock()
        mock_pool_cls = MagicMock(return_value=mock_pool_instance)
        mock_saver_instance = MagicMock()
        mock_saver_cls = MagicMock(return_value=mock_saver_instance)
        mock_dict_row = MagicMock()

        with (
            patch(
                "selva_workers.checkpointer.get_settings",
                return_value=MagicMock(
                    database_url="postgresql+asyncpg://user:pass@localhost/db"
                ),
            ),
            patch.dict(
                "sys.modules",
                {
                    "psycopg_pool": MagicMock(ConnectionPool=mock_pool_cls),
                    "langgraph.checkpoint.postgres": MagicMock(PostgresSaver=mock_saver_cls),
                    "psycopg.rows": MagicMock(dict_row=mock_dict_row),
                },
            ),
        ):
            from selva_workers.checkpointer import create_checkpointer

            saver = create_checkpointer()
            assert saver is mock_saver_instance

            mock_pool_cls.assert_called_once()
            call_kwargs = mock_pool_cls.call_args.kwargs
            assert call_kwargs["conninfo"] == "postgresql://user:pass@localhost/db"
            assert call_kwargs["min_size"] == 1
            assert call_kwargs["max_size"] == 4
            assert call_kwargs["open"] is True
            assert call_kwargs["kwargs"]["autocommit"] is True
            assert call_kwargs["kwargs"]["prepare_threshold"] == 0
            assert call_kwargs["kwargs"]["row_factory"] is mock_dict_row

            mock_pool_instance.wait.assert_called_once_with(timeout=10.0)
            mock_saver_cls.assert_called_once_with(conn=mock_pool_instance)
            mock_saver_instance.setup.assert_called_once_with()

    def test_module_pool_holder_is_set_on_success(self) -> None:
        mock_pool_instance = MagicMock()

        with (
            patch(
                "selva_workers.checkpointer.get_settings",
                return_value=MagicMock(database_url="postgresql://x"),
            ),
            patch.dict(
                "sys.modules",
                {
                    "psycopg_pool": MagicMock(
                        ConnectionPool=MagicMock(return_value=mock_pool_instance)
                    ),
                    "langgraph.checkpoint.postgres": MagicMock(PostgresSaver=MagicMock()),
                    "psycopg.rows": MagicMock(dict_row=MagicMock()),
                },
            ),
        ):
            from selva_workers.checkpointer import create_checkpointer

            create_checkpointer()
            import selva_workers.checkpointer as cp
            assert cp._pg_pool is mock_pool_instance


class TestCloseCheckpointer:
    def test_closes_pool_when_set(self) -> None:
        import selva_workers.checkpointer as cp

        mock_pool = MagicMock()
        cp._pg_pool = mock_pool

        from selva_workers.checkpointer import close_checkpointer

        close_checkpointer()
        mock_pool.close.assert_called_once()
        assert cp._pg_pool is None

    def test_idempotent_second_call_is_noop(self) -> None:
        import selva_workers.checkpointer as cp

        mock_pool = MagicMock()
        cp._pg_pool = mock_pool

        from selva_workers.checkpointer import close_checkpointer

        close_checkpointer()
        close_checkpointer()
        mock_pool.close.assert_called_once()

    def test_safe_when_memory_saver_was_used(self) -> None:
        import selva_workers.checkpointer as cp

        cp._pg_pool = None
        from selva_workers.checkpointer import close_checkpointer

        close_checkpointer()  # must not raise

    def test_swallows_close_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A pool.close() that raises must not propagate out of shutdown."""
        caplog.set_level(logging.WARNING, logger="selva_workers.checkpointer")

        import selva_workers.checkpointer as cp

        mock_pool = MagicMock()
        mock_pool.close.side_effect = RuntimeError("network error during close")
        cp._pg_pool = mock_pool

        from selva_workers.checkpointer import close_checkpointer

        close_checkpointer()  # must not raise
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Error closing PostgresSaver pool" in r.message for r in warning_records)
        assert cp._pg_pool is None


class TestFallbackCleansPartialPool:
    def test_partial_pool_closed_on_setup_failure(self) -> None:
        import selva_workers.checkpointer as cp

        mock_pool_instance = MagicMock()
        mock_saver_instance = MagicMock()
        mock_saver_instance.setup.side_effect = RuntimeError("schema migration failed")

        with (
            patch(
                "selva_workers.checkpointer.get_settings",
                return_value=MagicMock(database_url="postgresql://x"),
            ),
            patch.dict(
                "sys.modules",
                {
                    "psycopg_pool": MagicMock(
                        ConnectionPool=MagicMock(return_value=mock_pool_instance)
                    ),
                    "langgraph.checkpoint.postgres": MagicMock(
                        PostgresSaver=MagicMock(return_value=mock_saver_instance)
                    ),
                    "psycopg.rows": MagicMock(dict_row=MagicMock()),
                },
            ),
        ):
            from selva_workers.checkpointer import create_checkpointer

            saver = create_checkpointer()
            assert isinstance(saver, MemorySaver)
            mock_pool_instance.close.assert_called_once()
            assert cp._pg_pool is None
