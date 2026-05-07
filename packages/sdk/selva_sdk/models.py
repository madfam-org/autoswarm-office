"""Pydantic models mirroring the nexus-api schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DispatchRequest(BaseModel):
    """Request body for dispatching a swarm task."""

    title: str | None = None
    description: str = Field(..., min_length=1)
    graph_type: str = Field(default="coding")
    assigned_agent_ids: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None
    priority: str = Field(default="medium")
    labels: list[str] = Field(default_factory=list)
    due_date: str | None = None


class AgentResponse(BaseModel):
    """Agent data returned from the API."""

    id: str
    name: str
    role: str
    status: str
    level: int
    department_id: str | None = None
    skill_ids: list[str] | None = None
    effective_skills: list[str] = Field(default_factory=list)


class TaskResponse(BaseModel):
    """Task data returned from the API."""

    id: str
    title: str | None = None
    description: str
    graph_type: str
    assigned_agent_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    kanban_status: str = "todo"
    priority: str = "medium"
    labels: list[str] = Field(default_factory=list)
    due_date: str | None = None
    creator_id: str | None = None
    parent_task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str | None = None
    completed_at: str | None = None


class TaskBoardItem(BaseModel):
    """Aggregated task card returned by the kanban board endpoint."""

    id: str
    title: str | None = None
    description: str
    graph_type: str
    status: str
    kanban_status: str
    priority: str
    labels: list[str] = Field(default_factory=list)
    due_date: str | None = None
    parent_task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    agent_names: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    total_tokens: int | None = None
    event_count: int = 0
    comment_count: int = 0


class TaskBoardResponse(BaseModel):
    """Kanban board grouped by kanban status."""

    columns: dict[str, list[TaskBoardItem]]
    totals: dict[str, int]


class TaskCommentResponse(BaseModel):
    """Durable per-task comment."""

    id: str
    task_id: str
    author_id: str | None = None
    body: str
    created_at: str


class TaskHistoryResponse(BaseModel):
    """Append-only task history row."""

    id: str
    task_id: str
    event_type: str
    actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class TaskClaimResponse(BaseModel):
    """Response from benchmark-style task claiming."""

    claimed: bool
    task: TaskResponse | None = None


class OverdueNotificationResponse(BaseModel):
    """Response from overdue notification scan."""

    scanned: int
    notified: int


class KanbanTaskImportResponse(BaseModel):
    """Response from kanban JSON/CSV import."""

    created: int
    tasks: list[TaskResponse] = Field(default_factory=list)


class KanbanMetricsResponse(BaseModel):
    """Kanban-specific metrics."""

    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    blocked_count: int
    dependency_blocked_count: int = 0
    overdue_count: int
    wip_count: int
    avg_wip_age_seconds: float | None = None
    avg_cycle_time_seconds: float | None = None
    throughput_by_label: dict[str, int] = Field(default_factory=dict)
    workload_by_assignee: dict[str, int] = Field(default_factory=dict)
