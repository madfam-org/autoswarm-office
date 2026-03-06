from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider
from ..types import InferenceRequest, InferenceResponse

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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(self, request: InferenceRequest, *, stream: bool = False) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": request.policy.max_tokens,
            "temperature": request.policy.temperature,
        }
        if request.tools:
            body["tools"] = request.tools
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

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        body = self._build_body(request, stream=True)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
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
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = event.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/models",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []))
