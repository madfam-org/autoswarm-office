"""Outbound fanout for durable task lifecycle notifications."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from selva_redis_pool import get_redis_pool

logger = logging.getLogger(__name__)

_DEFAULT_CHANNEL = "selva:task-notifications"
_WEBHOOK_TIMEOUT_SECONDS = 3.0


def _configured_webhook_urls() -> list[str]:
    raw = os.environ.get("SELVA_TASK_NOTIFICATION_WEBHOOK_URLS", "")
    urls: list[str] = []
    for value in raw.split(","):
        url = value.strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.warning("Ignoring invalid task notification webhook URL: %s", url)
            continue
        urls.append(url)
    return urls


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def publish_task_notification(
    *,
    org_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort fanout for task lifecycle notification events.

    Delivery channels:
    - Redis pub/sub channel `selva:task-notifications` by default.
    - Optional generic HTTP webhooks from `SELVA_TASK_NOTIFICATION_WEBHOOK_URLS`.

    Failures are logged and swallowed so task mutations are never blocked by
    operator-notification delivery.
    """
    message = {
        "schema": "selva.task-notification/v1",
        "org_id": org_id,
        "event_type": event_type,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
    }
    body = json.dumps(message, sort_keys=True, default=str).encode("utf-8")

    try:
        pool = get_redis_pool()
        channel = os.environ.get("SELVA_TASK_NOTIFICATION_REDIS_CHANNEL", _DEFAULT_CHANNEL)
        await pool.execute_with_retry("publish", channel, body.decode("utf-8"))
    except Exception:
        logger.debug("Failed to publish task notification to Redis", exc_info=True)

    urls = _configured_webhook_urls()
    if not urls:
        return

    headers = {"Content-Type": "application/json"}
    secret = os.environ.get("SELVA_TASK_NOTIFICATION_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["X-Selva-Signature"] = _signature(secret, body)

    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
        for url in urls:
            try:
                response = await client.post(url, content=body, headers=headers)
                if response.status_code >= 400:
                    logger.warning(
                        "Task notification webhook %s returned status %s",
                        url,
                        response.status_code,
                    )
            except Exception:
                logger.warning("Task notification webhook %s failed", url, exc_info=True)
