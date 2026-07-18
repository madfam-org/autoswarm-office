from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import InferenceProvider, UsageCallback
from ..types import InferenceRequest, InferenceResponse, StreamUsage

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

    @property
    def supports_vision(self) -> bool:
        """Ollama supports vision for models like llava, bakllava, etc."""
        return True

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert multimodal message content to Ollama's format.

        Ollama expects images as a list of base64 strings in an ``images``
        field alongside the ``content`` text field per message.

        - Plain string content is passed through unchanged.
        - List content blocks are split into text (concatenated) and images
          (base64 data extracted into the ``images`` list).
        """
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) or content is None:
                formatted.append(msg)
                continue

            # content is a list of blocks -- extract text and images separately
            text_parts: list[str] = []
            images: list[str] = []
            for block in content:
                block_type = block.get("type", "")
                if block_type == "text":
                    text_parts.append(block.get("content", ""))
                elif block_type == "image_base64":
                    images.append(block["content"])
                elif block_type == "image_url":
                    # Ollama does not natively support image URLs --
                    # include a note in the text as a fallback.
                    text_parts.append(f"[Image: {block['content']}]")

            new_msg: dict[str, Any] = {
                **msg,
                "content": "\n".join(text_parts) if text_parts else "",
            }
            if images:
                new_msg["images"] = images
            formatted.append(new_msg)
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
                f"{self._base_url}/api/chat",
                json=body,
            ) as resp,
        ):
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

                # The final object (done: true) carries the eval counts.
                if data.get("done", False):
                    usage.model = data.get("model") or usage.model
                    if "prompt_eval_count" in data or "eval_count" in data:
                        usage.input_tokens = int(data.get("prompt_eval_count", 0))
                        usage.output_tokens = int(data.get("eval_count", 0))
                        saw_usage = True
                    break

        if on_usage is not None and saw_usage:
            on_usage(usage)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
