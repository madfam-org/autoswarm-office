from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import urllib.parse
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from ..config import get_settings
from ..database import tenant_session
from ..memory_store.db import memory_store
from ..models import ApprovalRequest, GatewayOperatorIdentity, SwarmTask, TaskComment, TaskHistory
from ..tasks.acp_tasks import run_acp_workflow_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gateway", tags=["Gateway"])

# ---------------------------------------------------------------------------
# Private IP ranges that must be blocked to prevent SSRF
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_webhook_url(url: str) -> str:
    """Validate a user-supplied URL to prevent SSRF attacks.

    Checks:
    - Length <= 2048 characters
    - Scheme must be http or https
    - Hostname must resolve to a non-private IP address

    Returns the cleaned URL on success, or raises HTTPException(400) with a
    descriptive reason on failure.

    NOTE: This validator only resolves the hostname *once* at admission time.
    The actual HTTP fetch happens later inside ``run_acp_workflow_task`` (a
    Celery task), which re-resolves the hostname. A malicious DNS server can
    therefore return a public IP at admission and a private IP at fetch time
    (DNS rebinding). Mitigations belong in the Celery task itself --
    pin-to-IP-with-SNI-override (see ``http_tools._resolve_safe_url``) is the
    full fix. Tracked separately; do not rely on this function alone for
    end-to-end SSRF protection of dispatched URLs.
    """
    if len(url) > 2048:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL: exceeds maximum length of 2048 characters",
        )

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL: scheme must be http or https")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: missing hostname")

    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400, detail="Invalid URL: hostname could not be resolved"
        ) from exc

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid URL: hostname resolves to a private/reserved IP address",
                )

    return url


def _require_secret(env_name: str, value: str | None) -> None:
    """Refuse the request with 503 when a webhook secret is unconfigured.

    Use at the top of every handler that authenticates inbound webhooks.
    Matches the Discord/WhatsApp/generic pattern hardened in v2.2.x: an
    unset secret is a misconfiguration, not a license to accept arbitrary
    unauthenticated POSTs.
    """
    if not value:
        logger.error(
            "%s webhook received but %s is unset; refusing to verify",
            env_name.removesuffix("_SECRET").removesuffix("_TOKEN").lower(),
            env_name,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook endpoint not configured",
        )


def _parse_email_address(raw: str) -> str:
    """Extract the bare email address from an RFC 5322 ``From:`` value.

    Inbound parse providers (SendGrid, Postmark, Mailgun) forward the
    raw ``From:`` header verbatim, which can take any of these shapes:

        alice@example.com
        Alice <alice@example.com>
        "Alice, Bob" <alice@example.com>

    Returns the lowercased bare address (``alice@example.com``) so the
    allow-list comparison is normalized. Returns an empty string when the
    input has no parseable address. Display names are intentionally
    discarded — they are attacker-controllable and MUST NOT participate
    in the trust decision.
    """
    if not raw:
        return ""
    _name, addr = email.utils.parseaddr(raw)
    addr = addr.strip().lower()
    # ``email.utils.parseaddr`` is greedy: ``parseaddr("Just a Name")``
    # returns ``("", "Just")``. Require an ``@`` so a malformed/header-only
    # ``From:`` value can't accidentally collide with a malformed allow-list
    # entry. Either side missing means "no usable address".
    return addr if "@" in addr else ""


def _require_inbound_allowlist(env_name: str, allowlist_csv: str | None, sender: str) -> None:
    """Refuse the request when the inbound-sender allow-list is misconfigured
    or the verified sender is not on the list.

    Threat model:
    - Inbound-email parse providers (SendGrid, Postmark, Mailgun, etc.)
      do NOT all share a common HMAC contract, and we accept the same
      payload shape from any of them. The trust signal is therefore the
      ``From:`` address that the upstream provider has *already* validated
      via SPF/DKIM/DMARC at MX time. This helper makes that trust
      decision explicit and fail-closed.
    - The allow-list is the equivalent of a shared secret in the other
      handlers: empty → endpoint disabled (503), not "allow everyone".
      That closes the pre-hardening fail-open bug where
      ``if whitelist and sender not in whitelist:`` accepted any sender
      from the public internet whenever ``GATEWAY_EMAIL_WHITELIST`` was
      unset.
    - Operators MUST front this endpoint with a provider that enforces
      DKIM/SPF/DMARC alignment on inbound mail. Without that upstream
      enforcement, an attacker can spoof an allow-listed ``From:``
      address. (Equivalent assumption to the WeCom/Weixin
      query-token handlers, which trust the upstream provider to deliver
      the token over TLS.)

    Returns 503 when ``allowlist_csv`` is empty/unset (handler disabled).
    Raises 401 when ``sender`` is not on the comma-separated allow-list.
    Comparison is case-insensitive and ignores RFC 5322 display names —
    callers should pre-normalize via ``_parse_email_address``.
    """
    if not allowlist_csv:
        logger.error(
            "email_inbound webhook received but %s is unset; refusing to verify",
            env_name,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook endpoint not configured",
        )

    allowlist = {entry.strip().lower() for entry in allowlist_csv.split(",") if entry.strip()}
    if not allowlist:
        # CSV present but every entry was whitespace -- treat as misconfigured.
        logger.error(
            "email_inbound webhook received but %s contains no usable entries; "
            "refusing to verify",
            env_name,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook endpoint not configured",
        )

    # Defense in depth: normalize the sender side too, even though the
    # canonical caller (``email_inbound``) pre-normalizes via
    # ``_parse_email_address``. A future caller that forgets to normalize
    # still gets correct case-insensitive matching.
    sender_norm = sender.strip().lower()
    if sender_norm not in allowlist:
        logger.warning(
            "email_inbound: rejected sender %r — not on %s allow-list",
            sender,
            env_name,
        )
        raise HTTPException(status_code=401, detail="Sender not authorised")


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification for incoming webhook payloads.

    SECURITY: Refuses verification when the secret is empty. An unconfigured
    secret env var is a misconfiguration, not a license to accept arbitrary
    unauthenticated POSTs from the public internet. Operators MUST set the
    corresponding webhook secret env var (see RUNBOOK / handler docstrings).
    """
    if not secret:
        logger.error(
            "HMAC verification attempted with empty secret -- rejecting. "
            "Set the corresponding webhook secret env var to enable this endpoint."
        )
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


def _trigger_acp_from_gateway(channel: str, actor: str, target_url: str) -> dict[str, Any]:
    """Dispatch an ACP task from a secured gateway channel."""
    target_url = _validate_webhook_url(target_url)
    task = run_acp_workflow_task.delay(target_url)
    memory_store.insert_transcript(
        run_id=task.id,
        agent_role=f"gateway-{channel}",
        role="user",
        content=f"ACP triggered via {channel} from {actor or 'unknown'} for {target_url}",
    )
    logger.info("Gateway (%s): ACP triggered for %s -> task %s", channel, target_url, task.id)
    return {"status": "success", "action": "acp_triggered", "task_id": task.id}


async def _resolve_gateway_operator(channel: str, actor: str) -> GatewayOperatorIdentity | None:
    """Resolve a channel actor to a tenant-bound Selva operator identity."""
    subject = (actor or "").strip()
    if not subject or subject == "unknown":
        return None

    async with tenant_session("platform") as db:
        result = await db.execute(
            select(GatewayOperatorIdentity).where(
                GatewayOperatorIdentity.channel == channel,
                GatewayOperatorIdentity.external_subject == subject,
                GatewayOperatorIdentity.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()


def _approval_payload(req: ApprovalRequest) -> dict[str, Any]:
    """Small approval envelope suitable for chat-channel responses."""
    return {
        "id": str(req.id),
        "agent_id": str(req.agent_id),
        "action_category": req.action_category,
        "action_type": req.action_type,
        "urgency": req.urgency,
        "reasoning": req.reasoning,
        "created_at": req.created_at.isoformat(),
    }


async def _list_gateway_pending_approvals(
    operator: GatewayOperatorIdentity,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """List pending approvals for a mapped gateway operator's tenant."""
    async with tenant_session(operator.org_id) as db:
        result = await db.execute(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.status == "pending",
                ApprovalRequest.org_id == operator.org_id,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
        )
        items = [_approval_payload(req) for req in result.scalars().all()]
    return {"status": "success", "action": "hitl_pending", "items": items, "limit": limit}


