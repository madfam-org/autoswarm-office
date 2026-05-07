"""Swarm task dispatch and monitoring endpoints."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from selva_orchestrator import ComputeTokenManager
from selva_permissions import Audience as PermissionAudience
from selva_permissions import is_audience_enforcement_enabled, resolve_audience
from selva_redis_pool import get_redis_pool
from selva_skills import SkillAudience, get_skill_registry

from ..auth import get_current_user, require_non_demo, require_non_guest
from ..billing_tiers import get_daily_limit
from ..config import get_settings
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import (
    Agent,
    ComputeTokenLedger,
    DeploymentEvidenceRecord,
    SwarmTask,
    SwarmTaskOutbox,
    TaskComment,
    TaskEvent,
    TaskHistory,
    TenantConfig,
    Workflow,
)
from ..operational_metrics import record_deployment_status_update
from ..tenant import TenantContext, get_tenant
from ..ws import MessageRateLimiter

router = APIRouter(tags=["swarms"], dependencies=[Depends(get_current_user)])

# -- Per-user dispatch rate limiter -------------------------------------------
_settings = get_settings()
_dispatch_limiter = MessageRateLimiter(
    max_messages=_settings.dispatch_rate_limit,
    window_seconds=float(_settings.dispatch_rate_window),
)

# -- Module-internal constants -------------------------------------------------
# Cost (in compute tokens) of dispatching one swarm task. Sourced from the
# canonical ``ComputeTokenManager.COST_TABLE`` in selva_orchestrator so the
# value lives in exactly one place. Falls back to a hardcoded default if
# the orchestrator package ever drops the entry (defensive — also lets us
# load this module before the orchestrator is initialised).
_DISPATCH_COMPUTE_TOKEN_COST: int = ComputeTokenManager.COST_TABLE.get("dispatch_task", 10)

# Page size for the kanban-style task board endpoint. Bounded so the
# server-side query plus payload serialisation stays within the request
# timeout for orgs with high task volume.
_TASK_BOARD_PAGE_SIZE: int = 100


async def require_dispatch_rate_limit(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    """Reject dispatch requests that exceed the per-user rate limit."""
    user_sub = user.get("sub", "anonymous")
    if not _dispatch_limiter.check(user_sub):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Dispatch rate limit exceeded",
        )


# -- Request / Response schemas -----------------------------------------------


class DispatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    graph_type: str = Field(
        default="sequential",
        pattern=r"^(sequential|parallel|coding|research|crm|custom|deployment|puppeteer|meeting|billing|accounting|sales|intelligence|operations)$",
    )
    assigned_agent_ids: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    kanban_status: str = Field(
        default="todo",
        pattern=r"^(todo|in_progress|review|done|blocked)$",
    )
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    labels: list[str] = Field(default_factory=list)
    due_date: str | None = None
    parent_task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    workflow_id: str | None = Field(
        default=None,
        description="UUID of a custom workflow definition (required for graph_type='custom')",
    )
    source: str = Field(
        default="api",
        min_length=1,
        max_length=80,
        description="Canonical task source such as api, webhook, scheduler, or selva-recursive.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=200,
        description="Consumer-supplied idempotency key copied into the canonical task envelope.",
    )
    desired_state_hash: str | None = Field(
        default=None,
        max_length=200,
        description="Optional desired-state hash for provisioning/deployment tasks.",
    )


class ManifestDispatchRequest(BaseModel):
    manifest: dict[str, Any] | str = Field(
        ...,
        description="EcosystemApp manifest as a parsed object, JSON string, or YAML string.",
    )
    assigned_agent_ids: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    source: str = Field(default="ecosystem-app-manifest", min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)


class ManifestVerifyResponse(BaseModel):
    ok: bool
    kind: str | None
    api_version: str | None
    manifest_hash: str | None
    derived: dict[str, Any]
    gaps: list[str]
    unsupported_placeholders: list[str]


class SwarmTaskResponse(BaseModel):
    id: str
    title: str | None
    description: str
    graph_type: str
    assigned_agent_ids: list[str]
    payload: dict[str, Any]
    status: str
    kanban_status: str
    priority: str
    labels: list[str]
    due_date: str | None
    creator_id: str | None
    parent_task_id: str | None
    depends_on: list[str]
    created_at: str
    updated_at: str | None
    completed_at: str | None

    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(running|completed|failed|cancelled)$")
    result: dict[str, Any] | None = None
    started_at: str | None = None
    error_message: str | None = None
    deployment_evidence: dict[str, Any] | None = None


class KanbanTaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    kanban_status: str | None = Field(
        default=None,
        pattern=r"^(todo|in_progress|review|done|blocked)$",
    )
    priority: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")
    labels: list[str] | None = None
    due_date: str | None = None
    parent_task_id: str | None = None
    depends_on: list[str] | None = None


class TaskCommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class TaskCommentResponse(BaseModel):
    id: str
    task_id: str
    author_id: str | None
    body: str
    created_at: str

    model_config = {"from_attributes": True}


class TaskHistoryResponse(BaseModel):
    id: str
    task_id: str
    event_type: str
    actor_id: str | None
    payload: dict[str, Any]
    created_at: str

    model_config = {"from_attributes": True}


class TaskClaimRequest(BaseModel):
    agent_id: str | None = None
    graph_type: str | None = None
    labels: list[str] = Field(default_factory=list)


class TaskClaimResponse(BaseModel):
    claimed: bool
    task: SwarmTaskResponse | None = None


class OverdueNotificationResponse(BaseModel):
    scanned: int
    notified: int


class KanbanTaskImportItem(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    graph_type: str = Field(default="sequential", max_length=50)
    kanban_status: str = Field(default="todo", pattern=r"^(todo|in_progress|review|done|blocked)$")
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    labels: list[str] = Field(default_factory=list)
    assigned_agent_ids: list[str] = Field(default_factory=list)
    due_date: str | None = None
    parent_task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class KanbanTaskImportRequest(BaseModel):
    items: list[KanbanTaskImportItem]


class KanbanTaskImportResponse(BaseModel):
    created: int
    tasks: list[SwarmTaskResponse]


class KanbanMetricsResponse(BaseModel):
    total: int
    status_counts: dict[str, int]
    blocked_count: int
    dependency_blocked_count: int
    overdue_count: int
    wip_count: int
    avg_wip_age_seconds: float | None
    avg_cycle_time_seconds: float | None
    throughput_by_label: dict[str, int]
    workload_by_assignee: dict[str, int]


class DeploymentEvidenceRecordResponse(BaseModel):
    id: str
    task_id: str
    graph_type: str
    deployment_status: str
    evidence: dict[str, Any]
    created_at: str

    model_config = {"from_attributes": True}


class DeploymentEvidenceRecordListResponse(BaseModel):
    evidence_records: list[DeploymentEvidenceRecordResponse]
    total: int
    limit: int
    offset: int


# -- Helpers ------------------------------------------------------------------


def _compute_perf_weight(agent: Agent) -> float:
    """Compute a 0.0-1.0 performance weight from agent stats.

    ``perf_weight = 0.5 * approval_rate + 0.5 * completion_rate``
    New agents (no history) default to 0.5 (neutral).
    """
    total_tasks = agent.tasks_completed + agent.tasks_failed
    total_approvals = agent.approval_success_count + agent.approval_denial_count

    if total_tasks == 0 and total_approvals == 0:
        return 0.5  # Neutral for new agents

    completion_rate = agent.tasks_completed / total_tasks if total_tasks > 0 else 0.5
    approval_rate = agent.approval_success_count / total_approvals if total_approvals > 0 else 0.5

    return 0.5 * approval_rate + 0.5 * completion_rate


def _task_to_response(task: SwarmTask) -> SwarmTaskResponse:
    return SwarmTaskResponse(
        id=str(task.id),
        title=task.title,
        description=task.description,
        graph_type=task.graph_type,
        assigned_agent_ids=task.assigned_agent_ids or [],
        payload=task.payload or {},
        status=task.status,
        kanban_status=task.kanban_status or _execution_status_to_kanban(task.status),
        priority=task.priority or "medium",
        labels=task.labels or [],
        due_date=task.due_date.isoformat() if task.due_date else None,
        creator_id=task.creator_id,
        parent_task_id=str(task.parent_task_id) if task.parent_task_id else None,
        depends_on=[str(dep) for dep in (task.depends_on or [])],
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


def _task_comment_to_response(comment: TaskComment) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=str(comment.id),
        task_id=str(comment.task_id),
        author_id=comment.author_id,
        body=comment.body,
        created_at=comment.created_at.isoformat(),
    )


def _task_history_to_response(history: TaskHistory) -> TaskHistoryResponse:
    return TaskHistoryResponse(
        id=str(history.id),
        task_id=str(history.task_id),
        event_type=history.event_type,
        actor_id=history.actor_id,
        payload=history.payload or {},
        created_at=history.created_at.isoformat(),
    )


def _derive_task_title(description: str) -> str:
    title = " ".join(description.strip().splitlines()[0].split())
    return title[:200] if title else "Untitled task"


def _execution_status_to_kanban(runtime_status: str | None) -> str:
    return {
        "queued": "todo",
        "pending": "todo",
        "running": "in_progress",
        "completed": "done",
        "failed": "blocked",
        "cancelled": "blocked",
    }.get(runtime_status or "", "todo")


def _parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}; expected ISO-8601 datetime",
        ) from exc


def _parse_optional_uuid(value: str | None, field_name: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} UUID",
        ) from exc


def _normalise_id_list(values: list[str] | None, field_name: str) -> list[str]:
    if values is None:
        return []
    normalised: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        normalised.append(str(_parse_optional_uuid(value, field_name)))
    return normalised


def _actor_id_from_user(user: dict | None) -> str | None:
    if not user:
        return None
    sub = user.get("sub")
    return str(sub) if sub else None


def _add_task_history(
    db: AsyncSession,
    *,
    task: SwarmTask,
    event_type: str,
    actor_id: str | None,
    payload: dict[str, Any],
) -> None:
    db.add(
        TaskHistory(
            task_id=task.id,
            org_id=task.org_id,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload,
        )
    )


def _notification_sent_key(kind: str, dedupe_key: str | None = None) -> str:
    return f"{kind}:{dedupe_key}" if dedupe_key else kind


def _has_task_notification(task: SwarmTask, key: str) -> bool:
    notifications = (task.payload or {}).get("_selva_notifications")
    return isinstance(notifications, dict) and key in notifications


def _record_task_notification(task: SwarmTask, key: str) -> None:
    payload = dict(task.payload or {})
    notifications = payload.get("_selva_notifications")
    if not isinstance(notifications, dict):
        notifications = {}
    notifications[key] = datetime.now(UTC).isoformat()
    payload["_selva_notifications"] = notifications
    task.payload = payload


async def _emit_task_lifecycle_notification(
    db: AsyncSession,
    *,
    task: SwarmTask,
    kind: str,
    actor_id: str | None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Emit a durable lifecycle notification event and history row."""
    key = _notification_sent_key(kind, dedupe_key)
    if _has_task_notification(task, key):
        return False

    notification_payload = {
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description,
        "kanban_status": task.kanban_status,
        "runtime_status": task.status,
        "priority": task.priority,
        "labels": task.labels or [],
        "assigned_agent_ids": task.assigned_agent_ids or [],
        "due_date": task.due_date.isoformat() if task.due_date else None,
        **(payload or {}),
    }
    _add_task_history(
        db,
        task=task,
        event_type=f"task.notification.{kind}",
        actor_id=actor_id,
        payload=notification_payload,
    )
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type=f"task.notification.{kind}",
            event_category="notification",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=task.org_id,
            payload=notification_payload,
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task notification event",
            exc_info=True,
        )
    try:
        from ..task_notification_notifier import publish_task_notification

        await publish_task_notification(
            org_id=task.org_id,
            event_type=f"task.notification.{kind}",
            payload=notification_payload,
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to fan out task notification",
            exc_info=True,
        )
    _record_task_notification(task, key)
    return True


