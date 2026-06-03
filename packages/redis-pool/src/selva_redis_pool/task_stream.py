"""Redis Streams-based task queue for durable task processing."""

from __future__ import annotations

import json
import logging
import os
import socket
from typing import Any

from .pool import get_redis_pool

logger = logging.getLogger(__name__)

STREAM_KEY = "selva:task-stream"
DLQ_KEY = "selva:task-dlq"
GROUP_NAME = "selva-workers"
MAX_RETRIES = 3


def _default_consumer_name() -> str:
    """Generate a consumer name from hostname and PID."""
    return f"{socket.gethostname()}-{os.getpid()}"


class TaskStreamProducer:
    """Publishes tasks to the Redis Stream."""

    def __init__(self, stream_key: str = STREAM_KEY) -> None:
        self._stream_key = stream_key

    async def enqueue(self, task_data: dict[str, Any]) -> str:
        """Add a task to the stream. Returns the stream message ID."""
        pool = get_redis_pool()
        raw = json.dumps(task_data)
        msg_id = await pool.execute_with_retry("xadd", self._stream_key, {"data": raw})
        logger.info(
            "Enqueued task %s to stream (msg_id=%s)",
            task_data.get("task_id", "?"),
            msg_id,
        )
        return str(msg_id)


class TaskStreamConsumer:
    """Reads tasks from the Redis Stream using consumer groups."""

    def __init__(
        self,
        stream_key: str = STREAM_KEY,
        group_name: str = GROUP_NAME,
        consumer_name: str | None = None,
    ) -> None:
        self._stream_key = stream_key
        self._group_name = group_name
        self._consumer_name = consumer_name or _default_consumer_name()

    async def ensure_group(self) -> None:
        """Create the consumer group if it doesn't exist."""
        pool = get_redis_pool()
        client = await pool.client()
        try:
            await client.xgroup_create(self._stream_key, self._group_name, id="0", mkstream=True)
            logger.info(
                "Created consumer group '%s' on '%s'",
                self._group_name,
                self._stream_key,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                pass  # Group already exists
            else:
                raise

    async def read(self, count: int = 1, block: int = 5000) -> list[tuple[str, dict[str, Any]]]:
        """Read pending messages from the stream.

        Returns list of (message_id, task_data) tuples.
        """
        pool = get_redis_pool()
        client = await pool.client()
        results = await client.xreadgroup(
            groupname=self._group_name,
            consumername=self._consumer_name,
            streams={self._stream_key: ">"},
            count=count,
            block=block,
        )
        if not results:
            return []

        messages: list[tuple[str, dict[str, Any]]] = []
        for _stream_name, stream_messages in results:
            for msg_id, fields in stream_messages:
                try:
                    task_data = json.loads(fields["data"])
                    messages.append((msg_id, task_data))
                except (KeyError, json.JSONDecodeError) as exc:
                    logger.error("Bad message %s in stream: %s", msg_id, exc)
                    await self.ack(msg_id)
        return messages

    async def ack(self, message_id: str) -> None:
        """Acknowledge a message as successfully processed."""
        pool = get_redis_pool()
        await pool.execute_with_retry("xack", self._stream_key, self._group_name, message_id)

    async def claim_stalled(self, min_idle_time: int = 60000) -> list[tuple[str, dict[str, Any]]]:
        """Claim stalled messages from other consumers (crash recovery).

        Args:
            min_idle_time: Minimum idle time in milliseconds.
        """
        pool = get_redis_pool()
        client = await pool.client()
        try:
            result = await client.xautoclaim(
                self._stream_key,
                self._group_name,
                self._consumer_name,
                min_idle_time=min_idle_time,
                start_id="0-0",
                count=10,
            )
            if not result or not result[1]:
                return []

            messages: list[tuple[str, dict[str, Any]]] = []
            for msg_id, fields in result[1]:
                if fields:
                    try:
                        task_data = json.loads(fields["data"])
                        messages.append((msg_id, task_data))
                    except (KeyError, json.JSONDecodeError):
                        logger.error("Bad stalled message %s", msg_id)
                        await self.ack(msg_id)
            if messages:
                logger.info("Claimed %d stalled messages", len(messages))
            return messages
        except Exception as exc:
            logger.warning("Failed to claim stalled messages: %s", exc)
            return []

    async def retry_count(self, message_id: str) -> int:
        """Get the delivery count for a message."""
        pool = get_redis_pool()
        client = await pool.client()
        try:
            pending = await client.xpending_range(
                self._stream_key, self._group_name, message_id, message_id, 1
            )
            if pending:
                return int(pending[0].get("times_delivered", 0))
        except Exception:
            pass
        return 0

    async def move_to_dlq(self, message_id: str, task_data: dict[str, Any], error: str) -> None:
        """Move a failed message to the dead letter queue."""
        pool = get_redis_pool()
        dlq_data = json.dumps({**task_data, "error": error, "original_id": message_id})
        await pool.execute_with_retry("xadd", DLQ_KEY, {"data": dlq_data})
        await self.ack(message_id)
        logger.warning(
            "Task %s moved to DLQ after max retries (msg_id=%s)",
            task_data.get("task_id", "?"),
            message_id,
        )