async def _resolve_gateway_approval(
    operator: GatewayOperatorIdentity,
    *,
    request_id: str,
    decision: str,
    feedback: str | None,
) -> dict[str, Any]:
    """Resolve a tenant-scoped approval from an authenticated gateway operator."""
    try:
        approval_id = uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid approval UUID") from exc

    async with tenant_session(operator.org_id) as db:
        result = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.org_id == operator.org_id,
            )
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval request not found")
        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Request already resolved with status '{approval.status}'",
            )

        from .approvals import _respond_to_request

        response = await _respond_to_request(
            request_id,
            decision,
            feedback,
            db,
            responded_by=operator.user_sub,
            tenant_org_id=operator.org_id,
        )
    return {
        "status": "success",
        "action": f"hitl_{decision}",
        "approval": response.model_dump(mode="json"),
    }


def _task_summary(task: SwarmTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "kanban_status": task.kanban_status,
        "priority": task.priority,
        "labels": task.labels or [],
        "assigned_agent_ids": task.assigned_agent_ids or [],
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _task_title_from_text(text: str) -> str:
    title = " ".join(text.strip().splitlines()[0].split())
    return (title[:200] if title else "Untitled task")


def _parse_gateway_task_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid task UUID") from exc


def _add_gateway_task_history(
    task: SwarmTask,
    *,
    event_type: str,
    actor_id: str,
    payload: dict[str, Any],
) -> TaskHistory:
    return TaskHistory(
        task_id=task.id,
        org_id=task.org_id,
        event_type=event_type,
        actor_id=actor_id,
        payload=payload,
    )


async def _handle_gateway_task_command(
    operator: GatewayOperatorIdentity,
    command: str,
) -> dict[str, Any]:
    """Execute tenant-bound `/task ...` commands from Harness channels."""
    parts = command.split(maxsplit=2)
    subcommand = parts[1].lower() if len(parts) > 1 else "list"
    rest = parts[2].strip() if len(parts) > 2 else ""

    async with tenant_session(operator.org_id) as db:
        if subcommand in {"list", "ls"}:
            status_filter = rest or None
            query = (
                select(SwarmTask)
                .where(SwarmTask.org_id == operator.org_id)
                .order_by(SwarmTask.updated_at.desc(), SwarmTask.created_at.desc())
                .limit(20)
            )
            if status_filter:
                query = query.where(SwarmTask.kanban_status == status_filter)
            result = await db.execute(query)
            return {
                "status": "success",
                "action": "task_list",
                "tasks": [_task_summary(task) for task in result.scalars().all()],
            }

        if subcommand == "create":
            if not rest:
                return {
                    "status": "error",
                    "action": "task_create",
                    "detail": "usage: /task create <title or title | description>",
                }
            raw_title, sep, raw_description = rest.partition("|")
            title = _task_title_from_text(raw_title)
            description = raw_description.strip() if sep else raw_title.strip()
            task = SwarmTask(
                title=title,
                description=description,
                graph_type="sequential",
                assigned_agent_ids=[],
                payload={"source": "harness", "channel": operator.channel},
                status="pending",
                kanban_status="todo",
                priority="medium",
                labels=["harness"],
                creator_id=operator.user_sub,
                org_id=operator.org_id,
            )
            db.add(task)
            await db.flush()
            db.add(
                _add_gateway_task_history(
                    task,
                    event_type="task.created",
                    actor_id=operator.user_sub,
                    payload={"source": "harness", "title": task.title},
                )
            )
            await db.flush()
            await db.refresh(task)
            return {"status": "success", "action": "task_create", "task": _task_summary(task)}

        if subcommand in {"show", "get"}:
            if not rest:
                return {"status": "error", "action": "task_show", "detail": "task id is required"}
            task_id = _parse_gateway_task_id(rest.split()[0])
            result = await db.execute(
                select(SwarmTask).where(
                    SwarmTask.id == task_id,
                    SwarmTask.org_id == operator.org_id,
                )
            )
            task_obj = result.scalar_one_or_none()
            if task_obj is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return {"status": "success", "action": "task_show", "task": _task_summary(task_obj)}

        if subcommand in {"start", "review", "complete", "done", "block", "move"}:
            tokens = rest.split(maxsplit=2)
            if not tokens:
                return {"status": "error", "action": "task_move", "detail": "task id is required"}
            task_id = _parse_gateway_task_id(tokens[0])
            status_map = {
                "start": "in_progress",
                "review": "review",
                "complete": "done",
                "done": "done",
                "block": "blocked",
            }
            next_status = status_map.get(subcommand)
            note = None
            if subcommand == "move":
                if len(tokens) < 2:
                    return {
                        "status": "error",
                        "action": "task_move",
                        "detail": (
                            "usage: /task move <task_id> "
                            "<todo|in_progress|review|done|blocked>"
                        ),
                    }
                next_status = tokens[1]
                note = tokens[2] if len(tokens) > 2 else None
            elif len(tokens) > 1:
                note = tokens[1] if len(tokens) == 2 else " ".join(tokens[1:])
            if next_status not in {"todo", "in_progress", "review", "done", "blocked"}:
                return {"status": "error", "action": "task_move", "detail": "invalid kanban status"}
            result = await db.execute(
                select(SwarmTask).where(
                    SwarmTask.id == task_id,
                    SwarmTask.org_id == operator.org_id,
                )
            )
            task_obj = result.scalar_one_or_none()
            if task_obj is None:
                raise HTTPException(status_code=404, detail="Task not found")
            old_status = task_obj.kanban_status
            task_obj.kanban_status = next_status
            db.add(
                _add_gateway_task_history(
                    task_obj,
                    event_type="task.kanban_status_changed",
                    actor_id=operator.user_sub,
                    payload={"old_kanban_status": old_status, "new_kanban_status": next_status},
                )
            )
            if note:
                db.add(
                    TaskComment(
                        task_id=task_obj.id,
                        org_id=task_obj.org_id,
                        author_id=operator.user_sub,
                        body=note,
                    )
                )
            await db.flush()
            await db.refresh(task_obj)
            return {"status": "success", "action": "task_move", "task": _task_summary(task_obj)}

        if subcommand in {"comment", "note"}:
            tokens = rest.split(maxsplit=1)
            if len(tokens) < 2:
                return {
                    "status": "error",
                    "action": "task_comment",
                    "detail": "usage: /task comment <task_id> <body>",
                }
            task_id = _parse_gateway_task_id(tokens[0])
            result = await db.execute(
                select(SwarmTask).where(
                    SwarmTask.id == task_id,
                    SwarmTask.org_id == operator.org_id,
                )
            )
            task_obj = result.scalar_one_or_none()
            if task_obj is None:
                raise HTTPException(status_code=404, detail="Task not found")
            comment = TaskComment(
                task_id=task_obj.id,
                org_id=task_obj.org_id,
                author_id=operator.user_sub,
                body=tokens[1],
            )
            db.add(comment)
            await db.flush()
            db.add(
                _add_gateway_task_history(
                    task_obj,
                    event_type="task.comment_added",
                    actor_id=operator.user_sub,
                    payload={"comment_id": str(comment.id)},
                )
            )
            await db.flush()
            return {
                "status": "success",
                "action": "task_comment",
                "comment": {"id": str(comment.id), "task_id": str(task.id), "body": comment.body},
            }

    return {
        "status": "error",
        "action": "task",
        "detail": "unknown task subcommand",
    }


async def _route_harness_command(
    channel: str, text: str, actor: str = "unknown"
) -> dict[str, Any] | None:
    """Route common Harness commands across chat-style gateway adapters.

    This is intentionally small and deterministic. It gives every secured
    channel the same basic control plane while keeping provider-specific
    signature/auth handling inside each adapter.
    """
    command = (text or "").strip()
    if not command:
        return None

    lowered = command.lower()
    if lowered in {"/help", "help"}:
        return {
            "status": "success",
            "action": "help",
            "commands": [
                "acp <url>",
                "/initiate_acp <url>",
                "status [query]",
                "recall <query>",
                "remember <note>",
                "pending",
                "/task list [status]",
                "/task create <title | description>",
                "/task show <id>",
                "/task move <id> <status>",
                "/task comment <id> <body>",
            ],
        }

    for prefix in ("/initiate_acp ", "initiate_acp ", "/acp ", "acp "):
        if lowered.startswith(prefix):
            return _trigger_acp_from_gateway(channel, actor, command[len(prefix) :].strip())

    for prefix in ("/status", "status", "/recall ", "recall "):
        if lowered == prefix or lowered.startswith(prefix + " ") or lowered.startswith(prefix):
            query = command[len(prefix) :].strip() or "acp"
            hits = memory_store.fts_search(query, limit=5)
            return {"status": "success", "action": "memory_recall", "query": query, "results": hits}

    for prefix in ("/remember ", "remember "):
        if lowered.startswith(prefix):
            note = command[len(prefix) :].strip()
            if not note:
                return {"status": "error", "action": "remember", "detail": "note is required"}
            run_id = f"gateway-{channel}"
            memory_store.insert_transcript(
                run_id=run_id,
                agent_role=f"gateway-{channel}",
                role="user",
                content=f"Operator note from {actor or 'unknown'}: {note}",
            )
            return {"status": "success", "action": "remembered", "run_id": run_id}

    if lowered in {"/pending", "pending", "/approvals", "approvals"}:
        operator = await _resolve_gateway_operator(channel, actor)
        if operator is None:
            return _gateway_identity_required("hitl_pending", channel, actor)
        return await _list_gateway_pending_approvals(operator)

    if (
        lowered == "/task"
        or lowered == "task"
        or lowered.startswith("/task ")
        or lowered.startswith("task ")
    ):
        operator = await _resolve_gateway_operator(channel, actor)
        if operator is None:
            return _gateway_identity_required("task", channel, actor)
        task_command = command[1:] if lowered.startswith("/task") else command
        return await _handle_gateway_task_command(operator, task_command)

    if lowered.startswith("/approve ") or lowered.startswith("approve "):
        operator = await _resolve_gateway_operator(channel, actor)
        if operator is None:
            return _gateway_identity_required("hitl_approve", channel, actor)
        request_id = command.split(maxsplit=1)[1].strip()
        return await _resolve_gateway_approval(
            operator,
            request_id=request_id,
            decision="approved",
            feedback=None,
        )

    if lowered.startswith("/deny ") or lowered.startswith("deny "):
        operator = await _resolve_gateway_operator(channel, actor)
        if operator is None:
            return _gateway_identity_required("hitl_deny", channel, actor)
        parts = command.split(maxsplit=2)
        request_id = parts[1].strip()
        feedback = parts[2].strip() if len(parts) > 2 else None
        return await _resolve_gateway_approval(
            operator,
            request_id=request_id,
            decision="denied",
            feedback=feedback,
        )

    return None


def _gateway_identity_required(action: str, channel: str, actor: str) -> dict[str, Any]:
    """Return explicit refusal when a channel actor is not tenant-bound."""
    return {
        "status": "needs_authenticated_bridge",
        "action": action,
        "channel": channel,
        "actor": actor,
        "detail": (
            "HITL approval actions require a tenant-bound gateway operator identity. "
            "Create a gateway_operator_identities row that maps this channel actor "
            "to a Janua/Selva user and org before approving or denying."
        ),
    }


def _verify_signed_relay_request(body: bytes, request: Request, secret: str) -> None:
    """Validate a generic signed relay used by platforms without native code here.

    Accepted forms:
    - Authorization: Bearer <secret>
    - Authorization: HMAC <base64(hmac_sha256(body, secret))>
    - X-Webhook-Signature: sha256=<hex hmac> or bare hex hmac
    """
    authorization = request.headers.get("Authorization", "").strip()
    bearer = authorization.removeprefix("Bearer ").strip()
    if bearer and hmac.compare_digest(bearer, secret):
        return

    if authorization.startswith("HMAC "):
        provided = authorization.removeprefix("HMAC ").strip()
        expected = base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        if hmac.compare_digest(expected, provided):
            return

    signature = request.headers.get("X-Webhook-Signature", "")
    if signature and _verify_hmac(body, signature, secret):
        return

    raise HTTPException(status_code=401, detail="Invalid gateway relay signature")


def _extract_gateway_text(payload: dict[str, Any]) -> str:
    """Extract text from common webhook/relay payload shapes."""
    for key in ("text", "message", "content", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested_message = payload.get("message")
    if isinstance(nested_message, dict):
        for key in ("text", "content", "body"):
            value = nested_message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def _extract_gateway_actor(payload: dict[str, Any]) -> str:
    """Extract a best-effort actor label for transcript/audit context."""
    for key in ("actor", "user", "username", "sender", "from"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("name") or value.get("id") or value.get("username")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return "unknown"


async def _signed_relay_inbound(
    request: Request,
    *,
    channel: str,
    env_name: str,
    secret: str,
) -> dict[str, Any]:
    """Shared Harness relay adapter for Teams, IRC, QQ, Yuanbao, and peers."""
    _require_secret(env_name, secret)
    body = await request.body()
    _verify_signed_relay_request(body, request, secret)
    try:
        payload = json.loads(body)
    except Exception:
        payload = {}

    text = _extract_gateway_text(payload)
    actor = _extract_gateway_actor(payload)
    routed = await _route_harness_command(channel, text, actor)
    if routed:
        return routed
    return {"status": "ignored", "channel": channel}


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
) -> dict[str, Any]:
    """
    Harness communication gateway — Telegram.

    Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (set when
    registering the webhook via ``setWebhook?secret_token=...``) and routes
    the ``/initiate_acp <url>`` slash command to a Celery ACP task.
    """
    settings = get_settings()
    _require_secret("TELEGRAM_WEBHOOK_SECRET", settings.telegram_webhook_secret)
    body = await request.body()

    if not x_telegram_bot_api_secret_token:
        raise HTTPException(status_code=401, detail="Missing Telegram secret token header")
    if not hmac.compare_digest(
        settings.telegram_webhook_secret,
        x_telegram_bot_api_secret_token,
    ):
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

    payload = await request.json() if not body else json.loads(body)
    message = payload.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id", "unknown")

    routed = await _route_harness_command("telegram", text, str(chat_id))
    if routed:
        return routed

    if text.startswith("/initiate_acp"):
        parts = text.split()
        if len(parts) > 1:
            target_url = parts[1]
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-telegram",
                role="user",
                content=f"ACP triggered from Telegram chat {chat_id} for {target_url}",
            )
            logger.info("Gateway (Telegram): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored", "text": text}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


@router.post("/discord/webhook")
async def discord_webhook(
    request: Request,
    x_signature_256: str = Header(None),
) -> dict[str, Any]:
    """
    Harness communication gateway — Discord.

    Validates HMAC-SHA256 signature and handles:
    - ``/status``: returns recent swarm transcript hits from EdgeMemoryDB.
    - ``/initiate_acp <url>``: same trigger as Telegram.

    Requires ``DISCORD_WEBHOOK_SECRET`` env var. Endpoint refuses requests
    when the secret is unset (no fail-open).
    """
    settings = get_settings()
    body = await request.body()

    if not settings.discord_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Discord webhook secret not configured -- endpoint disabled",
        )
    if not x_signature_256:
        raise HTTPException(status_code=401, detail="Missing X-Signature-256 header")
    if not _verify_hmac(body, x_signature_256, settings.discord_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Discord webhook signature")

    payload = json.loads(body)
    content = payload.get("content", "").strip()

    routed = await _route_harness_command("discord", content, _extract_gateway_actor(payload))
    if routed:
        return routed

    if content.startswith("/status"):
        query = content.removeprefix("/status").strip() or "acp"
        hits = memory_store.fts_search(query, limit=5)
        return {
            "status": "success",
            "query": query,
            "results": hits,
        }

    if content.startswith("/initiate_acp"):
        parts = content.split()
        if len(parts) > 1:
            target_url = parts[1]
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-discord",
                role="user",
                content=f"ACP triggered from Discord for {target_url}",
            )
            logger.info("Gateway (Discord): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored", "content": content}


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


