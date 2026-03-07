"""Gateway webhook endpoints for external event ingestion.

GitHub webhooks are received here and converted into SwarmTasks
that are enqueued on the Redis task queue.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session_factory
from ..models import SwarmTask
from ..ws import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

# Maps GitHub event + action to a graph type.
_GITHUB_EVENT_MAP: dict[str, str] = {
    "pull_request:opened": "coding",
    "pull_request:synchronize": "coding",
    "pull_request:review_requested": "coding",
    "issues:opened": "research",
    "issues:labeled": "research",
    "check_suite:completed": "coding",
}

MAX_TASKS_PER_WEBHOOK = 5


def _verify_github_signature(
    payload_body: bytes, signature: str, secret: str
) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not secret:
        return True  # No secret configured = skip in dev (production rejects below)
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default="ping"),
    x_hub_signature_256: str = Header(default=""),
) -> dict[str, Any]:
    """Receive GitHub webhook events and convert them to SwarmTasks.

    Supports: pull_request, issues, check_suite, and ping events.
    """
    settings = get_settings()
    body = await request.body()

    # In non-dev environments, a webhook secret must be configured.
    webhook_secret = settings.github_webhook_secret
    if not webhook_secret and settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret not configured",
        )

    # Verify signature if a secret is configured.
    if webhook_secret and not _verify_github_signature(
        body, x_hub_signature_256, webhook_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    if x_github_event == "ping":
        return {"status": "pong"}

    payload = json.loads(body)
    action = payload.get("action", "")
    event_key = f"{x_github_event}:{action}"

    graph_type = _GITHUB_EVENT_MAP.get(event_key)
    if graph_type is None:
        logger.info("Ignoring GitHub event: %s", event_key)
        return {"status": "ignored", "event": event_key}

    # Build task(s) from the webhook payload.
    tasks_created = 0

    async with async_session_factory() as session:
        task = await _create_task_from_github(
            session, x_github_event, action, payload, graph_type
        )
        if task:
            tasks_created = 1

            # Enqueue to Redis for worker consumption.
            try:
                redis_client = aioredis.from_url(
                    settings.redis_url, decode_responses=True
                )
                await redis_client.lpush(
                    "autoswarm:tasks",
                    json.dumps(
                        {
                            "task_id": str(task.id),
                            "graph_type": task.graph_type,
                            "description": task.description,
                            "assigned_agent_ids": task.assigned_agent_ids or [],
                            "payload": task.payload or {},
                        }
                    ),
                )
                await redis_client.aclose()
            except Exception:
                logger.warning("Redis unavailable; task persisted in DB only")
                task.status = "pending"

        await session.commit()

    # Broadcast to connected WebSocket clients.
    if tasks_created > 0:
        await manager.broadcast(
            {
                "type": "wave_incoming",
                "source": "github",
                "task_count": tasks_created,
            }
        )

    return {"status": "ok", "tasks_created": tasks_created}


async def _create_task_from_github(
    session: AsyncSession,
    event_type: str,
    action: str,
    payload: dict[str, Any],
    graph_type: str,
) -> SwarmTask | None:
    """Create a SwarmTask from a GitHub webhook payload."""
    repo_name = payload.get("repository", {}).get("full_name", "unknown")

    if event_type == "pull_request":
        pr = payload.get("pull_request", {})
        description = f"[github] PR #{pr.get('number', '?')}: {pr.get('title', 'N/A')}"
        task_payload = {
            "repo": repo_name,
            "pr_number": pr.get("number"),
            "title": pr.get("title"),
            "author": pr.get("user", {}).get("login"),
            "url": pr.get("html_url"),
            "action": action,
        }
    elif event_type == "issues":
        issue = payload.get("issue", {})
        description = (
            f"[github] Issue #{issue.get('number', '?')}: {issue.get('title', 'N/A')}"
        )
        task_payload = {
            "repo": repo_name,
            "issue_number": issue.get("number"),
            "title": issue.get("title"),
            "author": issue.get("user", {}).get("login"),
            "url": issue.get("html_url"),
            "labels": [
                label.get("name")
                for label in issue.get("labels", [])
                if isinstance(label, dict)
            ],
            "action": action,
        }
    elif event_type == "check_suite":
        check = payload.get("check_suite", {})
        conclusion = check.get("conclusion", "")
        if conclusion != "failure":
            return None  # Only create tasks for failures
        description = f"[github] CI failure on {repo_name}: {check.get('head_branch', 'N/A')}"
        task_payload = {
            "repo": repo_name,
            "branch": check.get("head_branch"),
            "sha": check.get("head_sha"),
            "conclusion": conclusion,
        }
    else:
        return None

    task = SwarmTask(
        description=description,
        graph_type=graph_type,
        payload=task_payload,
        status="queued",
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)

    logger.info("Created task %s from GitHub %s:%s", task.id, event_type, action)
    return task
