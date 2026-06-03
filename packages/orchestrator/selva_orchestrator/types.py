"""Core domain types for the Selva orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentRole(StrEnum):
    """Roles an agent can fulfill within a swarm department."""

    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    CRM = "crm"
    SUPPORT = "support"


class AgentStatus(StrEnum):
    """Lifecycle states for a swarm agent."""

    IDLE = "idle"
    WORKING = "working"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    ERROR = "error"


class AgentConfig(BaseModel):
    """Configuration and metadata for a single swarm agent."""

    id: str
    name: str
    role: AgentRole
    level: int = Field(default=1, ge=1, le=10)
    department_id: str | None = None
    status: AgentStatus = AgentStatus.IDLE
    skill_ids: list[str] = Field(default_factory=list)


class SwarmTask(BaseModel):
    """A task dispatched across one or more agents in the swarm."""

    id: str
    description: str
    assigned_agent_ids: list[str] = Field(default_factory=list)
    graph_type: str = "sequential"
    payload: dict = Field(default_factory=dict)
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DepartmentConfig(BaseModel):
    """Configuration for a department that groups agents."""

    id: str
    name: str
    slug: str
    max_agents: int = Field(ge=1)
    agent_ids: list[str] = Field(default_factory=list)