@router.post("/slack/webhook")
async def slack_webhook(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
) -> dict[str, Any]:
    """
    Harness communication gateway — Slack.

    Validates Slack's v0 HMAC-SHA256 signature with timestamp replay protection
    (rejects requests older than 5 minutes), then routes slash commands.
    """
    import time as _time

    settings = get_settings()
    _require_secret("SLACK_SIGNING_SECRET", settings.slack_signing_secret)
    body = await request.body()

    if not x_slack_signature or not x_slack_request_timestamp:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    # Replay protection: reject timestamps > 5 minutes old
    try:
        ts = int(x_slack_request_timestamp)
        if abs(_time.time() - ts) > 300:
            raise HTTPException(status_code=401, detail="Slack request timestamp too old")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc

    sig_base = f"v0:{x_slack_request_timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(), sig_base.encode(), hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, x_slack_signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    # Slack sends form-encoded payloads for slash commands
    try:
        form = await request.form()
        text = str(form.get("text", "")).strip()
        command = str(form.get("command", ""))
        user_name = str(form.get("user_name", "unknown"))
    except Exception:
        payload = json.loads(body)
        text = payload.get("text", "")
        command = payload.get("command", "")
        user_name = payload.get("user_name", "unknown")

    routed = await _route_harness_command("slack", f"{command} {text}".strip(), user_name)
    if routed:
        return routed

    if "/initiate_acp" in command or text.startswith("initiate_acp"):
        target_url = text.strip().split()[0] if text.strip() else ""
        if not target_url:
            return {"response_type": "ephemeral", "text": "Usage: /initiate_acp <url>"}

        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-slack",
            role="user",
            content=f"ACP triggered from Slack by @{user_name} for {target_url}",
        )
        logger.info("Gateway (Slack): ACP triggered for %s → task %s", target_url, task.id)
        return {
            "response_type": "ephemeral",
            "text": f"✅ ACP initiated for `{target_url}` (Task `{task.id}`)",
        }

    return {"response_type": "ephemeral", "text": "Unknown command. Try `/initiate_acp <url>`"}