def _notification_kind_for_kanban_status(kanban_status: str | None) -> str | None:
    return {
        "review": "review_needed",
        "done": "completed",
        "blocked": "blocked",
    }.get(kanban_status or "")


def _encode_csv_list(values: list[str] | None) -> str:
    return "|".join(values or [])


def _decode_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    separator = "|" if "|" in raw else ","
    return [part.strip() for part in raw.split(separator) if part.strip()]


def _task_to_export_item(task: SwarmTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "graph_type": task.graph_type,
        "status": task.status,
        "kanban_status": task.kanban_status,
        "priority": task.priority,
        "labels": task.labels or [],
        "assigned_agent_ids": task.assigned_agent_ids or [],
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "depends_on": [str(dep) for dep in (task.depends_on or [])],
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _task_export_csv(items: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "id",
        "title",
        "description",
        "graph_type",
        "status",
        "kanban_status",
        "priority",
        "labels",
        "assigned_agent_ids",
        "due_date",
        "parent_task_id",
        "depends_on",
        "created_at",
        "updated_at",
        "completed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = dict(item)
        row["labels"] = _encode_csv_list(row.get("labels"))
        row["assigned_agent_ids"] = _encode_csv_list(row.get("assigned_agent_ids"))
        row["depends_on"] = _encode_csv_list(row.get("depends_on"))
        writer.writerow(row)
    return output.getvalue()


def _import_items_from_csv(raw_csv: str) -> list[KanbanTaskImportItem]:
    reader = csv.DictReader(io.StringIO(raw_csv))
    items: list[KanbanTaskImportItem] = []
    for row in reader:
        items.append(
            KanbanTaskImportItem(
                title=row.get("title") or None,
                description=row.get("description") or "",
                graph_type=row.get("graph_type") or "sequential",
                kanban_status=row.get("kanban_status") or "todo",
                priority=row.get("priority") or "medium",
                labels=_decode_csv_list(row.get("labels")),
                assigned_agent_ids=_decode_csv_list(row.get("assigned_agent_ids")),
                due_date=row.get("due_date") or None,
                parent_task_id=row.get("parent_task_id") or None,
                depends_on=_decode_csv_list(row.get("depends_on")),
            )
        )
    return items


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    start = _normalise_datetime_for_compare(start)
    end = _normalise_datetime_for_compare(end)
    return max(0.0, (end - start).total_seconds())


def _normalise_datetime_for_compare(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _datetime_before(value: datetime | None, cutoff: datetime) -> bool:
    if value is None:
        return False
    return _normalise_datetime_for_compare(value) < _normalise_datetime_for_compare(cutoff)


def _deployment_status_from_evidence(
    evidence: dict[str, Any],
    result: dict[str, Any] | None,
    fallback_status: str,
) -> str:
    status_value = (
        evidence.get("deployment_status")
        or evidence.get("deploy_status")
        or evidence.get("status")
        or (result or {}).get("deploy_status")
        or fallback_status
    )
    return str(status_value)[:50]


def _evidence_record_to_response(
    record: DeploymentEvidenceRecord,
) -> DeploymentEvidenceRecordResponse:
    return DeploymentEvidenceRecordResponse(
        id=str(record.id),
        task_id=str(record.task_id),
        graph_type=record.graph_type,
        deployment_status=record.deployment_status,
        evidence=record.evidence or {},
        created_at=record.created_at.isoformat(),
    )


def _parse_ecosystem_app_manifest(raw_manifest: dict[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(raw_manifest, dict):
        return raw_manifest
    if isinstance(raw_manifest, bytes):
        raw_manifest = raw_manifest.decode("utf-8")

    try:
        parsed = json.loads(raw_manifest)
    except json.JSONDecodeError:
        try:
            import yaml

            parsed = yaml.safe_load(raw_manifest)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="manifest must be valid EcosystemApp JSON or YAML",
            ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manifest must parse to an object",
        )
    return parsed


def _pick_first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deployment_dispatch_from_ecosystem_app(
    manifest: dict[str, Any],
    *,
    assigned_agent_ids: list[str],
    required_skills: list[str],
    source: str,
    idempotency_key: str | None,
) -> DispatchRequest:
    kind = manifest.get("kind")
    if kind != "EcosystemApp":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manifest.kind must be EcosystemApp",
        )

    metadata = manifest.get("metadata") or {}
    spec = manifest.get("spec") or {}
    deployment = spec.get("deployment") or {}
    if (
        not isinstance(metadata, dict)
        or not isinstance(spec, dict)
        or not isinstance(deployment, dict)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manifest metadata, spec, and spec.deployment must be objects",
        )

    service = _pick_first(
        deployment.get("service"),
        deployment.get("service_id"),
        deployment.get("app_id"),
        spec.get("service"),
        spec.get("service_id"),
        spec.get("app_id"),
        spec.get("id"),
        metadata.get("name"),
    )
    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        labels = {}
    environment = _pick_first(
        deployment.get("environment"),
        spec.get("environment"),
        labels.get("environment"),
        "staging",
    )
    environment = str(environment).lower()

    gitops_app = deployment.get("gitops_app")
    smoke_checks = deployment.get("smoke_checks") or []
    current_pointer = deployment.get("current_pointer") or {}
    rollback_pointer = deployment.get("rollback_pointer") or {}

    if environment == "production":
        missing = []
        if not gitops_app:
            missing.append("spec.deployment.gitops_app")
        if not smoke_checks:
            missing.append("spec.deployment.smoke_checks")
        if not rollback_pointer:
            missing.append("spec.deployment.rollback_pointer")
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "production_manifest_missing_safety_fields",
                    "missing": missing,
                },
            )

    desired_state_hash = _canonical_manifest_hash(manifest)
    deployment_payload = {
        "service": str(service or ""),
        "app_id": str(
            _pick_first(
                deployment.get("app_id"),
                spec.get("app_id"),
                spec.get("id"),
                service,
            )
            or ""
        ),
        "environment": environment,
        "gitops_app": gitops_app or "",
        "branch": deployment.get("branch") or spec.get("branch") or "",
        "manifest_path": deployment.get("manifest_path") or spec.get("manifest_path") or "",
        "overlay_path": deployment.get("overlay_path") or deployment.get("manifest_path") or "",
        "repo_path": (
            deployment.get("repo_path")
            or deployment.get("repo")
            or spec.get("repo_path")
            or ""
        ),
        "smoke_checks": smoke_checks if isinstance(smoke_checks, list) else [smoke_checks],
        "current_pointer": current_pointer if isinstance(current_pointer, dict) else {},
        "rollback_pointer": rollback_pointer if isinstance(rollback_pointer, dict) else {},
        "ecosystem_app": {
            "apiVersion": manifest.get("apiVersion"),
            "kind": kind,
            "metadata": metadata,
            "spec": spec,
        },
        "manifest_hash": desired_state_hash,
    }
    app_identity = deployment_payload["app_id"] or deployment_payload["service"]

    return DispatchRequest(
        description=(
            f"Deploy EcosystemApp {deployment_payload['app_id'] or deployment_payload['service']}"
            f" to {environment}"
        ),
        graph_type="deployment",
        assigned_agent_ids=assigned_agent_ids,
        required_skills=required_skills,
        payload=deployment_payload,
        source=source,
        idempotency_key=(
            idempotency_key
            or f"ecosystem-app:{app_identity}:{environment}:{desired_state_hash}"
        ),
        desired_state_hash=desired_state_hash,
    )


def _verify_ecosystem_app_manifest(manifest: dict[str, Any]) -> ManifestVerifyResponse:
    """Validate and derive canonical EcosystemApp/AppSpec fields without dispatching."""
    raw_kind = manifest.get("kind")
    raw_api_version = manifest.get("apiVersion")
    kind = raw_kind if isinstance(raw_kind, str) else None
    api_version = raw_api_version if isinstance(raw_api_version, str) else None
    gaps: list[str] = []
    unsupported_placeholders: list[str] = []

    if kind != "EcosystemApp":
        gaps.append("manifest.kind must be EcosystemApp")
    if api_version != "madfam.io/v1alpha1":
        gaps.append("manifest.apiVersion must be madfam.io/v1alpha1")

    metadata = manifest.get("metadata") or {}
    spec = manifest.get("spec") or {}
    deployment = spec.get("deployment") if isinstance(spec, dict) else {}
    deployment = deployment or {}

    if not isinstance(metadata, dict):
        gaps.append("metadata must be an object")
        metadata = {}
    if not isinstance(spec, dict):
        gaps.append("spec must be an object")
        spec = {}
    if not isinstance(deployment, dict):
        gaps.append("spec.deployment must be an object")
        deployment = {}

    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        labels = {}
    metadata_app_id = _pick_first(metadata.get("app_id"), metadata.get("name"))

    service = _pick_first(
        deployment.get("service"),
        deployment.get("service_id"),
        deployment.get("app_id"),
        spec.get("service"),
        spec.get("service_id"),
        spec.get("app_id"),
        spec.get("id"),
        metadata_app_id,
    )
    app_id = _pick_first(
        deployment.get("app_id"),
        spec.get("app_id"),
        spec.get("id"),
        metadata_app_id,
        service,
    )
    environment = str(
        _pick_first(
            deployment.get("environment"),
            spec.get("environment"),
            metadata.get("environment"),
            labels.get("environment"),
            "staging",
        )
    ).lower()

    for path, value in (
        ("metadata.app_id", metadata_app_id),
        ("metadata.environment", metadata.get("environment")),
        ("metadata.idempotency_key", metadata.get("idempotency_key")),
        ("metadata.desired_state_hash", metadata.get("desired_state_hash")),
        ("spec.identity", spec.get("identity")),
        ("spec.runtime", spec.get("runtime")),
        ("spec.deployment.gitops_app", deployment.get("gitops_app")),
        ("spec.orchestration", spec.get("orchestration")),
        ("spec.observability", spec.get("observability")),
    ):
        if not value:
            gaps.append(path)

    smoke_checks = deployment.get("smoke_checks") or []
    current_pointer = deployment.get("current_pointer") or {}
    rollback_pointer = deployment.get("rollback_pointer") or {}
    if environment == "production":
        if not smoke_checks:
            gaps.append("spec.deployment.smoke_checks")
        if not rollback_pointer:
            gaps.append("spec.deployment.rollback_pointer")

    for path in (
        "spec.janua",
        "spec.auth",
        "spec.enclii",
        "spec.gitops",
        "spec.deployment.janua",
        "spec.deployment.enclii",
    ):
        cursor: Any = manifest
        for part in path.split("."):
            cursor = cursor.get(part) if isinstance(cursor, dict) else None
        if cursor:
            unsupported_placeholders.append(path)

    manifest_hash = _canonical_manifest_hash(manifest)
    derived = {
        "graph_type": "deployment",
        "service": str(service or ""),
        "app_id": str(app_id or ""),
        "environment": environment,
        "gitops_app": deployment.get("gitops_app") or "",
        "branch": deployment.get("branch") or spec.get("branch") or "",
        "manifest_path": deployment.get("manifest_path") or spec.get("manifest_path") or "",
        "overlay_path": deployment.get("overlay_path") or deployment.get("manifest_path") or "",
        "repo_path": (
            deployment.get("repo_path")
            or deployment.get("repo")
            or spec.get("repo_path")
            or ""
        ),
        "smoke_checks": smoke_checks if isinstance(smoke_checks, list) else [smoke_checks],
        "current_pointer": current_pointer,
        "rollback_pointer": rollback_pointer,
        "desired_state_hash": manifest_hash,
        "idempotency_key": f"ecosystem-app:{app_id or service or ''}:{environment}:{manifest_hash}",
    }

    return ManifestVerifyResponse(
        ok=not gaps and not unsupported_placeholders,
        kind=kind,
        api_version=api_version,
        manifest_hash=manifest_hash,
        derived=derived,
        gaps=gaps,
        unsupported_placeholders=unsupported_placeholders,
    )


# -- Endpoints ----------------------------------------------------------------


@router.post(
    "/dispatch",
    response_model=SwarmTaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_non_guest),
        Depends(require_non_demo),
        Depends(require_dispatch_rate_limit),
    ],
)
async def dispatch_task(
    body: DispatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> SwarmTaskResponse:
    """Dispatch a new swarm task.

    Validates compute token budget, persists the task, and publishes a
    message to the Redis task queue for worker consumption.

    Idempotency: when the caller sends ``Idempotency-Key`` header, a
    successful response is cached for 24h scoped by (org_id, POST,
    /api/v1/swarms/dispatch, key). Retries with the same key replay the
    cached response instead of dispatching a duplicate task. Header
    absent → endpoint behaves exactly as before (no caching).
    """
    # Idempotency replay short-circuit. Must run before any DB work so
    # the second call doesn't even hit the compute-budget ledger.
    cached_response = getattr(idem, "cached", None)
    if getattr(idem, "is_replay", False) and cached_response is not None:
        return SwarmTaskResponse.model_validate(cached_response)

    settings = get_settings()

    # Extract request_id for cross-service correlation.
    request_id = getattr(request.state, "request_id", None)

    # -- Validate custom workflow dispatch ------------------------------------
    workflow_yaml: str | None = None
    if body.graph_type == "custom":
        if not body.workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workflow_id is required when graph_type is 'custom'",
            )
        try:
            wf_uid = uuid.UUID(body.workflow_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workflow_id UUID",
            ) from exc
        wf_result = await db.execute(select(Workflow).where(Workflow.id == wf_uid))
        wf = wf_result.scalar_one_or_none()
        if wf is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )
        workflow_yaml = wf.yaml_content

    # -- Audience gate --------------------------------------------------------
    # A tenant swarm (org_id != PLATFORM_ORG_ID) cannot dispatch a task
    # that requires platform-audience skills. Platform swarms can
    # dispatch any audience (superset). Unset PLATFORM_ORG_ID means
    # every caller is tenant audience — no platform skills are
    # dispatchable at all, which is the safe default until MADFAM's
    # own org is configured.
    caller_audience = resolve_audience(tenant.org_id)
    if body.required_skills and caller_audience is PermissionAudience.TENANT:
        forbidden: list[str] = []
        try:
            skill_registry = get_skill_registry()
        except Exception:
            skill_registry = None
        if skill_registry is not None:
            for skill_name in body.required_skills:
                meta = skill_registry.get_metadata(skill_name)
                if meta is not None and meta.audience is SkillAudience.PLATFORM:
                    forbidden.append(skill_name)
        if forbidden:
            if is_audience_enforcement_enabled():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "audience_mismatch",
                        "message": ("Tenant swarms cannot dispatch platform-audience skills."),
                        "forbidden_skills": forbidden,
                        "caller_audience": caller_audience.value,
                    },
                )
            # Shadow mode: log + allow. Flip AUDIENCE_FILTER_ENABLED to
            # enforce once the production rate of shadow blocks is known.
            logging.getLogger(__name__).warning(
                "audience_shadow_block caller_org=%s caller_audience=%s "
                "forbidden_skills=%s (permitting — AUDIENCE_FILTER_ENABLED off)",
                tenant.org_id,
                caller_audience.value,
                forbidden,
            )

    # -- Skill-based agent matching (when no explicit agents provided) --------
    assigned_agent_ids = body.assigned_agent_ids
    if not assigned_agent_ids and body.required_skills:
        # Auto-select agents by skill overlap
        try:
            from selva_skills import DEFAULT_ROLE_SKILLS

            result = await db.execute(
                select(Agent).where(Agent.status == "idle").order_by(Agent.created_at)
            )
            idle_agents = result.scalars().all()
            scored: list[tuple[float, Any]] = []
            required = set(body.required_skills)
            for agent in idle_agents:
                agent_skills = set(agent.skill_ids or DEFAULT_ROLE_SKILLS.get(agent.role, []))
                overlap = len(required & agent_skills)
                if overlap > 0:
                    skill_score = overlap / len(required)
                    # Performance-weighted scoring (30% weight)
                    perf_weight = _compute_perf_weight(agent)
                    final_score = skill_score * (0.7 + 0.3 * perf_weight)
                    scored.append((final_score, agent))
            scored.sort(key=lambda x: x[0], reverse=True)
            assigned_agent_ids = [str(a.id) for _, a in scored[:3]]
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to auto-select agents by skill",
                exc_info=True,
            )

    # -- Fallback: auto-assign any idle agent when no agents or skills given --
    if not assigned_agent_ids:
        try:
            fallback_result = await db.execute(
                select(Agent)
                .where(Agent.org_id == tenant.org_id)
                .where(Agent.status == "idle")
                .order_by(Agent.created_at)
                .limit(1)
            )
            fallback_agent = fallback_result.scalar_one_or_none()
            if fallback_agent is None:
                # No idle agents — pick any agent in the org
                fallback_result = await db.execute(
                    select(Agent)
                    .where(Agent.org_id == tenant.org_id)
                    .order_by(Agent.created_at)
                    .limit(1)
                )
                fallback_agent = fallback_result.scalar_one_or_none()
            if fallback_agent is not None:
                assigned_agent_ids = [str(fallback_agent.id)]
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to auto-assign fallback agent",
                exc_info=True,
            )

    # -- Tenant limit enforcement -----------------------------------------------
    tenant_config = None
    try:
        tc_result = await db.execute(
            select(TenantConfig).where(TenantConfig.org_id == tenant.org_id)
        )
        tenant_config = tc_result.scalar_one_or_none()
        if tenant_config is not None:
            # Check daily task limit
            today_start_tc = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            today_count_result = await db.execute(
                select(func.count(SwarmTask.id)).where(
                    SwarmTask.org_id == tenant.org_id,
                    SwarmTask.created_at >= today_start_tc,
                )
            )
            today_count: int = today_count_result.scalar_one()
            if today_count >= tenant_config.max_daily_tasks:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily task limit reached for your organization",
                )

            # Check agent capacity (warn, don't block)
            agent_count_result = await db.execute(
                select(func.count(Agent.id)).where(Agent.org_id == tenant.org_id)
            )
            agent_count: int = agent_count_result.scalar_one()
            if agent_count >= tenant_config.max_agents:
                logging.getLogger(__name__).warning(
                    "Org %s at agent capacity (%d/%d)",
                    tenant.org_id,
                    agent_count,
                    tenant_config.max_agents,
                )
    except HTTPException:
        raise
    except SQLAlchemyError:
        logging.getLogger(__name__).warning(
            "Tenant limit check failed due to DB error; refusing dispatch",
            exc_info=True,
        )
        # Rollback the failed transaction so the session is reusable.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="transient db error during quota check",
        ) from None

    # -- Compute token budget enforcement (Dhanam subscription tier) ----------
    if tenant_config and tenant_config.dhanam_space_id:
        try:
            from ..billing_client import get_billing_status

            billing = await get_billing_status(tenant_config.dhanam_space_id)
            if billing and billing.get("compute_tokens_remaining", float("inf")) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Compute token budget exhausted. Upgrade your subscription at dhan.am",
                )
        except HTTPException:
            raise
        except Exception:
            logging.getLogger(__name__).debug(
                "Compute budget check skipped (Dhanam unavailable)", exc_info=True
            )

    # -- Compute token budget check -------------------------------------------
    dispatch_cost = _DISPATCH_COMPUTE_TOKEN_COST

    # Check remaining budget before dispatching.
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    budget_result = await db.execute(
        select(func.coalesce(func.sum(ComputeTokenLedger.amount), 0)).where(
            ComputeTokenLedger.created_at >= today_start,
            ComputeTokenLedger.org_id == tenant.org_id,
        )
    )
    used: int = budget_result.scalar_one()
    # Default tier limit when no Dhanam-cached entry exists in Redis.
    # billing_internal.check_budget consults the cache; this branch is
    # the fast path that keeps dispatch latency low. Source-of-truth:
    # ``nexus_api.billing_tiers``.
    daily_limit = get_daily_limit(None)
    if used + dispatch_cost > daily_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Compute token budget exceeded for today",
        )

    header_idempotency_key = request.headers.get("Idempotency-Key")
    if not isinstance(header_idempotency_key, str):
        header_idempotency_key = None
    idempotency_key = body.idempotency_key or header_idempotency_key or str(uuid.uuid4())
    task_audience = caller_audience.value
    canonical_envelope: dict[str, Any] = {
        "schema": "selva.task-envelope/v1",
        "task_id": None,
        "org_id": tenant.org_id,
        "audience": task_audience,
        "graph_type": body.graph_type,
        "idempotency_key": idempotency_key,
        "source": body.source,
        "desired_state_hash": body.desired_state_hash,
        "request_id": request_id,
    }
    task_payload = {
        **(body.payload or {}),
        "_selva_envelope": canonical_envelope,
    }

    # Record the debit in the ledger (the in-memory ComputeTokenManager lives
    # in the orchestrator package; the ledger is the durable record).
    wf_uid_value = wf_uid if body.graph_type == "custom" else None
    task = SwarmTask(
        title=body.title or _derive_task_title(body.description),
        description=body.description,
        graph_type=body.graph_type,
        assigned_agent_ids=assigned_agent_ids,
        payload=task_payload,
        status="queued",
        kanban_status=body.kanban_status,
        priority=body.priority,
        labels=body.labels,
        due_date=_parse_optional_datetime(body.due_date, "due_date"),
        parent_task_id=_parse_optional_uuid(body.parent_task_id, "parent_task_id"),
        depends_on=_normalise_id_list(body.depends_on, "depends_on"),
        org_id=tenant.org_id,
        workflow_id=wf_uid_value,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    canonical_envelope["task_id"] = str(task.id)
    task.payload = {
        **(task.payload or {}),
        "_selva_envelope": canonical_envelope,
    }
    _add_task_history(
        db,
        task=task,
        event_type="task.created",
        actor_id=task.creator_id,
        payload={
            "title": task.title,
            "kanban_status": task.kanban_status,
            "priority": task.priority,
            "labels": task.labels or [],
        },
    )
    if assigned_agent_ids:
        await _emit_task_lifecycle_notification(
            db,
            task=task,
            kind="assigned",
            actor_id=task.creator_id,
            payload={"assigned_agent_ids": assigned_agent_ids},
            dedupe_key="dispatch",
        )
    await db.flush()

    ledger_entry = ComputeTokenLedger(
        action="dispatch_task",
        amount=dispatch_cost,
        task_id=task.id,
        org_id=tenant.org_id,
    )
    db.add(ledger_entry)
    await db.flush()

    # -- Durable outbox for Redis queue publication ---------------------------
    task_msg_data: dict[str, Any] = {
        "schema": "selva.task-envelope/v1",
        "task_id": str(task.id),
        "org_id": tenant.org_id,
        "audience": task_audience,
        "graph_type": task.graph_type,
        "idempotency_key": idempotency_key,
        "source": body.source,
        "desired_state_hash": body.desired_state_hash,
        "description": task.description,
        "assigned_agent_ids": task.assigned_agent_ids,
        "required_skills": body.required_skills,
        "payload": task.payload,
        "request_id": request_id,
    }
    if workflow_yaml is not None:
        task_msg_data["workflow_yaml"] = workflow_yaml

    # Resolve matching playbook for autonomous execution (Axiom IV)
    try:
        from .playbooks import _playbooks

        trigger_event = (task.payload or {}).get("trigger_event", "")
        if trigger_event:
            for pb in _playbooks.values():
                if (
                    pb["trigger_event"] == trigger_event
                    and pb["enabled"]
                    and not pb["require_approval"]
                ):
                    task_msg_data["playbook_id"] = pb["id"]
                    task_msg_data["playbook"] = pb
                    break
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to resolve autonomous playbook for trigger_event",
            exc_info=True,
        )

    outbox = SwarmTaskOutbox(
        task_id=task.id,
        org_id=tenant.org_id,
        stream_name="autoswarm:task-stream",
        payload=task_msg_data,
    )
    db.add(outbox)
    await db.flush()

    # Existing best-effort Redis publish path remains for compatibility.
    # The outbox row above is durable and committed with the SwarmTask;
    # if Redis fails, the legacy DB-pending worker reclaim still applies.
    try:
        pool = get_redis_pool(url=settings.redis_url)
        task_msg = json.dumps(task_msg_data)
        msg_id = await pool.execute_with_retry("xadd", "autoswarm:task-stream", {"data": task_msg})
        task.stream_message_id = str(msg_id)
        outbox.status = "sent"
        outbox.stream_message_id = str(msg_id)
        outbox.sent_at = datetime.now(UTC)
        await db.flush()
    except Exception as exc:
        task.status = "pending"
        outbox.status = "retryable"
        outbox.retry_count += 1
        outbox.last_error = str(exc)[:2000]
        await db.flush()

    # Emit task.dispatched event (direct DB insert, no HTTP)
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.dispatched",
            event_category="task",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=tenant.org_id,
            request_id=request_id,
            payload={"description": task.description[:200], "graph_type": task.graph_type},
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task.dispatched event",
            exc_info=True,
        )

    # PostHog analytics
    try:
        from nexus_api.analytics import track

        track(
            str(tenant.org_id),
            "selva_task_dispatched",
            {
                "graph_type": body.graph_type,
                "task_id": str(task.id),
            },
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit PostHog selva_task_dispatched event",
            exc_info=True,
        )

    response = _task_to_response(task)

    # Cache the response BEFORE returning so a network blip mid-response
    # on the first call still gives the second call something to replay.
    # No-op when the caller didn't send Idempotency-Key.
    if isinstance(idem, IdempotencyContext):
        await idem.save(response.model_dump(mode="json"))

    return response


