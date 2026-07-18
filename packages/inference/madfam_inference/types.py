from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ContentType(StrEnum):
    """Content block types for multimodal messages."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BASE64 = "image_base64"


class MediaContent(BaseModel):
    """A single content block within a multimodal message.

    For TEXT blocks, ``content`` holds the text string.
    For IMAGE_URL blocks, ``content`` holds the URL.
    For IMAGE_BASE64 blocks, ``content`` holds the base64-encoded data
    and ``mime_type`` indicates the image format.
    """

    type: ContentType
    content: str
    mime_type: str | None = None


class RoutingPolicy(BaseModel):
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    max_tokens: int = 4096
    temperature: float = 0.7
    prefer_local: bool = False
    require_local: bool = False
    task_type: str | None = None
    model_override: str | None = None


class InferenceRequest(BaseModel):
    messages: list[dict[str, Any]]
    policy: RoutingPolicy = Field(default_factory=RoutingPolicy)
    system_prompt: str | None = None
    tools: list[dict] | None = None
    response_format: dict[str, Any] | None = None

    def has_media(self) -> bool:
        """Return True if any message contains image content blocks.

        Detects multimodal content by checking for messages whose ``content``
        field is a list containing blocks with ``type`` equal to
        ``image_url`` or ``image_base64``.
        """
        for msg in self.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in (
                        ContentType.IMAGE_URL,
                        ContentType.IMAGE_URL.value,
                        ContentType.IMAGE_BASE64,
                        ContentType.IMAGE_BASE64.value,
                    ):
                        return True
        return False


class InferenceResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    tool_calls: list[dict] | None = None


class StreamUsage(BaseModel):
    """Final token accounting for a streamed completion.

    Providers report this once, at stream end, via the optional
    ``on_usage`` callback of ``stream()`` — the streamed chunks themselves
    stay plain text. ``provider`` is stamped by the router (the caller
    doesn't know which provider won selection/fallback).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    provider: str | None = None
