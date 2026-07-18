from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider, UsageCallback
from ..types import InferenceRequest, InferenceResponse, StreamUsage

OPENAI_API_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(InferenceProvider):
    """Inference provider for OpenAI-compatible chat completion APIs.

    Works with the official OpenAI API and any service that implements
    the same /v1/chat/completions interface.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = OPENAI_API_URL,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def supports_vision(self) -> bool:
        """OpenAI models (gpt-4o, gpt-4-turbo, etc.) support vision."""
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert multimodal message content to OpenAI's format.

        - Plain string content is passed through unchanged.
        - List content blocks are converted:
          - ``text`` blocks -> ``{"type": "text", "text": ...}``
          - ``image_url`` blocks -> ``{"type": "image_url", "image_url": {"url": ...}}``
          - ``image_base64`` blocks -> ``{"type": "image_url", "image_url": {"url":
            "data:{mime};base64,{data}"}}``
        """
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) or content is None:
                formatted.append(msg)
                continue

            # content is a list of blocks
            openai_blocks: list[dict[str, Any]] = []
            for block in content:
                block_type = block.get("type", "")
                if block_type == "text":
                    openai_blocks.append({"type": "text", "text": block["content"]})
                elif block_type == "image_url":
                    openai_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": block["content"]},
                        }
                    )
                elif block_type == "image_base64":
                    mime = block.get("mime_type", "image/png")
                    data_uri = f"data:{mime};base64,{block['content']}"
                    openai_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        }
                    )
                else:
                    # Unknown block type -- pass through as text if it has content
                    if "content" in block:
                        openai_blocks.append({"type": "text", "text": block["content"]})

            formatted.append({**msg, "content": openai_blocks})
        return formatted

    def _build_body(self, request: InferenceRequest, *, stream: bool = False) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        messages = self._format_messages(messages)

        model = request.policy.model_override or self._model
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.policy.max_tokens,
            "temperature": request.policy.temperature,
        }
        if request.tools:
            body["tools"] = request.tools
        if request.response_format:
            body["response_format"] = request.response_format
        if stream:
            body["stream"] = True
        return body

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        body = self._build_body(request)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": tc["type"],
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in message["tool_calls"]
            ]

        usage_data = data.get("usage", {})
        return InferenceResponse(
            content=message.get("content", ""),
            model=data.get("model", self._model),
            provider=self.name,
            usage={
                "input_tokens": usage_data.get("prompt_tokens", 0),
                "output_tokens": usage_data.get("completion_tokens", 0),
            },
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        request: InferenceRequest,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]:
        body = self._build_body(request, stream=True)
        # Ask for the final usage chunk (an extra terminal event with empty
        # choices and a populated "usage"). Part of the OpenAI streaming spec
        # and supported by the OpenAI-compatible gateways we route to
        # (DeepInfra, OpenRouter); servers that don't know it ignore it.
        body["stream_options"] = {"include_usage": True}

        usage = StreamUsage()
        saw_usage = False
        async with (
            httpx.AsyncClient(timeout=self._timeout) as client,
            client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
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
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                usage.model = event.get("model") or usage.model
                event_usage = event.get("usage")
                if event_usage:
                    # OpenAI wire keys — normalize to the provider contract.
                    usage.input_tokens = int(event_usage.get("prompt_tokens", 0))
                    usage.output_tokens = int(event_usage.get("completion_tokens", 0))
                    saw_usage = True

                choices = event.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

        if on_usage is not None and saw_usage:
            on_usage(usage)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/models",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []))
