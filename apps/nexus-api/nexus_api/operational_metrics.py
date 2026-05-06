"""Operational Prometheus metrics for deploy reliability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from .database import async_session_factory
from .models import DeploymentEvidenceRecord, SwarmTask, SwarmTaskOutbox

try:
    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, generate_latest

    OUTBOX_DEPTH = Gauge(
        "selva_swarm_task_outbox_depth",
        "Current durable swarm task outbox rows by retry status.",
        ["status"],
    )
    OUTBOX_STALE_ROWS = Gauge(
        "selva_swarm_task_outbox_stale_rows",
        "Current pending/retryable swarm task outbox rows older than the stale threshold.",
    )
    DEPLOYMENT_EVIDENCE_POLICY_FAILURES = Counter(
        "selva_deployment_evidence_policy_failures_total",
        "Deployment evidence policy gate failures.",
        ["graph_type", "reason"],
    )
    PRODUCTION_EVIDENCE_INCOMPLETE = Counter(
        "selva_production_deployment_evidence_incomplete_total",
        "Production deployment task completions missing required deployment evidence.",
        ["graph_type", "reason"],
    )
    PRODUCTION_DEPLOY_FAILURES_AFTER_POLICY_GATE = Counter(
        "selva_production_deploy_failures_after_policy_gate_total",
        "Production deployment failures after the evidence policy gate passed.",
        ["graph_type"],
    )
    MISSING_PRODUCTION_EVIDENCE_ROWS = Gauge(
        "selva_production_deployment_missing_evidence_rows",
        "Completed or failed production deployment tasks without a deployment evidence ledger row.",
    )
    _HAS_PROMETHEUS = True
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"  # type: ignore[assignment]
    _HAS_PROMETHEUS = False


_OUTBOX_RETRYABLE_STATUSES = ("pending", "retryable")
_REQUIRED_PRODUCTION_EVIDENCE = (
    "preflight",
    "deploy",
    "argo_sync",
    "argo_health",
    "smoke",
    "status_check",
    "rollback_evidence",
    "evidence_policy",
)


def _deployment_environment(task: SwarmTask, evidence: dict[str, Any] | None) -> str:
    payload = task.payload or {}
    return str(
        (evidence or {}).get("environment")
        or payload.get("environment")
        or payload.get("target_environment")
        or ""
    ).lower()


def _evidence_policy(evidence: dict[str, Any] | None) -> dict[str, Any]:
    policy = (evidence or {}).get("evidence_policy")
    return policy if isinstance(policy, dict) else {}


def _production_evidence_gap(evidence: dict[str, Any] | None) -> str | None:
    if not evidence:
        return "missing"
    for key in _REQUIRED_PRODUCTION_EVIDENCE:
        value = evidence.get(key)
        if not isinstance(value, dict) or not value.get("status"):
            return f"missing_{key}"
    if str(_evidence_policy(evidence).get("status") or "").lower() != "passed":
        return "policy_not_passed"
    return None


def record_deployment_status_update(task: SwarmTask, evidence: dict[str, Any] | None) -> None:
    """Update counters for a deployment task terminal status update."""
    if not _HAS_PROMETHEUS or task.graph_type != "deployment":
        return

    policy = _evidence_policy(evidence)
    policy_status = str(policy.get("status") or "").lower()
    if policy_status == "failed":
        reason = str(policy.get("reason") or "policy_failed")[:80]
        DEPLOYMENT_EVIDENCE_POLICY_FAILURES.labels(task.graph_type, reason).inc()

    if _deployment_environment(task, evidence) != "production":
        return

    gap = _production_evidence_gap(evidence)
    if gap is not None and task.status in ("completed", "failed"):
        PRODUCTION_EVIDENCE_INCOMPLETE.labels(task.graph_type, gap).inc()

    if task.status == "failed" and policy_status == "passed":
        PRODUCTION_DEPLOY_FAILURES_AFTER_POLICY_GATE.labels(task.graph_type).inc()


async def _refresh_db_gauges() -> None:
    stale_before = datetime.now(UTC) - timedelta(minutes=10)
    async with async_session_factory() as db:
        depth_result = await db.execute(
            select(SwarmTaskOutbox.status, func.count(SwarmTaskOutbox.id))
            .where(SwarmTaskOutbox.status.in_(_OUTBOX_RETRYABLE_STATUSES))
            .group_by(SwarmTaskOutbox.status)
        )
        counts = {status: count for status, count in depth_result}
        for status in _OUTBOX_RETRYABLE_STATUSES:
            OUTBOX_DEPTH.labels(status).set(counts.get(status, 0))

        stale_result = await db.execute(
            select(func.count(SwarmTaskOutbox.id))
            .where(SwarmTaskOutbox.status.in_(_OUTBOX_RETRYABLE_STATUSES))
            .where(
                or_(
                    SwarmTaskOutbox.next_attempt_at.is_(None),
                    SwarmTaskOutbox.next_attempt_at <= stale_before,
                )
            )
            .where(SwarmTaskOutbox.created_at <= stale_before)
        )
        OUTBOX_STALE_ROWS.set(stale_result.scalar_one() or 0)

        missing_evidence_result = await db.execute(
            select(func.count(SwarmTask.id))
            .where(SwarmTask.graph_type == "deployment")
            .where(SwarmTask.status.in_(("completed", "failed")))
            .where(
                or_(
                    SwarmTask.payload["environment"].as_string() == "production",
                    SwarmTask.payload["target_environment"].as_string() == "production",
                )
            )
            .where(
                ~select(DeploymentEvidenceRecord.id)
                .where(DeploymentEvidenceRecord.task_id == SwarmTask.id)
                .exists()
            )
        )
        MISSING_PRODUCTION_EVIDENCE_ROWS.set(missing_evidence_result.scalar_one() or 0)


async def render_prometheus_metrics() -> tuple[bytes, str]:
    """Refresh DB-backed gauges and render the default Prometheus registry."""
    if not _HAS_PROMETHEUS:
        return b"# prometheus-client not installed\n", CONTENT_TYPE_LATEST
    await _refresh_db_gauges()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
