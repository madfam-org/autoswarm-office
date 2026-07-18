from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider, UsageCallback
from ..types import InferenceRequest, InferenceResponse, StreamUsage

ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-sonnet-4-6"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(InferenceProvider):
    """Inference provider for the Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = ANTHROPIC_API_URL,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def supports_vision(self) -> bool:
        """Anthropic Claude models support vision natively."""
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert multimodal message content to Anthropic's native format.

        - Plain string content is wrapped as ``[{"type": "text", "text": ...}]``.
        - List content blocks are converted:
          - ``text`` blocks -> ``{"type": "text", "text": ...}``
          - ``image_base64`` blocks -> ``{"type": "image", "source":
            {"type": "base64", "media_type": ..., "data": ...}}``
          - ``image_url`` blocks -> ``{"type": "image", "source":
            {"type": "url", "url": ...}}``
        """
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) or content is None:
                text = content or ""
                formatted.append(
                    {
                        **msg,
                        "content": [{"type": "text", "text": text}],
                    }
                )
                continue

            # content is a list of blocks
            anthropic_blocks: list[dict[str, Any]] = []
            for block in content:
                block_type = block.get("type", "")
                if block_type == "text":
                    anthropic_blocks.append({"type": "text", "text": block["content"]})
                elif block_type == "image_base64":
                    mime = block.get("mime_type", "image/png")
                    anthropic_blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": block["content"],
                            },
                        }
                    )
                elif block_type == "image_url":
                    anthropic_blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": block["content"],
                            },
                        }
                    )
                else:
                    if "content" in block:
                        anthropic_blocks.append({"type": "text", "text": block["content"]})

            formatted.append({**msg, "content": anthropic_blocks})
        return formatted

    def _build_body(self, request: InferenceRequest, *, stream: bool = False) -> dict[str, Any]:
        messages = self._format_messages(request.messages)
        model = request.policy.model_override or self._model
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": request.policy.max_tokens,
            "temperature": request.policy.temperature,
            "messages": messages,
        }
        if request.system_prompt:
            body["system"] = request.system_prompt
        if request.tools:
            body["tools"] = request.tools
        if stream:
            body["stream"] = True
        return body

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        body = self._build_body(request)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/messages",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract text from content blocks
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        usage_data = data.get("usage", {})
        return InferenceResponse(
            content="".join(text_parts),
            model=data.get("model", self._model),
            provider=self.name,
            usage={
                "input_tokens": usage_data.get("input_tokens", 0),
                "output_tokens": usage_data.get("output_tokens", 0),
            },
            tool_calls=tool_calls if tool_calls else None,
        )

    async def stream(
        self,
        request: InferenceRequest,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]:
        body = self._build_body(request, stream=True)

        usage = StreamUsage()
        saw_usage = False
        async with (
            httpx.AsyncClient(timeout=self._timeout) as client,
            client.stream(
                "POST",
                f"{self._base_url}/messages",
                headers=self._headers(),
                json=body,
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload.strip() == "[DONE]":
                    break
                # Parse SSE event - Anthropic sends content_block_delta events
                import json

                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta.get("text", "")
                elif event_type == "message_start":
                    # Carries the resolved model + input token count.
                    message = event.get("message", {})
                    usage.model = message.get("model") or usage.model
                    start_usage = message.get("usage", {})
                    if "input_tokens" in start_usage:
                        usage.input_tokens = int(start_usage["input_tokens"])
                        saw_usage = True
                elif event_type == "message_delta":
                    # usage.output_tokens here is cumulative — last one wins.
                    delta_usage = event.get("usage", {})
                    if "output_tokens" in delta_usage:
                        usage.output_tokens = int(delta_usage["output_tokens"])
                        saw_usage = True

        if on_usage is not None and saw_usage:
            on_usage(usage)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/models",
                headers=self._headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return [m["id"] for m in data.get("data", [])]
            # Fallback to known models if endpoint not available
            return [
                "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001",
                "claude-opus-4-7",
            ]
