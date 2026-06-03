"""
Track B5: image_gen — DALL-E 3 image generation tool.
Track B6: tts — OpenAI TTS tool.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# B5 — Image Generation
# ---------------------------------------------------------------------------


class GenerateImageTool(BaseTool):
    """Generate an image from a text prompt using DALL-E 3."""

    name = "generate_image"
    description = (
        "Generate an image from a text prompt using DALL-E 3. "
        "Returns the image URL and optionally saves it to disk."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Image generation prompt"},
                "size": {
                    "type": "string",
                    "enum": ["1024x1024", "1792x1024", "1024x1792"],
                    "default": "1024x1024",
                },
                "quality": {"type": "string", "enum": ["standard", "hd"], "default": "standard"},
                "style": {"type": "string", "enum": ["vivid", "natural"], "default": "vivid"},
                "save_path": {
                    "type": "string",
                    "description": "Optional file path to save the image (PNG)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        prompt: str = kwargs["prompt"]
        size: str = kwargs.get("size", "1024x1024")
        quality: str = kwargs.get("quality", "standard")
        style: str = kwargs.get("style", "vivid")
        save_path: str | None = kwargs.get("save_path")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="OPENAI_API_KEY not set.")

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "dall-e-3",
                        "prompt": prompt,
                        "size": size,
                        "quality": quality,
                        "style": style,
                        "n": 1,
                        "response_format": "url",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                url = data["data"][0]["url"]
                revised_prompt = data["data"][0].get("revised_prompt", prompt)

            result_data: dict[str, Any] = {
                "url": url,
                "size": size,
                "revised_prompt": revised_prompt,
            }

            if save_path:
                async with httpx.AsyncClient() as dl:
                    img_resp = await dl.get(url)
                    img_resp.raise_for_status()
                Path(save_path).write_bytes(img_resp.content)
                result_data["saved_to"] = save_path

            return ToolResult(
                output=f"Image generated: {url}",
                data=result_data,
            )
        except Exception as exc:
            logger.error("generate_image failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# B6 — Text-to-Speech
# ---------------------------------------------------------------------------


class TextToSpeechTool(BaseTool):
    """Convert text to speech using the OpenAI TTS API."""

    name = "text_to_speech"
    description = (
        "Convert text to speech audio using OpenAI's TTS-1 model. "
        "Saves the audio file and returns the path."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to convert to speech"},
                "voice": {
                    "type": "string",
                    "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                    "default": "alloy",
                    "description": "Voice character",
                },
                "format": {
                    "type": "string",
                    "enum": ["mp3", "opus", "aac", "flac"],
                    "default": "mp3",
                },
                "save_path": {
                    "type": "string",
                    "description": "File path to save the audio output",
                },
                "model": {
                    "type": "string",
                    "enum": ["tts-1", "tts-1-hd"],
                    "default": "tts-1",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        text: str = kwargs["text"]
        voice: str = kwargs.get("voice", "alloy")
        fmt: str = kwargs.get("format", "mp3")
        model: str = kwargs.get("model", "tts-1")
        save_path: str = kwargs.get("save_path") or f"/tmp/selva_tts_{voice}.{fmt}"

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="OPENAI_API_KEY not set.")

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "voice": voice, "input": text, "response_format": fmt},
                )
                resp.raise_for_status()
                Path(save_path).write_bytes(resp.content)

            size_kb = Path(save_path).stat().st_size // 1024
            return ToolResult(
                output=f"Audio saved to {save_path} ({size_kb} KB).",
                data={"path": save_path, "voice": voice, "format": fmt, "size_kb": size_kb},
            )
        except Exception as exc:
            logger.error("text_to_speech failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
