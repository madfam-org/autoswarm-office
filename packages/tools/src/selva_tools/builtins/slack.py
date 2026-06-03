"""Slack messaging tool for agent-to-human communication."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.slack")


class SlackMessageTool(BaseTool):
    name = "slack_message"
    description = "Send a message to a Slack channel"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Slack channel name or ID (e.g., #alerts-critical, #deploys)",
                },
                "message": {
                    "type": "string",
                    "description": "Message text (supports Slack markdown)",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Thread timestamp to reply in a thread (optional)",
                    "default": "",
                },
            },
            "required": ["channel", "message"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        channel = kwargs.get("channel", "")
        message = kwargs.get("message", "")
        thread_ts = kwargs.get("thread_ts", "")

        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            logger.warning("SLACK_BOT_TOKEN not configured — message logged only")
            logger.info("Slack [%s]: %s", channel, message[:200])
            return ToolResult(
                output=f"Slack message logged (no token): {channel}",
                data={"sent": False, "channel": channel},
            )

        payload: dict[str, Any] = {
            "channel": channel,
            "text": message,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json=payload,
            )

        data = resp.json()
        if data.get("ok"):
            ts = data.get("ts", "")
            logger.info("Slack message sent to %s (ts=%s)", channel, ts)
            return ToolResult(
                output=f"Message sent to {channel}",
                data={"sent": True, "channel": channel, "ts": ts},
            )

        error = data.get("error", "unknown")
        logger.error("Slack API error: %s", error)
        return ToolResult(
            output=f"Slack error: {error}",
            data={"sent": False, "error": error},
        )
