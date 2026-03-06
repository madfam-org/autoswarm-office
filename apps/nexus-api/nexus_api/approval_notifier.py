"""Redis pub/sub notifier for approval decisions."""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from .config import get_settings

logger = logging.getLogger(__name__)


async def notify_approval_decision(request_id: str, decision: str, feedback: str | None = None) -> None:
    """Publish an approval decision to the Redis channel for the request.

    Workers subscribe to ``autoswarm:approval:{request_id}`` to receive
    push notifications instead of polling.
    """
    settings = get_settings()
    channel = f"autoswarm:approval:{request_id}"
    message = json.dumps({
        "request_id": request_id,
        "result": decision,
        "feedback": feedback,
    })

    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.publish(channel, message)
        await client.aclose()
        logger.info("Published approval decision to %s: %s", channel, decision)
    except Exception:
        logger.warning("Failed to publish approval decision to Redis for %s", request_id)
