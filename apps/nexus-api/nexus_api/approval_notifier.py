"""Redis pub/sub notifier for approval decisions."""

from __future__ import annotations

import json
import logging

from selva_redis_pool import get_redis_pool

logger = logging.getLogger(__name__)


async def notify_approval_decision(
    request_id: str,
    decision: str,
    feedback: str | None = None,
) -> None:
    """Publish an approval decision to the Redis channel for the request.

    Workers subscribe to ``selva:approval:{request_id}`` to receive
    push notifications instead of polling.
    """
    channel = f"selva:approval:{request_id}"
    message = json.dumps(
        {
            "request_id": request_id,
            "result": decision,
            "feedback": feedback,
        }
    )

    try:
        pool = get_redis_pool()
        await pool.execute_with_retry("publish", channel, message)
        logger.info("Published approval decision to %s: %s", channel, decision)
    except Exception:
        logger.warning("Failed to publish approval decision to Redis for %s", request_id)