# ---------------------------------------------------------------------------
# Email (SendGrid / Postmark inbound parse)
# ---------------------------------------------------------------------------


@router.post("/email/inbound")
async def email_inbound(request: Request) -> dict[str, Any]:
    """
    Accepts inbound email parse payloads from SendGrid or Postmark.
    Routes commands from allow-listed sender addresses.

    SECURITY (Phase 1 hardening): Unlike the other 14 webhook handlers,
    this endpoint does NOT use a shared HMAC secret -- inbound-email
    parse providers don't share a common signing contract. The trust
    signal is the ``From:`` address that the upstream provider has
    already validated via SPF/DKIM/DMARC at MX time, checked against
    the operator-controlled ``GATEWAY_EMAIL_WHITELIST`` allow-list.

    Fail-closed contract:
    - 503 when ``GATEWAY_EMAIL_WHITELIST`` is unset (endpoint disabled).
      Pre-hardening this would 200 and dispatch an ACP task with an
      attacker-supplied URL because empty allow-list short-circuited
      the membership check.
    - 401 when the parsed ``From:`` address is not on the allow-list.
    - 200 + ``status: ignored`` when the body has no ``initiate_acp:``
      command (so spam / out-of-band mail from allow-listed senders
      doesn't error-loop the upstream provider).

    See ``_require_inbound_allowlist`` for the full threat model.
    """
    settings = get_settings()
    payload = await request.json()

    # SendGrid uses 'from', Postmark uses 'From'. Both forward the raw
    # RFC 5322 header, so strip display names before allow-list matching.
    raw_sender = payload.get("from") or payload.get("From", "")
    sender = _parse_email_address(raw_sender)
    body_text = payload.get("text") or payload.get("TextBody", "")

    _require_inbound_allowlist(
        "GATEWAY_EMAIL_WHITELIST",
        settings.gateway_email_whitelist,
        sender,
    )

    for line in body_text.splitlines():
        line = line.strip()
        routed = await _route_harness_command("email", line, sender)
        if routed:
            return routed
        if line.lower().startswith("initiate_acp:"):
            target_url = line.split(":", 1)[1].strip()
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-email",
                role="user",
                content=f"ACP triggered via email from {sender} for {target_url}",
            )
            logger.info("Gateway (Email): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ---------------------------------------------------------------------------
# Gap 8 — Wave 2 Gateway Platforms
# ---------------------------------------------------------------------------

# ── WhatsApp (Meta Cloud API) ───────────────────────────────────────────────


@router.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(
    request: Request,
) -> Any:
    """
    Responds to the Meta webhook verification challenge (GET request).
    Required during webhook registration in Meta Developer Portal.
    """
    settings = get_settings()
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Gateway (WhatsApp): webhook verification successful.")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(content=challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_inbound(request: Request) -> dict[str, Any]:
    """
    Receive inbound WhatsApp messages via Meta Cloud API webhook.
    Validates X-Hub-Signature-256 and routes /acp commands.

    Requires ``WHATSAPP_ACCESS_TOKEN`` env var (used as the HMAC secret).
    Endpoint refuses requests when the secret is unset.
    """
    settings = get_settings()
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not settings.whatsapp_access_token:
        raise HTTPException(
            status_code=503,
            detail="WhatsApp access token not configured -- endpoint disabled",
        )
    if not _verify_hmac(body, sig, settings.whatsapp_access_token):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature")

    try:
        payload = await request.json()
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        message = changes.get("value", {}).get("messages", [{}])[0]
        text = message.get("text", {}).get("body", "")
        from_number = message.get("from", "unknown")
    except Exception:
        return {"status": "ignored"}

    routed = await _route_harness_command("whatsapp", text, from_number)
    if routed:
        return routed

    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-whatsapp",
            role="user",
            content=f"ACP triggered via WhatsApp from {from_number} for {target_url}",
        )
        logger.info("Gateway (WhatsApp): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ── Matrix / Element (Appservice API) ──────────────────────────────────────


@router.put("/matrix/webhook")
@router.post("/matrix/webhook")
async def matrix_inbound(
    request: Request,
    authorization: str = Header(None),
) -> dict[str, Any]:
    """
    Receive events from a Matrix appservice registration.
    Validates the Authorization: Bearer <token> header.
    """
    settings = get_settings()
    _require_secret("MATRIX_APPSERVICE_TOKEN", settings.matrix_appservice_token)
    if authorization != f"Bearer {settings.matrix_appservice_token}":
        raise HTTPException(status_code=401, detail="Invalid Matrix appservice token")

    try:
        payload = await request.json()
        events = payload.get("events", [])
    except Exception:
        return {"status": "ignored"}

    for event in events:
        if event.get("type") != "m.room.message":
            continue
        content = event.get("content", {})
        msgtype = content.get("msgtype")
        if msgtype != "m.text":
            continue

        text = content.get("body", "")
        sender = event.get("sender", "unknown")

        routed = await _route_harness_command("matrix", text, sender)
        if routed:
            return routed

        if text.lower().startswith("acp "):
            target_url = text[4:].strip()
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-matrix",
                role="user",
                content=f"ACP triggered via Matrix from {sender} for {target_url}",
            )
            logger.info("Gateway (Matrix): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ── Mattermost (Slash Command) ──────────────────────────────────────────────


@router.post("/mattermost/webhook")
async def mattermost_inbound(request: Request) -> dict[str, Any]:
    """
    Receive Mattermost slash command: /initiate_acp <url>.
    Validates the shared mattermost_token from the request body.
    """
    settings = get_settings()
    _require_secret("MATTERMOST_TOKEN", settings.mattermost_token)
    try:
        form = await request.form()
        # Starlette's `form.get()` returns `UploadFile | str | None`; the
        # Mattermost slash-command envelope is always url-encoded form data,
        # so coerce explicitly to keep mypy happy and reject any oddly-typed
        # UploadFile before we try to .strip() it.
        token = str(form.get("token", "") or "")
        text = str(form.get("text", "") or "")
        user_name = str(form.get("user_name", "unknown") or "unknown")
    except Exception:
        return {"status": "ignored"}

    if not hmac.compare_digest(token, settings.mattermost_token):
        raise HTTPException(status_code=401, detail="Invalid Mattermost token")

    routed = await _route_harness_command("mattermost", text, user_name)
    if routed:
        return routed

    target_url = text.strip()
    if not target_url:
        return {"response_type": "ephemeral", "text": "Usage: /initiate_acp <target-url>"}

    target_url = _validate_webhook_url(target_url)
    task = run_acp_workflow_task.delay(target_url)
    memory_store.insert_transcript(
        run_id=task.id,
        agent_role="gateway-mattermost",
        role="user",
        content=f"ACP triggered via Mattermost by {user_name} for {target_url}",
    )
    logger.info("Gateway (Mattermost): ACP triggered for %s → task %s", target_url, task.id)
    return {
        "response_type": "ephemeral",
        "text": f"✅ ACP run queued (`{task.id}`). Phase I analysis starting for `{target_url}`.",
    }


# ── Signal (via signal-cli REST API) ───────────────────────────────────────


@router.post("/signal/webhook")
async def signal_inbound(request: Request) -> dict[str, Any]:
    """
    Receive inbound Signal messages via signal-cli REST API envelope format.
    Validates source number against the configured whitelist.
    """
    settings = get_settings()
    allowed = {n.strip() for n in settings.signal_allowed_numbers.split(",") if n.strip()}

    try:
        payload = await request.json()
        envelope = payload.get("envelope", {})
        source = envelope.get("source", "")
        data_message = envelope.get("dataMessage", {})
        text = data_message.get("message", "")
    except Exception:
        return {"status": "ignored"}

    if allowed and source not in allowed:
        logger.warning("Gateway (Signal): rejected message from non-whitelisted source %s", source)
        raise HTTPException(status_code=403, detail="Signal source not in allowlist")

    routed = await _route_harness_command("signal", text, source)
    if routed:
        return routed

    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-signal",
            role="user",
            content=f"ACP triggered via Signal from {source} for {target_url}",
        )
        logger.info("Gateway (Signal): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ---------------------------------------------------------------------------
# SMS (Twilio)
# ---------------------------------------------------------------------------


@router.post("/sms/inbound")
async def sms_inbound(
    request: Request,
    x_twilio_signature: str = Header(None),
) -> dict[str, Any]:
    """
    Accepts Twilio SMS webhook payloads.
    Validates the X-Twilio-Signature HMAC and routes commands.
    """
    settings = get_settings()
    _require_secret("TWILIO_AUTH_TOKEN", settings.twilio_auth_token)
    body = await request.body()

    try:
        from urllib.parse import parse_qs

        form_data = parse_qs(body.decode(), keep_blank_values=True)
        # Twilio signature = HMAC-SHA1 of URL + sorted params
        url = str(request.url)
        params = "".join(f"{k}{v[0]}" for k, v in sorted(form_data.items()))
        sig_base = (url + params).encode()
        expected = base64.b64encode(
            hmac.new(
                settings.twilio_auth_token.encode(),
                sig_base,
                hashlib.sha1,
            ).digest()
        ).decode()
        if not hmac.compare_digest(expected, x_twilio_signature or ""):
            raise HTTPException(status_code=401, detail="Invalid Twilio signature")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Twilio signature check error: %s", exc)
        raise HTTPException(status_code=401, detail="Twilio signature parse failed") from exc

    try:
        from urllib.parse import parse_qs

        form = parse_qs(body.decode())
        sms_body = form.get("Body", [""])[0].strip()
        from_number = form.get("From", ["unknown"])[0]
    except Exception:
        return {"status": "ignored"}

    routed = await _route_harness_command("sms", sms_body, from_number)
    if routed:
        return routed

    if sms_body.lower().startswith("acp "):
        target_url = sms_body[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-sms",
            role="user",
            content=f"ACP triggered via SMS from {from_number} for {target_url}",
        )
        logger.info("Gateway (SMS): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ===========================================================================
# Gateway Wave 3 — 9 additional platform adapters (Track C)
# Harness adapter coverage: native webhooks where provider contracts are
# stable, and signed relays for platforms that require a bridge service.
# ===========================================================================


@router.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request) -> dict[str, Any]:
    """DingTalk inbound webhook — HMAC-SHA256 validated."""
    settings = get_settings()
    _require_secret("DINGTALK_APP_SECRET", getattr(settings, "dingtalk_app_secret", None))
    await request.body()
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")

    string_to_sign = f"{timestamp}\n{settings.dingtalk_app_secret}"
    expected = base64.b64encode(
        hmac.new(
            settings.dingtalk_app_secret.encode(),
            string_to_sign.encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    if not hmac.compare_digest(expected, sign):
        raise HTTPException(status_code=401, detail="Invalid DingTalk signature")
    try:
        data = await request.json()
        text = data.get("text", {}).get("content", "").strip()
        sender = data.get("senderNick", "unknown")
    except Exception:
        return {"msgtype": "text", "text": {"content": "Parse error"}}
    routed = await _route_harness_command("dingtalk", text, sender)
    if routed:
        return {"msgtype": "text", "text": {"content": json.dumps(routed)}}
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-dingtalk",
            role="user",
            content=f"ACP from DingTalk ({sender}): {target_url}",
        )
        logger.info("Gateway (DingTalk): ACP -> task %s", task.id)
        return {"msgtype": "text", "text": {"content": f"ACP task started: {task.id}"}}
    return {"msgtype": "text", "text": {"content": "Send: acp <url>"}}


@router.post("/feishu/webhook")
async def feishu_webhook(request: Request) -> dict[str, Any]:
    """Feishu (Lark) event webhook — challenge verification + ACP routing."""
    try:
        data = await request.json()
    except Exception:
        return {"code": 1}
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}
    settings = get_settings()
    _require_secret("FEISHU_APP_SECRET", getattr(settings, "feishu_app_secret", None))
    body = await request.body()

    ts = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    sig = request.headers.get("X-Lark-Signature", "")
    sig_input = f"{ts}{nonce}{settings.feishu_app_secret}{body.decode()}"
    computed = hashlib.sha256(sig_input.encode()).hexdigest()
    if not hmac.compare_digest(computed, sig):
        raise HTTPException(status_code=401, detail="Invalid Feishu signature")
    event = data.get("event", {})
    content_str = event.get("message", {}).get("content", "{}")
    try:
        import json as _j

        text = _j.loads(content_str).get("text", "").strip()
    except Exception:
        text = ""
    sender = event.get("sender", {})
    actor = "unknown"
    if isinstance(sender, dict):
        sender_id = sender.get("sender_id", {})
        if isinstance(sender_id, dict):
            actor = str(sender_id.get("open_id") or sender_id.get("union_id") or "unknown")
    routed = await _route_harness_command("feishu", text, actor)
    if routed:
        return {"code": 0, "data": routed}
    if text.lower().startswith("/acp "):
        target_url = text[5:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Feishu): ACP -> task %s", task.id)
    return {"code": 0}


@router.post("/wecom/webhook")
async def wecom_webhook(request: Request) -> dict[str, Any]:
    """WeCom outgoing webhook — token-validated."""
    settings = get_settings()
    _require_secret("WECOM_TOKEN", getattr(settings, "wecom_token", None))
    token = request.query_params.get("token", "")
    if not hmac.compare_digest(settings.wecom_token, token):
        raise HTTPException(status_code=401, detail="Invalid WeCom token")
    try:
        data = await request.json()
        text = data.get("text", {}).get("content", "").strip()
    except Exception:
        return {"errcode": 1, "errmsg": "parse error"}
    routed = await _route_harness_command("wecom", text, data.get("FromUserName", "unknown"))
    if routed:
        return {"errcode": 0, "errmsg": json.dumps(routed)}
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (WeCom): ACP -> task %s", task.id)
    return {"errcode": 0, "errmsg": "ok"}


@router.post("/wecom/callback")
async def wecom_callback(request: Request, echostr: str | None = None) -> Any:
    """WeCom server-mode callback — echoes challenge, logs encrypted messages."""
    if echostr:
        return echostr
    body = await request.body()
    logger.info("Gateway (WeCom Callback): received %d byte payload", len(body))
    return "<xml><return_code>SUCCESS</return_code></xml>"


@router.post("/weixin/webhook")
async def weixin_webhook(request: Request) -> dict[str, Any]:
    """Weixin via WxPusher — appToken validated."""
    settings = get_settings()
    _require_secret("WEIXIN_APP_TOKEN", getattr(settings, "weixin_app_token", None))
    token = request.query_params.get("appToken", "")
    if not hmac.compare_digest(settings.weixin_app_token, token):
        raise HTTPException(status_code=401, detail="Invalid Weixin appToken")
    try:
        data = await request.json()
        content = data.get("content", "").strip()
    except Exception:
        return {"success": False}
    routed = await _route_harness_command("weixin", content, data.get("uid", "unknown"))
    if routed:
        return {"success": True, "data": routed}
    if content.lower().startswith("acp "):
        target_url = content[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Weixin): ACP -> task %s", task.id)
        return {"success": True, "task_id": task.id}
    return {"success": True}


@router.post("/bluebubbles/webhook")
async def bluebubbles_webhook(request: Request) -> dict[str, Any]:
    """BlueBubbles iMessage bridge webhook — password validated."""
    settings = get_settings()
    _require_secret("BLUEBUBBLES_PASSWORD", getattr(settings, "bluebubbles_password", None))
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(f"Basic {settings.bluebubbles_password}", auth.strip()):
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles password")
    try:
        data = await request.json()
        text = data.get("data", {}).get("text", "").strip()
    except Exception:
        return {"status": "ignored"}
    routed = await _route_harness_command(
        "bluebubbles",
        text,
        data.get("data", {}).get("chatGuid", "unknown"),
    )
    if routed:
        return routed
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (BlueBubbles): ACP -> task %s", task.id)
        return {"status": "ok", "task_id": task.id}
    return {"status": "ignored"}


@router.post("/teams/webhook")
async def teams_webhook(request: Request) -> dict[str, Any]:
    """Microsoft Teams inbound webhook or bridge relay — signed and command-routed."""
    settings = get_settings()
    return await _signed_relay_inbound(
        request,
        channel="teams",
        env_name="TEAMS_WEBHOOK_SECRET",
        secret=settings.teams_webhook_secret,
    )


@router.post("/irc/webhook")
async def irc_webhook(request: Request) -> dict[str, Any]:
    """IRC bridge relay — signed and routed into the Harness command surface."""
    settings = get_settings()
    return await _signed_relay_inbound(
        request,
        channel="irc",
        env_name="IRC_WEBHOOK_SECRET",
        secret=settings.irc_webhook_secret,
    )


@router.post("/qq/webhook")
async def qq_webhook(request: Request) -> dict[str, Any]:
    """QQ Bot bridge relay — signed and routed into the Harness command surface."""
    settings = get_settings()
    return await _signed_relay_inbound(
        request,
        channel="qq",
        env_name="QQ_WEBHOOK_SECRET",
        secret=settings.qq_webhook_secret,
    )


@router.post("/yuanbao/webhook")
async def yuanbao_webhook(request: Request) -> dict[str, Any]:
    """Yuanbao bridge relay — signed and routed into the Harness command surface."""
    settings = get_settings()
    return await _signed_relay_inbound(
        request,
        channel="yuanbao",
        env_name="YUANBAO_WEBHOOK_SECRET",
        secret=settings.yuanbao_webhook_secret,
    )


@router.post("/homeassistant/webhook")
async def homeassistant_webhook(request: Request) -> dict[str, Any]:
    """Home Assistant webhook — Bearer long-lived token validated."""
    settings = get_settings()
    _require_secret("HA_TOKEN", getattr(settings, "ha_token", None))
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(settings.ha_token, bearer):
        raise HTTPException(status_code=401, detail="Invalid HA token")
    try:
        data = await request.json()
        message = data.get("message", "").strip()
        entity_id = data.get("entity_id", "unknown")
    except Exception:
        return {"result": "ignored"}
    routed = await _route_harness_command("homeassistant", message, entity_id)
    if routed:
        return routed
    if message.lower().startswith("acp "):
        target_url = message[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (HomeAssistant): entity=%s -> task %s", entity_id, task.id)
        return {"result": "triggered", "task_id": task.id}
    return {"result": "ignored"}


@router.post("/webhook/{channel_id}")
async def generic_webhook(
    channel_id: str,
    request: Request,
    x_webhook_signature: str | None = None,
) -> dict[str, Any]:
    """Generic HMAC-signed webhook. channel_id used for routing/logging.

    Requires ``AUTOSWARM_WEBHOOK_SECRET`` env var. Endpoint refuses requests
    when the secret is unset OR when the X-Webhook-Signature header is missing
    (no fail-open).
    """
    body = await request.body()
    from ..config import get_settings as _get_settings

    secret = _get_settings().autoswarm_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Generic webhook secret not configured -- endpoint disabled",
        )
    if not x_webhook_signature:
        raise HTTPException(status_code=401, detail="Missing X-Webhook-Signature header")
    if not _verify_hmac(body, x_webhook_signature, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        import json as _j

        data = _j.loads(body)
    except Exception:
        data = {}
    text = (data.get("text") or data.get("message") or data.get("content") or "").strip()
    routed = await _route_harness_command(channel_id, text, data.get("actor", "unknown"))
    if routed:
        routed["channel_id"] = channel_id
        return routed
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Webhook/%s): ACP -> task %s", channel_id, task.id)
        return {"status": "ok", "channel_id": channel_id, "task_id": task.id}
    return {"status": "ignored", "channel_id": channel_id}


@router.post("/api/complete")
async def api_complete(request: Request) -> dict[str, Any]:
    """Direct API completion — fire-and-forget ACP dispatch for Harness API mode."""
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
    target_url: str = data.get("target_url", "")
    metadata: dict = data.get("metadata", {})
    if not target_url:
        raise HTTPException(status_code=422, detail="target_url is required")
    target_url = _validate_webhook_url(target_url)
    task = run_acp_workflow_task.delay(target_url, metadata=metadata)
    logger.info("Gateway (API): ACP for %s -> task %s", target_url, task.id)
    return {
        "status": "dispatched",
        "task_id": task.id,
        "target_url": target_url,
        "poll_url": f"/api/v1/acp/status/{task.id}",
    }
