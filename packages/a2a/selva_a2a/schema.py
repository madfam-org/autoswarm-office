"""A2A protocol schema definitions.

Follows the Google A2A open specification for agent discovery and task exchange.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Lifecycle status of an A2A task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentSkill(BaseModel):
    """A single capability advertised by an agent."""

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """Agent discovery metadata served at ``/.well-known/agent.json``.

    External frameworks (CrewAI, LangGraph, MS Agent Framework) use this
    to discover what this agent can do and how to call it.
    """

    name: str = "Selva Office"
    description: str = "AI-powered virtual office with autonomous agent swarms"
    url: str = ""
    version: str = "0.7.0"
    capabilities: list[str] = Field(
        default_factory=lambda: ["tasks/send", "tasks/get", "tasks/sendSubscribe"]
    )
    skills: list[AgentSkill] = Field(default_factory=list)
    authentication: dict[str, Any] = Field(default_factory=lambda: {"schemes": ["bearer"]})


class TaskRequest(BaseModel):
    """Inbound task request from an external agent."""

    description: str = Field(..., min_length=1, max_length=4000)
    graph_type: str = "coding"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """Response returned after submitting or querying an A2A task."""

    task_id: str
    status: TaskStatus
    result: dict[str, Any] | None = None
    error: str | None = None