@router.post(
    "/dispatch/ecosystem-app",
    response_model=SwarmTaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_non_guest),
        Depends(require_non_demo),
        Depends(require_dispatch_rate_limit),
    ],
)
async def dispatch_ecosystem_app_manifest(
    request: Request,
    body: Any = Body(None),
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> SwarmTaskResponse:
    """Dispatch an EcosystemApp manifest as a canonical deployment task."""
    if idem.is_replay and idem.cached is not None:
        return SwarmTaskResponse.model_validate(idem.cached)

    if body is None:
        body = await request.body()

    if isinstance(body, ManifestDispatchRequest):
        manifest_body = body
    elif isinstance(body, dict) and "manifest" in body:
        manifest_body = ManifestDispatchRequest.model_validate(body)
    else:
        manifest_body = ManifestDispatchRequest(manifest=body)

    manifest = _parse_ecosystem_app_manifest(manifest_body.manifest)
    dispatch_body = _deployment_dispatch_from_ecosystem_app(
        manifest,
        assigned_agent_ids=manifest_body.assigned_agent_ids,
        required_skills=manifest_body.required_skills,
        source=manifest_body.source,
        idempotency_key=manifest_body.idempotency_key or request.headers.get("Idempotency-Key"),
    )
    return await dispatch_task(dispatch_body, request, db=db, tenant=tenant, idem=idem)


@router.post(
    "/dispatch/ecosystem-app/verify",
    response_model=ManifestVerifyResponse,
    dependencies=[
        Depends(require_non_guest),
        Depends(require_non_demo),
    ],
)
async def verify_ecosystem_app_manifest(
    request: Request,
    body: Any = Body(None),
) -> ManifestVerifyResponse:
    """Read-only EcosystemApp/AppSpec verification; never dispatches or mutates."""
    if body is None:
        body = await request.body()

    if isinstance(body, ManifestDispatchRequest):
        manifest_body = body
    elif isinstance(body, dict) and "manifest" in body:
        manifest_body = ManifestDispatchRequest.model_validate(body)
    else:
        manifest_body = ManifestDispatchRequest(manifest=body)

    manifest = _parse_ecosystem_app_manifest(manifest_body.manifest)
    return _verify_ecosystem_app_manifest(manifest)


@router.get("/tasks", response_model=list[SwarmTaskResponse])
async def list_active_tasks(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[SwarmTaskResponse]:
    """List tasks that are currently queued or in progress."""
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.status.in_(["queued", "pending", "running"]))
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_task_to_response(t) for t in tasks]


