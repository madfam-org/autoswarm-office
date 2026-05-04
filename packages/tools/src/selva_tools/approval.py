"""
Gap 2: Dangerous Command Approval System

Mirrors Hermes Agent's tools/approval.py design.
Provides pre-execution pattern matching and an async HITL approval gate
for destructive shell or Python commands dispatched inside ACP runs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dangerous pattern catalogue (aligned with Hermes Agent tools/approval.py)
# ---------------------------------------------------------------------------

_RAW_PATTERNS = [
    # Destructive filesystem ops
    r"rm\s+(-\w*r\w*|-\w*f\w*|--recursive|--force)",
    r"rm\s+.*\s+/",
    r"find\s+.*(-exec\s+rm|-delete)",
    r"xargs\s+rm",
    # Permissions escalation
    r"chmod\s+(777|666|o\+w|a\+w|--recursive)",
    r"chown\s+(-R|--recursive)\s+root",
    # Disk / partition ops
    r"mkfs",
    r"dd\s+if=",
    r">\s*/dev/sd",
    # Database destruction
    r"DROP\s+(TABLE|DATABASE)",
    r"DELETE\s+FROM",
    r"TRUNCATE\s+TABLE",
    # System file writes
    r">\s*/etc/",
    r"tee\s+/etc/",
    r"sed\s+(-i|--in-place)\s+.*\s+/etc/",
    r"(cp|mv|install)\s+.*\s+/etc/",
    r">\s*~/.ssh/",
    # Service management
    r"systemctl\s+(stop|disable|mask)",
    # Process kills
    r"kill\s+-9\s+-1",
    r"pkill\s+-9",
    r"pkill\b",
    r"killall\b",
    # Remote code execution
    r"(curl|wget).*\|\s*(sh|bash|zsh)",
    r"bash\s+<\(curl",
    r"sh\s+<\(wget",
    # Inline script execution
    r"(bash|sh|zsh|ksh)\s+-c",
    r"python\s+-[ce]",
    r"perl\s+-e",
    r"ruby\s+-e",
    r"node\s+-e",
    # Background detachment
    r"nohup\b",
    r"setsid\b",
    r"disown\b",
]

DANGEROUS_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in _RAW_PATTERNS]


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


def is_dangerous(command: str) -> tuple[bool, str]:
    """
    Check *command* against the dangerous pattern catalogue.

    Returns:
        (True, reason_string) if dangerous, (False, "") otherwise.
    """
    for pattern in DANGEROUS_PATTERNS:
        m = pattern.search(command)
        if m:
            return True, f"Matched dangerous pattern: {pattern.pattern!r} at '{m.group()}'"
    return False, ""


# ---------------------------------------------------------------------------
# Approval result
# ---------------------------------------------------------------------------


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalResult:
    status: ApprovalStatus
    request_id: str
    command: str
    reason: str
    resolved_by: str | None = None
    elapsed_s: float = 0.0

    @property
    def approved(self) -> bool:
        return self.status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# In-process approval store (Redis-backed in production)
# ---------------------------------------------------------------------------

_PENDING: dict[str, ApprovalResult] = {}


def _resolve(request_id: str, status: ApprovalStatus, resolved_by: str = "system") -> None:
    """Resolve a pending approval (called from the API router)."""
    if request_id in _PENDING:
        _PENDING[request_id].status = status
        _PENDING[request_id].resolved_by = resolved_by


async def request_approval(
    command: str,
    run_id: str,
    reason: str,
    timeout_s: int | None = None,
) -> ApprovalResult:
    """
    Insert an approval request and block until a human approves/denies it
    or the timeout expires (fail-closed on timeout).

    If AUTO_APPROVE=true is set, immediately approve without blocking.
    """
    from nexus_api.config import get_settings

    settings = get_settings()

    # CI / auto-approve bypass
    if settings.auto_approve_dangerous or os.environ.get("AUTO_APPROVE", "").lower() == "true":
        logger.warning("AUTO_APPROVE: bypassing dangerous command gate for run %s", run_id)
        return ApprovalResult(
            status=ApprovalStatus.APPROVED,
            request_id="auto",
            command=command,
            reason=reason,
            resolved_by="AUTO_APPROVE",
        )

    timeout_s = timeout_s or settings.command_approval_timeout_seconds
    request_id = str(uuid.uuid4())
    result = ApprovalResult(
        status=ApprovalStatus.PENDING,
        request_id=request_id,
        command=command,
        reason=reason,
    )
    _PENDING[request_id] = result

    # Persist to DB and broadcast via Redis pub/sub
    await _persist_and_broadcast(request_id, run_id, command, reason)

    # Poll until resolved or timeout
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        await asyncio.sleep(1)
        current = _PENDING.get(request_id)
        if current and current.status != ApprovalStatus.PENDING:
            current.elapsed_s = time.monotonic() - start
            _PENDING.pop(request_id, None)
            return current

    # Timeout — fail closed
    result.status = ApprovalStatus.EXPIRED
    result.elapsed_s = timeout_s
    _PENDING.pop(request_id, None)
    logger.warning(
        "Approval request %s expired after %ss — command DENIED (fail-closed).",
        request_id,
        timeout_s,
    )
    return result


async def _persist_and_broadcast(request_id: str, run_id: str, command: str, reason: str) -> None:
    """Persist approval request to Postgres and broadcast to Redis pub/sub."""
    try:
        from datetime import datetime

        from nexus_api.database import async_session_factory
        from nexus_api.models import ApprovalStatus as DBStatus
        from nexus_api.models import CommandApprovalRequest as ApprovalRequest

        async with async_session_factory() as session:
            req = ApprovalRequest(
                id=request_id,
                run_id=run_id,
                command=command,
                reason=reason,
                status=DBStatus.PENDING,
                requested_at=datetime.now(tz=UTC),
            )
            session.add(req)
            await session.commit()
    except Exception as exc:
        logger.warning("Could not persist approval request to DB: %s", exc)

    try:
        import json

        from nexus_api.redis_pool import get_redis

        redis = await get_redis()
        await redis.publish(
            "autoswarm:approval_requests",
            json.dumps(
                {
                    "id": request_id,
                    "run_id": run_id,
                    "command": command[:200],
                    "reason": reason,
                }
            ),
        )
    except Exception as exc:
        logger.warning("Could not broadcast approval request via Redis: %s", exc)


def resolve_approval(request_id: str, approved: bool, resolved_by: str = "api") -> bool:
    """Called by the REST API router to resolve a pending approval."""
    if request_id not in _PENDING:
        return False
    _resolve(
        request_id,
        ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
        resolved_by=resolved_by,
    )
    return True
