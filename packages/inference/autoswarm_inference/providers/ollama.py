from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider
from ..types import InferenceRequest, InferenceResponse

OLLAMA_DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class OllamaProvider(InferenceProvider):
    """Inference provider for the Ollama local REST API.

    Ollama runs models locally, making it suitable for restricted and
    confidential data that must not leave the machine.

    API reference: https://github.com/ollama/ollama/blob/main/docs/api.md
    """

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = OLLAMA_DEFAULT_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 300.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def _build_body(
        self, request: InferenceRequest, *, stream: bool = False
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "options": {
                "num_predict": request.policy.max_tokens,
                "temperature": request.policy.temperature,
            },
        }
        if request.tools:
            body["tools"] = request.tools
        return body

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        body = self._build_body(request, stream=False)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})

        # Ollama returns tool calls in the message when tools are provided
        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = message["tool_calls"]

        # Ollama reports token counts at the top level
        return InferenceResponse(
            content=message.get("content", ""),
            model=data.get("model", self._model),
            provider=self.name,
            usage={
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
            },
            tool_calls=tool_calls,
        )

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        body = self._build_body(request, stream=True)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Ollama streams JSON objects, one per line.
                    # Each has a "message" field with partial content.
                    message = data.get("message", {})
                    content = message.get("content", "")
                    if content:
                        yield content

                    # The final object has "done": true
                    if data.get("done", False):
                        break

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
