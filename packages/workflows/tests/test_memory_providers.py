import os

import pytest

from selva_workflows.memory_provider import (
    RedisMemoryProvider,
    SQLiteMemoryProvider,
    get_memory_provider,
)


@pytest.mark.asyncio
async def test_memory_provider_factory():
    os.environ["SELVA_MEMORY_PROVIDER"] = "sqlite"
    provider = get_memory_provider()
    assert isinstance(provider, SQLiteMemoryProvider)

    os.environ["SELVA_MEMORY_PROVIDER"] = "redis"
    provider = get_memory_provider()
    # If redis not installed, might log warning and return subclass or error
    # For now check if it tries to instantiate Redis
    assert isinstance(provider, RedisMemoryProvider)


@pytest.mark.asyncio
async def test_sqlite_provider_mocked():
    from unittest.mock import MagicMock

    provider = SQLiteMemoryProvider()
    provider._db = MagicMock()

    await provider.insert({"role": "user", "content": "hi"})
    provider._db.insert.assert_called_once()

    provider._db.recall.return_value = ["hi result"]
    res = await provider.recall("hi")
    assert res == ["hi result"]
