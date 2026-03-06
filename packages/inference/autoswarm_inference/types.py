from enum import Enum

from pydantic import BaseModel, Field


class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RoutingPolicy(BaseModel):
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    max_tokens: int = 4096
    temperature: float = 0.7
    prefer_local: bool = False
    require_local: bool = False


class InferenceRequest(BaseModel):
    messages: list[dict[str, str]]
    policy: RoutingPolicy = Field(default_factory=RoutingPolicy)
    system_prompt: str | None = None
    tools: list[dict] | None = None


class InferenceResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    tool_calls: list[dict] | None = None
