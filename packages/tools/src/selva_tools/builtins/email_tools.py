"""Email tools: send via Resend API, read via IMAP (placeholder).

Every outbound send is gated on the tenant's ``voice_mode``. When the
mode is ``None`` (tenant hasn't completed onboarding) the tool refuses
the call. When the mode is ``agent_identified`` the tool also verifies
SPF/DKIM/DMARC alignment on ``selva.town`` before handing off to Resend.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from ..base import BaseTool, ToolResult
from ._email_signatures import build_identity
from ._spf_check import check_alignment

logger = logging.getLogger("autoswarm.email")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _fetch_voice_mode(org_id: str) -> str | None:
    """Fetch the tenant's outbound voice mode from nexus-api.

    Workers authenticate with ``WORKER_API_TOKEN`` and declare the target
    tenant via the ``X-Selva-Tenant-Org`` header so nexus-api ``auth.py``
    populates ``user["org_id"]`` correctly. Returns ``None`` on any
    error so the caller fails closed (refuses the send rather than
    silently defaulting).
    """
    base_url = os.environ.get("NEXUS_API_URL", "http://localhost:4300")
    token = os.environ.get("WORKER_API_TOKEN", "dev-bypass")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/v1/onboarding/status",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Selva-Tenant-Org": org_id,
                },
            )
            if resp.status_code == 200:
                return resp.json().get("voice_mode")
            logger.warning(
                "voice_mode lookup returned %d org_id=%s",
                resp.status_code,
                org_id,
            )
            return None
    except Exception:
        logger.warning("voice_mode lookup failed org_id=%s", org_id, exc_info=True)
        return None


class SendEmailTool(BaseTool):
    name = "send_email"
    description = (
        "Send an email via the Resend API. "
        "Requires RESEND_API_KEY env var. "
        "Supports HTML body content."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "html": {
                    "type": "string",
                    "description": "HTML body content",
                },
                "org_id": {
                    "type": "string",
                    "description": "Tenant org_id for voice-mode lookup",
                },
                "user_name": {"type": "string"},
                "user_email": {"type": "string"},
                "agent_slug": {"type": "string"},
                "agent_display_name": {"type": "string"},
                "org_name": {"type": "string"},
            },
            "required": ["to", "subject", "html", "org_id", "user_email"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        to = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        html = kwargs.get("html", "")
        org_id = kwargs.get("org_id", "")
        user_name = kwargs.get("user_name", "")
        user_email = kwargs.get("user_email", "")
        agent_slug = kwargs.get("agent_slug")
        agent_display_name = kwargs.get("agent_display_name")
        org_name = kwargs.get("org_name", "")

        if not to:
            return ToolResult(success=False, error="Recipient 'to' is required")
        if not _EMAIL_RE.match(to):
            return ToolResult(success=False, error=f"Invalid email format: {to[:20]}...")
        if not org_id:
            return ToolResult(success=False, error="org_id is required for voice-mode gate")
        if not user_email or not _EMAIL_RE.match(user_email):
            return ToolResult(success=False, error="valid user_email required")

        # -- Voice-mode gate: check BEFORE Resend key so the failure mode
        # is consistent regardless of upstream provider configuration.
        voice_mode = await _fetch_voice_mode(org_id)
        if voice_mode is None:
            return ToolResult(
                success=False,
                error=(
                    "Outbound voice mode not configured. Complete onboarding before sending mail."
                ),
            )

        api_key = os.environ.get("RESEND_API_KEY")
        if not api_key:
            logger.warning("RESEND_API_KEY not configured")
            return ToolResult(
                success=False,
                error="RESEND_API_KEY not configured",
            )

        if voice_mode == "agent_identified":
            alignment = check_alignment("selva.town")
            if not alignment.aligned:
                return ToolResult(
                    success=False,
                    error=(
                        f"agent_identified send blocked: selva.town "
                        f"alignment {alignment.status} — {alignment.reason}"
                    ),
                )

        selva_from = os.environ.get("EMAIL_FROM_SELVA", "noreply@selva.town")
        try:
            identity = build_identity(
                voice_mode=voice_mode,
                user_name=user_name,
                user_email=user_email,
                selva_from=selva_from,
                agent_slug=agent_slug,
                agent_display_name=agent_display_name,
                org_name=org_name,
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        from_address = identity.from_address
        html_body = f"{html}\n{identity.html_signature}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload: dict[str, Any] = {
                    "from": from_address,
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                }
                # user_direct: user's mailbox authors the message. Add
                # Reply-To matching the user so replies route back to them.
                if voice_mode in ("dyad_selva_plus_user", "user_direct"):
                    payload["reply_to"] = user_email
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )

            if resp.status_code in (200, 201):
                message_id = resp.json().get("id", "unknown")
                logger.info("Email sent to=%s id=%s", to, message_id)
                try:
                    from ..service_tracking import emit_service_usage

                    emit_service_usage(
                        "resend",
                        "transactional_email_sent",
                        1,
                        {
                            "to": to,
                            "subject": subject,
                            "message_id": message_id,
                        },
                    )
                except Exception:
                    pass
                return ToolResult(
                    output=f"Email sent to {to} (id={message_id})",
                    data={"message_id": message_id, "to": to, "subject": subject},
                )

            logger.error("Email send failed: %s %s", resp.status_code, resp.text[:200])
            return ToolResult(
                success=False,
                error=f"Resend API error: {resp.status_code} {resp.text[:200]}",
            )
        except Exception as exc:
            logger.error("send_email failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class ReadEmailTool(BaseTool):
    name = "read_email"
    description = (
        "Read emails from a mailbox via IMAP. "
        "Currently a placeholder -- returns an error indicating "
        "IMAP is not configured. Production would use imaplib."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mailbox": {
                    "type": "string",
                    "description": "Mailbox folder to read (e.g. INBOX)",
                    "default": "INBOX",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of recent emails to retrieve",
                    "default": 10,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=False,
            error="IMAP not configured. Set IMAP_HOST, IMAP_USER, IMAP_PASSWORD env vars.",
        )