class TaskBoardItem(BaseModel):
    id: str
    title: str | None
    description: str
    graph_type: str
    status: str
    kanban_status: str
    priority: str
    labels: list[str]
    due_date: str | None
    parent_task_id: str | None
    depends_on: list[str]
    agent_names: list[str]
    created_at: str
    updated_at: str | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    total_tokens: int | None
    event_count: int
    comment_count: int

    model_config = {"from_attributes": True}


class TaskBoardResponse(BaseModel):
    columns: dict[str, list[TaskBoardItem]]
    totals: dict[str, int]


@router.get("/tasks/board", response_model=TaskBoardResponse)
async def get_task_board(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> TaskBoardResponse:
    """Return tasks grouped by status column with aggregated event data."""
    # Fetch recent tasks (last N — see _TASK_BOARD_PAGE_SIZE).
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.created_at.desc())
        .limit(_TASK_BOARD_PAGE_SIZE)
    )
    tasks = result.scalars().all()

    # Aggregate event data per task
    task_ids = [t.id for t in tasks]
    event_agg: dict[str, dict] = {}
    if task_ids:
        agg_result = await db.execute(
            select(
                TaskEvent.task_id,
                func.sum(TaskEvent.duration_ms),
                func.sum(TaskEvent.token_count),
                func.count(TaskEvent.id),
            )
            .where(TaskEvent.task_id.in_(task_ids))
            .group_by(TaskEvent.task_id)
        )
        for row in agg_result:
            event_agg[str(row[0])] = {
                "duration_ms": row[1],
                "total_tokens": row[2],
                "event_count": row[3],
            }

    # Resolve agent names
    all_agent_ids: set[str] = set()
    for t in tasks:
        for aid in t.assigned_agent_ids or []:
            all_agent_ids.add(aid)

    agent_names: dict[str, str] = {}
    if all_agent_ids:
        for aid in all_agent_ids:
            # NOTE: ``uuid.UUID(aid)`` raises ``ValueError`` on malformed IDs,
            # and ``db.execute(...)`` can raise ``SQLAlchemyError`` (not a
            # ``ValueError`` subclass). ``Exception`` is the smallest common
            # ancestor that catches both — name-resolution is best-effort.
            try:
                uid = uuid.UUID(aid)
                agent_result = await db.execute(select(Agent).where(Agent.id == uid))
                agent = agent_result.scalar_one_or_none()
                if agent:
                    agent_names[aid] = agent.name
            except Exception:
                logging.getLogger(__name__).debug(
                    "Failed to resolve agent name for %s",
                    aid,
                    exc_info=True,
                )

    comment_counts: dict[str, int] = {}
    if task_ids:
        comment_result = await db.execute(
            select(TaskComment.task_id, func.count(TaskComment.id))
            .where(TaskComment.task_id.in_(task_ids))
            .group_by(TaskComment.task_id)
        )
        for comment_row in comment_result:
            comment_counts[str(comment_row[0])] = comment_row[1]

    # Build columns
    columns: dict[str, list[TaskBoardItem]] = {
        "todo": [],
        "in_progress": [],
        "review": [],
        "done": [],
        "blocked": [],
    }

    for t in tasks:
        task_id_str = str(t.id)
        agg = event_agg.get(task_id_str, {})
        col = t.kanban_status or _execution_status_to_kanban(t.status)
        if col not in columns:
            col = "todo"

        item = TaskBoardItem(
            id=task_id_str,
            title=t.title,
            description=t.description,
            graph_type=t.graph_type,
            status=t.status,
            kanban_status=col,
            priority=t.priority or "medium",
            labels=t.labels or [],
            due_date=t.due_date.isoformat() if t.due_date else None,
            parent_task_id=str(t.parent_task_id) if t.parent_task_id else None,
            depends_on=[str(dep) for dep in (t.depends_on or [])],
            agent_names=[agent_names.get(aid, aid[:8]) for aid in (t.assigned_agent_ids or [])],
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat() if t.updated_at else None,
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            duration_ms=agg.get("duration_ms"),
            total_tokens=agg.get("total_tokens"),
            event_count=agg.get("event_count", 0),
            comment_count=comment_counts.get(task_id_str, 0),
        )
        columns[col].append(item)

    totals = {col: len(items) for col, items in columns.items()}

    return TaskBoardResponse(columns=columns, totals=totals)


