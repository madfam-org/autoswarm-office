"""Inference metering -- records token usage to the billing ledger."""

from __future__ import annotations

import logging

import httpx

from .auth import get_worker_auth_headers
from .config import get_settings

logger = logging.getLogger(__name__)


async def meter_inference_call(
    *,
    usage: dict[str, int],
    provider: str,
    model: str,
    agent_id: str | None = None,
    task_id: str | None = None,
    org_id: str = "default",
) -> None:
    """POST token usage to the nexus-api billing record endpoint.

    This is a fire-and-forget operation -- failures are logged but do not
    propagate so that inference calls are never blocked by metering issues.
    """
    total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    if total_tokens <= 0:
        return

    settings = get_settings()
    payload = {
        "action": "inference",
        "amount": total_tokens,
        "provider": provider,
        "model": model,
        "agent_id": agent_id,
        "task_id": task_id,
        "org_id": org_id,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.nexus_api_url}/api/v1/billing/record",
                json=payload,
                headers=get_worker_auth_headers(org_id=org_id),
            )
            if resp.status_code != 201:
                logger.warning(
                    "Billing record rejected (status %d): %s",
                    resp.status_code,
                    resp.text,
                )
    except Exception:
        logger.warning("Failed to meter inference call", exc_info=True)
