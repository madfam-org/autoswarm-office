from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider
from ..types import InferenceRequest, InferenceResponse

ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
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

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_body(self, request: InferenceRequest, *, stream: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.policy.max_tokens,
            "temperature": request.policy.temperature,
            "messages": request.messages,
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

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        body = self._build_body(request, stream=True)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/messages",
                headers=self._headers(),
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):]
                    if payload.strip() == "[DONE]":
                        break
                    # Parse SSE event - Anthropic sends content_block_delta events
                    import json

                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta.get("text", "")

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
                "claude-sonnet-4-20250514",
                "claude-haiku-4-20250514",
                "claude-opus-4-20250514",
            ]