@router.get("/tasks/export")
async def export_kanban_tasks(
    format: str = Query(default="json", pattern=r"^(json|csv)$"),  # noqa: A002, B008
    kanban_status: str | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=1000, ge=1, le=5000),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> Response:
    """Export kanban tasks as JSON or CSV."""
    query = (
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.updated_at.desc(), SwarmTask.created_at.desc())
        .limit(limit)
    )
    if kanban_status:
        query = query.where(SwarmTask.kanban_status == kanban_status)

    result = await db.execute(query)
    items = [_task_to_export_item(task) for task in result.scalars().all()]

    if format == "csv":
        return Response(
            content=_task_export_csv(items),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="selva-kanban-tasks.csv"'},
        )

    return Response(
        content=json.dumps({"items": items}, default=str),
        media_type="application/json",
    )


@router.post(
    "/tasks/import",
    response_model=KanbanTaskImportResponse,
    dependencies=[Depends(require_non_guest)],
)
async def import_kanban_tasks(
    request: Request,
    format: str = Query(default="json", pattern=r"^(json|csv)$"),  # noqa: A002, B008
    user: dict = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> KanbanTaskImportResponse:
    """Import kanban tasks from JSON or CSV without enqueuing execution."""
    if format == "csv":
        body = (await request.body()).decode("utf-8")
        items = _import_items_from_csv(body)
    else:
        payload = await request.json()
        if isinstance(payload, list):
            payload = {"items": payload}
        import_request = KanbanTaskImportRequest.model_validate(payload)
        items = import_request.items

    actor_id = _actor_id_from_user(user)
    created_tasks: list[SwarmTask] = []
    for item in items:
        task = SwarmTask(
            title=item.title or _derive_task_title(item.description),
            description=item.description,
            graph_type=item.graph_type,
            assigned_agent_ids=item.assigned_agent_ids,
            payload={"source": "kanban_import"},
            status="backlog",
            kanban_status=item.kanban_status,
            priority=item.priority,
            labels=item.labels,
            due_date=_parse_optional_datetime(item.due_date, "due_date"),
            parent_task_id=_parse_optional_uuid(item.parent_task_id, "parent_task_id"),
            depends_on=_normalise_id_list(item.depends_on, "depends_on"),
            creator_id=actor_id,
            org_id=tenant.org_id,
        )
        db.add(task)
        await db.flush()
        _add_task_history(
            db,
            task=task,
            event_type="task.imported",
            actor_id=actor_id,
            payload={
                "source": "kanban_import",
                "kanban_status": task.kanban_status,
                "priority": task.priority,
            },
        )
        if task.assigned_agent_ids:
            await _emit_task_lifecycle_notification(
                db,
                task=task,
                kind="assigned",
                actor_id=actor_id,
                payload={"assigned_agent_ids": task.assigned_agent_ids, "source": "import"},
                dedupe_key="import",
            )
        created_tasks.append(task)

    await db.flush()
    for task in created_tasks:
        await db.refresh(task)
    return KanbanTaskImportResponse(
        created=len(created_tasks),
        tasks=[_task_to_response(task) for task in created_tasks],
    )


@router.get("/tasks/kanban-metrics", response_model=KanbanMetricsResponse)
async def get_kanban_metrics(
    limit: int = Query(default=1000, ge=1, le=5000),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> KanbanMetricsResponse:
    """Return kanban-specific throughput, WIP, blocked, and overdue metrics."""
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .order_by(SwarmTask.updated_at.desc(), SwarmTask.created_at.desc())
        .limit(limit)
    )
    tasks = result.scalars().all()
    now = datetime.now(UTC)
    status_counts = {
        status_key: 0
        for status_key in ["todo", "in_progress", "review", "done", "blocked"]
    }
    throughput_by_label: dict[str, int] = {}
    workload_by_assignee: dict[str, int] = {}
    wip_ages: list[float] = []
    cycle_times: list[float] = []
    overdue_count = 0
    dependency_blocked_count = 0
    status_by_task_id = {
        str(task.id): task.kanban_status or _execution_status_to_kanban(task.status)
        for task in tasks
    }

    for task in tasks:
        kanban_status = task.kanban_status or _execution_status_to_kanban(task.status)
        status_counts[kanban_status] = status_counts.get(kanban_status, 0) + 1
        if kanban_status in {"in_progress", "review"}:
            age = _seconds_between(task.updated_at or task.created_at, now)
            if age is not None:
                wip_ages.append(age)
        if kanban_status == "done":
            finished_at = task.completed_at or task.updated_at
            cycle_time = _seconds_between(task.created_at, finished_at)
            if cycle_time is not None:
                cycle_times.append(cycle_time)
            for label in task.labels or []:
                throughput_by_label[label] = throughput_by_label.get(label, 0) + 1
        for assignee in task.assigned_agent_ids or []:
            workload_by_assignee[assignee] = workload_by_assignee.get(assignee, 0) + 1
        if (
            _datetime_before(task.due_date, now)
            and kanban_status not in {"done", "blocked"}
        ):
            overdue_count += 1
        unresolved_dependencies = [
            dep_id
            for dep_id in task.depends_on or []
            if status_by_task_id.get(str(dep_id)) != "done"
        ]
        if unresolved_dependencies:
            dependency_blocked_count += 1

    return KanbanMetricsResponse(
        total=len(tasks),
        status_counts=status_counts,
        blocked_count=status_counts.get("blocked", 0),
        dependency_blocked_count=dependency_blocked_count,
        overdue_count=overdue_count,
        wip_count=status_counts.get("in_progress", 0) + status_counts.get("review", 0),
        avg_wip_age_seconds=(sum(wip_ages) / len(wip_ages)) if wip_ages else None,
        avg_cycle_time_seconds=(sum(cycle_times) / len(cycle_times)) if cycle_times else None,
        throughput_by_label=throughput_by_label,
        workload_by_assignee=workload_by_assignee,
    )


@router.post(
    "/tasks/claim",
    response_model=TaskClaimResponse,
    dependencies=[Depends(require_non_guest)],
)
async def claim_available_task(
    body: TaskClaimRequest,
    user: dict = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> TaskClaimResponse:
    """Claim the next available kanban task for an agent/operator.

    This is the benchmark-style worker claiming primitive. It updates only
    kanban ownership/progress state; runtime workers still drive execution
    through the existing status PATCH endpoint.
    """
    query = (
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .where(SwarmTask.kanban_status == "todo")
        .order_by(
            SwarmTask.due_date.asc().nullsfirst(),
            SwarmTask.created_at.asc(),
        )
        .limit(1)
    )
    if body.graph_type:
        query = query.where(SwarmTask.graph_type == body.graph_type)
    if body.labels:
        for label in body.labels:
            query = query.where(SwarmTask.labels.contains([label]))

    try:
        query = query.with_for_update(skip_locked=True)
    except Exception:
        logging.getLogger(__name__).debug("Database dialect does not support SKIP LOCKED")

    result = await db.execute(query)
    task = result.scalar_one_or_none()
    if task is None:
        return TaskClaimResponse(claimed=False)

    actor_id = body.agent_id or _actor_id_from_user(user)
    if body.agent_id and body.agent_id not in (task.assigned_agent_ids or []):
        task.assigned_agent_ids = [*(task.assigned_agent_ids or []), body.agent_id]
    task.kanban_status = "in_progress"
    _add_task_history(
        db,
        task=task,
        event_type="task.claimed",
        actor_id=actor_id,
        payload={
            "agent_id": body.agent_id,
            "kanban_status": task.kanban_status,
        },
    )
    await _emit_task_lifecycle_notification(
        db,
        task=task,
        kind="assigned",
        actor_id=actor_id,
        payload={"agent_id": body.agent_id, "source": "claim"},
        dedupe_key=f"claim:{body.agent_id or actor_id or 'unknown'}",
    )
    await db.flush()
    await db.refresh(task)
    return TaskClaimResponse(claimed=True, task=_task_to_response(task))


@router.post(
    "/tasks/notify-overdue",
    response_model=OverdueNotificationResponse,
    dependencies=[Depends(require_non_guest)],
)
async def notify_overdue_tasks(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> OverdueNotificationResponse:
    """Emit lifecycle notifications for overdue active kanban tasks."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(SwarmTask)
        .where(SwarmTask.org_id == tenant.org_id)
        .where(SwarmTask.due_date.is_not(None))
        .where(SwarmTask.due_date < now)
        .where(SwarmTask.kanban_status.not_in(["done", "blocked"]))
        .order_by(SwarmTask.due_date.asc())
        .limit(200)
    )
    tasks = result.scalars().all()
    notified = 0
    for task in tasks:
        emitted = await _emit_task_lifecycle_notification(
            db,
            task=task,
            kind="overdue",
            actor_id=None,
            payload={"source": "overdue_scan"},
            dedupe_key=task.due_date.isoformat() if task.due_date else None,
        )
        if emitted:
            notified += 1
    await db.flush()
    return OverdueNotificationResponse(scanned=len(tasks), notified=notified)


@router.post("/tasks/notify-overdue-all", response_model=OverdueNotificationResponse)
async def notify_overdue_tasks_all(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> OverdueNotificationResponse:
    """Emit overdue notifications across all tenants for worker/platform callers."""
    from ..database import admin_session

    roles = user.get("roles", [])
    if not any(r in _REAP_STALE_ALLOWED_ROLES for r in roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "notify-overdue-all is a platform-only endpoint; caller must hold "
                "service, worker, platform, or admin role"
            ),
        )

    now = datetime.now(UTC)
    async with admin_session() as db:
        result = await db.execute(
            select(SwarmTask)
            .where(SwarmTask.due_date.is_not(None))
            .where(SwarmTask.due_date < now)
            .where(SwarmTask.kanban_status.not_in(["done", "blocked"]))
            .order_by(SwarmTask.org_id.asc(), SwarmTask.due_date.asc())
            .limit(2000)
        )
        tasks = result.scalars().all()
        notified = 0
        for task in tasks:
            emitted = await _emit_task_lifecycle_notification(
                db,
                task=task,
                kind="overdue",
                actor_id=None,
                payload={"source": "overdue_cross_tenant_scan"},
                dedupe_key=task.due_date.isoformat() if task.due_date else None,
            )
            if emitted:
                notified += 1
        await db.flush()
    return OverdueNotificationResponse(scanned=len(tasks), notified=notified)


@router.get("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> SwarmTaskResponse:
    """Retrieve a single task by ID."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(
        select(SwarmTask).where(SwarmTask.id == uid).where(SwarmTask.org_id == tenant.org_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return _task_to_response(task)


@router.patch(
    "/tasks/{task_id}/kanban",
    response_model=SwarmTaskResponse,
    dependencies=[Depends(require_non_guest)],
)
async def update_task_kanban(
    task_id: str,
    body: KanbanTaskUpdate,
    user: dict = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> SwarmTaskResponse:
    """Update first-class kanban metadata for a task."""
    uid = _parse_optional_uuid(task_id, "task_id")
    result = await db.execute(
        select(SwarmTask).where(SwarmTask.id == uid).where(SwarmTask.org_id == tenant.org_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    actor_id = _actor_id_from_user(user)
    before = _task_to_response(task).model_dump()

    if body.title is not None:
        task.title = body.title
    if body.kanban_status is not None:
        task.kanban_status = body.kanban_status
    if body.priority is not None:
        task.priority = body.priority
    if body.labels is not None:
        task.labels = body.labels
    if body.due_date is not None:
        task.due_date = _parse_optional_datetime(body.due_date, "due_date")
    if body.parent_task_id is not None:
        task.parent_task_id = _parse_optional_uuid(body.parent_task_id, "parent_task_id")
    if body.depends_on is not None:
        task.depends_on = _normalise_id_list(body.depends_on, "depends_on")

    after = {
        "title": task.title,
        "kanban_status": task.kanban_status,
        "priority": task.priority,
        "labels": task.labels or [],
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "depends_on": [str(dep) for dep in (task.depends_on or [])],
    }
    _add_task_history(
        db,
        task=task,
        event_type="task.kanban_updated",
        actor_id=actor_id,
        payload={"before": before, "after": after},
    )

    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.kanban_updated",
            event_category="task",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=task.org_id,
            payload=after,
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task.kanban_updated event",
            exc_info=True,
        )

    notification_kind = _notification_kind_for_kanban_status(task.kanban_status)
    if notification_kind and before.get("kanban_status") != task.kanban_status:
        await _emit_task_lifecycle_notification(
            db,
            task=task,
            kind=notification_kind,
            actor_id=actor_id,
            payload={
                "source": "kanban_update",
                "old_kanban_status": before.get("kanban_status"),
            },
            dedupe_key=task.kanban_status,
        )

    due_date = task.due_date
    if (
        due_date is not None
        and _datetime_before(due_date, datetime.now(UTC))
        and task.kanban_status not in {"done", "blocked"}
    ):
        await _emit_task_lifecycle_notification(
            db,
            task=task,
            kind="overdue",
            actor_id=actor_id,
            payload={"source": "kanban_update"},
            dedupe_key=due_date.isoformat(),
        )

    await db.flush()
    await db.refresh(task)
    return _task_to_response(task)


@router.get("/tasks/{task_id}/comments", response_model=list[TaskCommentResponse])
async def list_task_comments(
    task_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[TaskCommentResponse]:
    uid = _parse_optional_uuid(task_id, "task_id")
    result = await db.execute(
        select(TaskComment)
        .where(TaskComment.task_id == uid)
        .where(TaskComment.org_id == tenant.org_id)
        .order_by(TaskComment.created_at.asc())
    )
    return [_task_comment_to_response(comment) for comment in result.scalars().all()]


@router.post(
    "/tasks/{task_id}/comments",
    response_model=TaskCommentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def create_task_comment(
    task_id: str,
    body: TaskCommentCreate,
    user: dict = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> TaskCommentResponse:
    uid = _parse_optional_uuid(task_id, "task_id")
    task_result = await db.execute(
        select(SwarmTask).where(SwarmTask.id == uid).where(SwarmTask.org_id == tenant.org_id)
    )
    task = task_result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    actor_id = _actor_id_from_user(user)
    comment = TaskComment(
        task_id=task.id,
        org_id=task.org_id,
        author_id=actor_id,
        body=body.body,
    )
    db.add(comment)
    await db.flush()
    _add_task_history(
        db,
        task=task,
        event_type="task.comment_added",
        actor_id=actor_id,
        payload={"comment_id": str(comment.id)},
    )
    await db.flush()
    await db.refresh(comment)
    return _task_comment_to_response(comment)


@router.get("/tasks/{task_id}/history", response_model=list[TaskHistoryResponse])
async def list_task_history(
    task_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> list[TaskHistoryResponse]:
    uid = _parse_optional_uuid(task_id, "task_id")
    result = await db.execute(
        select(TaskHistory)
        .where(TaskHistory.task_id == uid)
        .where(TaskHistory.org_id == tenant.org_id)
        .order_by(TaskHistory.created_at.asc())
    )
    return [_task_history_to_response(item) for item in result.scalars().all()]


@router.get("/evidence", response_model=DeploymentEvidenceRecordListResponse)
async def list_deployment_evidence_records(
    task_id: str | None = Query(default=None),  # noqa: B008
    graph_type: str | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> DeploymentEvidenceRecordListResponse:
    """List deployment evidence records, newest first. Tenant-scoped."""
    query = select(DeploymentEvidenceRecord).where(
        DeploymentEvidenceRecord.org_id == tenant.org_id
    )

    if task_id:
        try:
            task_uid = uuid.UUID(task_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid task_id UUID",
            ) from exc
        query = query.where(DeploymentEvidenceRecord.task_id == task_uid)

    if graph_type:
        query = query.where(DeploymentEvidenceRecord.graph_type == graph_type)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(DeploymentEvidenceRecord.created_at.desc()).limit(limit).offset(offset)
    )
    records = result.scalars().all()

    return DeploymentEvidenceRecordListResponse(
        evidence_records=[_evidence_record_to_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/evidence/{evidence_id}", response_model=DeploymentEvidenceRecordResponse)
async def get_deployment_evidence_record(
    evidence_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    tenant: TenantContext = Depends(get_tenant),  # noqa: B008
) -> DeploymentEvidenceRecordResponse:
    """Retrieve one deployment evidence record by ID. Tenant-scoped."""
    try:
        uid = uuid.UUID(evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(
        select(DeploymentEvidenceRecord)
        .where(DeploymentEvidenceRecord.id == uid)
        .where(DeploymentEvidenceRecord.org_id == tenant.org_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment evidence record not found",
        )

    return _evidence_record_to_response(record)


@router.patch("/tasks/{task_id}", response_model=SwarmTaskResponse)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SwarmTaskResponse:
    """Update a task's status.

    When the status transitions to ``completed`` or ``failed`` the
    ``completed_at`` timestamp is set automatically.
    """
    try:
        uid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID") from exc

    result = await db.execute(select(SwarmTask).where(SwarmTask.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Capture old status for the audit event payload (lets OpsFeed render
    # "queued → running" arrows without a follow-up DB query).
    old_status = task.status

    task.status = body.status
    old_kanban_status = task.kanban_status or _execution_status_to_kanban(old_status)
    new_kanban_status = _execution_status_to_kanban(body.status)
    if body.status in {"running", "completed", "failed", "cancelled"}:
        task.kanban_status = new_kanban_status

    if body.result is not None:
        task.payload = {**(task.payload or {}), "result": body.result}

    if body.started_at is not None:
        task.started_at = datetime.fromisoformat(body.started_at)

    if body.error_message is not None:
        task.error_message = body.error_message

    if body.status in ("completed", "failed"):
        task.completed_at = datetime.now(UTC)

    deployment_evidence = body.deployment_evidence
    if deployment_evidence is None and body.result is not None:
        result_evidence = body.result.get("deployment_evidence")
        if isinstance(result_evidence, dict):
            deployment_evidence = result_evidence

    if deployment_evidence is not None:
        db.add(
            DeploymentEvidenceRecord(
                task_id=task.id,
                org_id=task.org_id,
                graph_type=task.graph_type,
                deployment_status=_deployment_status_from_evidence(
                    deployment_evidence,
                    body.result,
                    body.status,
                ),
                evidence=deployment_evidence,
            )
        )
    record_deployment_status_update(task, deployment_evidence)

    runtime_notification_kind = {
        "completed": "completed",
        "failed": "blocked",
        "cancelled": "blocked",
    }.get(body.status)
    if runtime_notification_kind:
        await _emit_task_lifecycle_notification(
            db,
            task=task,
            kind=runtime_notification_kind,
            actor_id=None,
            payload={
                "source": "runtime_status",
                "old_status": old_status,
                "new_status": body.status,
            },
            dedupe_key=body.status,
        )

    await db.flush()
    await db.refresh(task)

    # Audit trail: emit task.status_changed event. Worker writes back
    # queued → running → completed/failed via this PATCH; today the table
    # holds the truth but the event stream doesn't, forcing OpsFeed to
    # poll. Carrying old → new in the payload lets clients render
    # transitions without an extra fetch. See gap doc #3.
    #
    # org_id is taken from the task row itself (the resource being
    # mutated), not from the worker's X-Selva-Tenant-Org header — the
    # truth-of-record for "which tenant owns this task" lives on the
    # row. error_message is intentionally excluded from the payload
    # because it can carry stack traces / file paths that other tenants
    # in the same org should not necessarily see in the activity feed.
    try:
        from .events import emit_event_db

        await emit_event_db(
            db,
            event_type="task.status_changed",
            event_category="task",
            task_id=task.id,
            graph_type=task.graph_type,
            org_id=task.org_id,
            payload={
                "task_id": str(task.id),
                "old_status": old_status,
                "new_status": task.status,
            },
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to emit task.status_changed event",
            exc_info=True,
        )

    if old_kanban_status != task.kanban_status:
        _add_task_history(
            db,
            task=task,
            event_type="task.kanban_status_changed",
            actor_id=None,
            payload={
                "old_kanban_status": old_kanban_status,
                "new_kanban_status": task.kanban_status,
                "runtime_status": task.status,
            },
        )

    return _task_to_response(task)


# Roles allowed to call the cross-tenant reap-stale endpoint. ``service``
# and ``worker`` cover automated callers (cron jobs, ops tooling using the
# worker shared-secret token); ``platform`` and ``admin`` cover human
# operators. Any other authenticated caller (regular tactician, guest,
# demo) is rejected with 403.
_REAP_STALE_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"service", "worker", "platform", "admin"}
)


@router.post("/tasks/reap-stale")
async def reap_stale_tasks(
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict[str, int]:
    """Auto-fail queued/pending tasks older than 1 hour (cross-tenant ops).

    This is a platform health endpoint that operators or a cron job call
    to clean up stuck tasks across **all tenants**. The role gate is the
    access control: only callers carrying ``service``, ``worker``,
    ``platform``, or ``admin`` roles may invoke it.

    Tenancy bypass (Phase 1.5 -- migration 0028):
        Uses ``admin_session()`` which opens a session against the
        ``app_admin`` BYPASSRLS connection pool. This is the canonical
        way to express "I genuinely need to read/mutate rows belonging
        to multiple tenants in one query" under the strict RLS policies
        installed by migration 0028.

        Pre-migration-0028 this endpoint relied on the Phase 1 permissive
        policy (``IS NULL OR = '' OR = $org``) and manually reset the
        session var to ``""`` to fall through to the IS NULL leg. That
        leg no longer exists -- under the strict policies a reset
        session var would return zero rows. ``admin_session()`` logs at
        WARNING on every entry, so the cross-tenant access is visible in
        structured logs without needing to parse pg_stat_activity.

        See ``docs/RLS_PHASE_1_5_AUDIT.md`` §2.C and §3 for the full
        rationale.
    """
    from datetime import timedelta

    from ..database import admin_session

    roles = user.get("roles", [])
    if not any(r in _REAP_STALE_ALLOWED_ROLES for r in roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "reap-stale is a platform-only endpoint; caller must hold "
                "service, worker, platform, or admin role"
            ),
        )

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    async with admin_session() as db:
        result = await db.execute(
            select(SwarmTask)
            .where(SwarmTask.status.in_(["queued", "pending"]))
            .where(SwarmTask.created_at < cutoff)
        )
        stale_tasks = result.scalars().all()

        for task in stale_tasks:
            task.status = "failed"
            task.error_message = "Reaped: stale task older than 1 hour"
            task.completed_at = datetime.now(UTC)

        await db.flush()
        reaped_count = len(stale_tasks)

    if reaped_count:
        logging.getLogger(__name__).warning(
            "Reaped %d stale task(s) across all tenants (caller=%s)",
            reaped_count,
            user.get("sub", "unknown"),
        )

    return {"reaped": reaped_count}
