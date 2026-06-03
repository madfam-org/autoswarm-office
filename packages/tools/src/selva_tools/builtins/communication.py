"""Communication tools: notifications and reports."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.notifications")


class SendNotificationTool(BaseTool):
    name = "send_notification"
    description = "Send a notification via email, webhook, or log"

    def parameters_schema(self) -> dict[str, Any]:
        # Email channel is a thin delegate to ``SendEmailTool`` so the
        # voice-mode gate, consent ledger linkage, and server-resolved
        # From: header all apply uniformly. The LLM cannot bypass any
        # of those by picking ``send_notification`` instead of
        # ``send_email``. ``org_id`` is therefore required when the
        # caller selects channel=email; ``webhook_url`` and the log
        # channel keep their original surface.
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification message"},
                "channel": {
                    "type": "string",
                    "description": (
                        "Channel type. ``email`` delegates to send_email "
                        "(voice-mode gated). ``webhook`` posts JSON to "
                        "``webhook_url``. ``log`` is a noop logger."
                    ),
                    "enum": ["log", "webhook", "email"],
                    "default": "log",
                },
                "recipient": {
                    "type": "string",
                    "description": "Recipient email address (required for channel=email).",
                    "default": "",
                },
                "subject": {"type": "string", "default": "Selva Notification"},
                "webhook_url": {"type": "string", "default": ""},
                "org_id": {
                    "type": "string",
                    "description": (
                        "Tenant org_id. REQUIRED when channel=email so "
                        "the delegated send_email call can resolve the "
                        "voice mode + outbound identity."
                    ),
                    "default": "",
                },
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        message = kwargs.get("message", "")
        channel = kwargs.get("channel", "log")
        recipient = kwargs.get("recipient", "")
        subject = kwargs.get("subject", "Selva Notification")
        webhook_url = kwargs.get("webhook_url", "")
        org_id = kwargs.get("org_id", "")
        agent_role = kwargs.get("agent_role")

        if channel == "email":
            return await self._send_email(
                recipient=recipient,
                subject=subject,
                message=message,
                org_id=org_id,
                agent_role=agent_role,
            )
        elif channel == "webhook":
            return await self._send_webhook(webhook_url, message)
        else:
            logger.info("Notification [log] to=%s: %s", recipient or "broadcast", message)
            return ToolResult(
                output=f"Notification logged: {message[:100]}",
                data={"channel": "log", "recipient": recipient, "message": message},
            )

    async def _send_email(
        self,
        *,
        recipient: str,
        subject: str,
        message: str,
        org_id: str,
        agent_role: str | None = None,
    ) -> ToolResult:
        """Delegate the email channel to ``SendEmailTool``.

        This guarantees one — and only one — outbound email gate. The
        previous in-tool Resend call duplicated none of the protections
        in ``SendEmailTool`` (voice-mode lookup, consent-ledger linkage,
        server-resolved From: header, agent-slug allow-list, SPF/DKIM/
        DMARC alignment for ``agent_identified``). An LLM that chose
        ``send_notification`` over ``send_email`` was effectively a free
        bypass of every Wave 3B-A control. Delegating here closes that
        bypass without adding a parallel implementation that could drift
        out of sync.

        ``org_id`` is required for the delegate to resolve voice mode +
        identity; we refuse early when missing rather than letting the
        delegate produce a less-specific error.
        """
        if not recipient:
            return ToolResult(
                success=False,
                error="email channel requires 'recipient'",
            )
        if not org_id:
            return ToolResult(
                success=False,
                error=(
                    "email channel requires 'org_id' so the voice-mode "
                    "gate + tenant identity lookup can resolve."
                ),
            )

        # Late import — keeps the module import graph free of a cycle
        # if email_tools ever needs to reference communication tools.
        from .email_tools import SendEmailTool

        return await SendEmailTool().execute(
            to=recipient,
            subject=subject,
            html=message,
            org_id=org_id,
            agent_role=agent_role,
        )

    async def _send_webhook(self, url: str, message: str) -> ToolResult:
        target = url or os.environ.get("NOTIFICATION_WEBHOOK_URL", "")
        if not target:
            logger.warning("No webhook URL — notification logged only")
            return ToolResult(output="Webhook skipped (no URL)", data={"sent": False})

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(target, json={"text": message})

        if resp.status_code < 300:
            logger.info("Webhook delivered to %s", target[:50])
            return ToolResult(output=f"Webhook sent to {target[:50]}", data={"sent": True})

        logger.error("Webhook failed: %s", resp.status_code)
        return ToolResult(output=f"Webhook failed: {resp.status_code}", data={"sent": False})


class CreateReportTool(BaseTool):
    name = "create_report"
    description = "Create a structured report from provided data"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "Report sections",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "text"],
                    "default": "markdown",
                },
            },
            "required": ["title", "sections"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        title = kwargs.get("title", "Report")
        sections = kwargs.get("sections", [])
        fmt = kwargs.get("format", "markdown")

        if fmt == "markdown":
            lines = [f"# {title}\n"]
            for section in sections:
                lines.append(f"## {section.get('heading', '')}\n")
                lines.append(section.get("content", "") + "\n")
            output = "\n".join(lines)
        elif fmt == "json":
            output = json.dumps({"title": title, "sections": sections}, indent=2)
        else:
            lines = [title, "=" * len(title)]
            for section in sections:
                lines.append(f"\n{section.get('heading', '')}")
                lines.append("-" * len(section.get("heading", "")))
                lines.append(section.get("content", ""))
            output = "\n".join(lines)

        return ToolResult(output=output, data={"title": title, "format": fmt})
