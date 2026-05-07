"""Periodic overdue-notification scan for kanban tasks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..auth import get_worker_auth_headers
from ..config import get_settings

logger = logging.getLogger(__name__)


async def run(settings: Any | None = None) -> dict[str, int]:
    """Call the Nexus API cross-tenant overdue scan endpoint."""
    settings = settings or get_settings()
    url = f"{settings.nexus_api_url.rstrip('/')}/api/v1/swarms/tasks/notify-overdue-all"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=get_worker_auth_headers())
        response.raise_for_status()
        data = response.json()
    return {
        "scanned": int(data.get("scanned", 0)),
        "notified": int(data.get("notified", 0)),
    }


async def periodic_loop(shutdown: asyncio.Event) -> None:
    """Run the overdue scan on the configured worker interval."""
    settings = get_settings()
    interval = int(settings.kanban_overdue_scan_interval_seconds)
    if interval <= 0:
        logger.info("Kanban overdue scan disabled")
        return

    while not shutdown.is_set():
        try:
            summary = await run(settings)
            if summary["scanned"] or summary["notified"]:
                logger.info(
                    "kanban overdue scan tick: scanned=%d notified=%d",
                    summary["scanned"],
                    summary["notified"],
                )
        except Exception:
            logger.exception("Kanban overdue scan tick failed")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except TimeoutError:
            continue
