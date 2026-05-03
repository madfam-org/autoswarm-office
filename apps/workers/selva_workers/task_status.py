"""Task status updates -- PATCH task lifecycle to nexus-api."""

from __future__ import annotations

import logging

from .auth import get_worker_auth_headers
from .http_retry import fire_and_forget_request

logger = logging.getLogger(__name__)


async def update_task_status(
    nexus_url: str,
    task_id: str,
    status: str,
    result: dict | None = None,
    started_at: str | None = None,
    error_message: str | None = None,
    org_id: str | None = None,
) -> None:
    """PATCH task status to the nexus-api.

    Fire-and-forget with retry: failures are logged but never raised, matching
    the same resilience pattern used by ``metering.py``.

    Args:
        org_id: Target tenant org_id, propagated to nexus-api via the
            ``X-Selva-Tenant-Org`` header. When omitted the call resolves
            to ``platform`` scope on the API side, which is incorrect for
            tenant-owned task records — callers SHOULD pass ``task.org_id``.
    """
    if task_id == "unknown":
        return
    body: dict = {"status": status}
    if result is not None:
        body["result"] = result
    if started_at is not None:
        body["started_at"] = started_at
    if error_message is not None:
        body["error_message"] = error_message

    url = f"{nexus_url}/api/v1/swarms/tasks/{task_id}"
    success = await fire_and_forget_request(
        "PATCH",
        url,
        json=body,
        headers=get_worker_auth_headers(org_id=org_id),
        timeout=5.0,
    )
    if not success:
        logger.warning("Failed to update task %s status to %s after retries", task_id, status)
