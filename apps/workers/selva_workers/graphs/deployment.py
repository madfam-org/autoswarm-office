"""Deployment workflow graph -- validate, approve, deploy, monitor."""

from __future__ import annotations

import logging
from typing import TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ..event_emitter import instrumented_node
from .base import BaseGraphState, check_permission
from .base import run_async as _run_async

logger = logging.getLogger(__name__)


# -- State --------------------------------------------------------------------


class DeploymentState(BaseGraphState, TypedDict, total=False):
    """Extended state for the deployment workflow."""

    service: str
    environment: str
    image_tag: str
    overlay_path: str
    repo_path: str
    gitops_app: str
    smoke_checks: list
    smoke_status: str
    current_pointer: dict
    rollback_pointer: dict
    rollback_evidence_artifact: dict
    deploy_id: str
    deploy_status: str
    argo_sync_status: str
    argo_health_status: str
    deployment_evidence: dict


_SUCCESS_DEPLOY_STATUSES = {
    "completed",
    "deployed",
    "healthy",
    "succeeded",
    "success",
    "synced",
}
_PENDING_DEPLOY_STATUSES = {
    "accepted",
    "created",
    "deploying",
    "in_progress",
    "pending",
    "queued",
    "running",
}


def _evidence(state: DeploymentState, key: str, value: object) -> dict:
    evidence = dict(state.get("deployment_evidence") or {})
    evidence[key] = value
    return evidence


# -- Node functions -----------------------------------------------------------


@instrumented_node
def validate(state: DeploymentState) -> DeploymentState:
    """Validate deployment parameters and check permissions.

    Rejects the task if the ``deploy`` permission is denied or if the
    ``service`` field is missing.
    """
    messages = state.get("messages", [])
    service = state.get("service", "")
    environment = state.get("environment", "staging")
    image_tag = state.get("image_tag", "latest")
    overlay_path = state.get("overlay_path", "")
    gitops_app = state.get("gitops_app", "")
    smoke_checks = state.get("smoke_checks", [])
    rollback_pointer = state.get("rollback_pointer", {})

    if not service:
        error_msg = AIMessage(content="Deployment rejected: 'service' is required.")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "failed", "reason": "service is required"},
            ),
        }

    if environment == "production" and (image_tag == "latest" or image_tag.endswith(":latest")):
        error_msg = AIMessage(
            content="Deployment rejected: production image_tag must not be latest."
        )
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "failed", "reason": "production image_tag is mutable"},
            ),
        }

    if environment == "production" and not gitops_app:
        error_msg = AIMessage(content="Deployment rejected: production requires gitops_app.")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "failed", "reason": "gitops_app required for production"},
            ),
        }

    if environment == "production" and not smoke_checks:
        error_msg = AIMessage(content="Deployment rejected: production requires smoke_checks.")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "failed", "reason": "smoke_checks required for production"},
            ),
        }

    if environment == "production" and not rollback_pointer:
        error_msg = AIMessage(content="Deployment rejected: production requires rollback_pointer.")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "failed", "reason": "rollback_pointer required for production"},
            ),
        }

    from selva_permissions.types import PermissionLevel

    perm = check_permission(state, "deploy")
    if perm.level == PermissionLevel.DENY:
        deny_msg = AIMessage(content="Deployment denied by permission engine.")
        return {
            **state,
            "messages": [*messages, deny_msg],
            "status": "blocked",
            "deployment_evidence": _evidence(
                state,
                "validation",
                {"status": "blocked", "reason": "permission denied"},
            ),
        }

    validate_msg = AIMessage(
        content=(
            f"Deployment validated: service={service}, "
            f"environment={environment}, image_tag={image_tag}, overlay_path={overlay_path or 'unset'}."
        ),
        additional_kwargs={"action_category": "deploy"},
    )
    return {
        **state,
        "messages": [*messages, validate_msg],
        "status": "validated",
        "deployment_evidence": _evidence(
            state,
            "validation",
            {
                "status": "passed",
                "service": service,
                "environment": environment,
                "image_tag": image_tag,
                "overlay_path": overlay_path,
                "gitops_app": gitops_app,
                "smoke_checks_count": len(smoke_checks),
                "rollback_pointer_present": bool(rollback_pointer),
            },
        ),
    }


@instrumented_node
def preflight(state: DeploymentState) -> DeploymentState:
    """Run manifest preflight before approval/deploy.

    Production deploys must provide an overlay path so digest/resource
    checks can run. Staging can continue with explicit skipped evidence.
    """
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked", "error"):
        return state

    environment = state.get("environment", "staging")
    overlay_path = state.get("overlay_path", "")
    repo_path = state.get("repo_path", ".")

    if not overlay_path:
        if environment == "production":
            error_msg = AIMessage(
                content="Deployment preflight failed: production requires overlay_path."
            )
            return {
                **state,
                "messages": [*messages, error_msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "preflight",
                    {"status": "failed", "reason": "overlay_path required for production"},
                ),
            }

        skip_msg = AIMessage(
            content="Deployment preflight skipped: overlay_path not provided.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, skip_msg],
            "status": "preflight_skipped",
            "deployment_evidence": _evidence(
                state,
                "preflight",
                {"status": "skipped", "reason": "overlay_path not provided"},
            ),
        }

    try:
        from selva_tools.builtins.deploy_preflight import DeployPreflightTool

        tool = DeployPreflightTool()
        result = _run_async(
            tool.execute(
                overlay_path=overlay_path,
                repo_path=repo_path,
                checks=["all"] if environment == "production" else [],
            )
        )
        preflight_data = result.data or {}
        verdict = preflight_data.get("verdict", "unknown")
        if result.success and verdict == "ready":
            msg = AIMessage(
                content=f"Deployment preflight passed: {overlay_path}.",
                additional_kwargs={"action_category": "deploy"},
            )
            return {
                **state,
                "messages": [*messages, msg],
                "status": "preflight_passed",
                "deployment_evidence": _evidence(
                    state,
                    "preflight",
                    {"status": "passed", **preflight_data},
                ),
            }

        msg = AIMessage(content=f"Deployment preflight blocked: {preflight_data or result.error}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "blocked",
            "deployment_evidence": _evidence(
                state,
                "preflight",
                {
                    "status": "blocked",
                    "error": result.error,
                    "data": preflight_data,
                },
            ),
        }
    except Exception as exc:
        logger.exception("Deployment preflight failed")
        error_msg = AIMessage(content=f"Deployment preflight exception: {exc}")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "preflight",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def deploy_gate(state: DeploymentState) -> DeploymentState:
    """Interrupt execution before deployment to require human approval.

    Uses LangGraph's ``interrupt()`` to pause the graph.  The Tactician
    must approve before the deployment proceeds.
    """
    if state.get("status") in ("error", "blocked"):
        return state

    service = state.get("service", "unknown")
    environment = state.get("environment", "staging")
    image_tag = state.get("image_tag", "latest")

    approval_context = {
        "action": "deploy",
        "action_category": "deploy",
        "service": service,
        "environment": environment,
        "image_tag": image_tag,
        "evidence": state.get("deployment_evidence") or {},
    }

    decision = interrupt(approval_context)

    if decision.get("approved", False):
        approve_msg = AIMessage(
            content=f"Deployment approved: {service} → {environment}.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*state.get("messages", []), approve_msg],
            "status": "approved",
            "deployment_evidence": _evidence(
                state,
                "approval",
                {"status": "approved"},
            ),
        }

    feedback = decision.get("feedback", "No feedback provided")
    deny_msg = AIMessage(
        content=f"Deployment denied. Feedback: {feedback}",
        additional_kwargs={"action_category": "deploy"},
    )
    return {
        **state,
        "messages": [*state.get("messages", []), deny_msg],
        "status": "denied",
        "deployment_evidence": _evidence(
            state,
            "approval",
            {"status": "denied", "feedback": feedback},
        ),
    }


@instrumented_node
def deploy(state: DeploymentState) -> DeploymentState:
    """Trigger the deployment via the DeployTool.

    Skips if the deployment was denied or blocked at an earlier stage.
    """
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked", "error"):
        return state

    service = state.get("service", "")
    environment = state.get("environment", "staging")
    image_tag = state.get("image_tag", "latest")

    try:
        import os

        from selva_tools.builtins.deploy import DeployTool

        # Inject Enclii credentials from worker config.
        from selva_workers.config import get_settings

        settings = get_settings()
        if settings.enclii_deploy_token:
            os.environ.setdefault("ENCLII_DEPLOY_TOKEN", settings.enclii_deploy_token)

        tool = DeployTool()
        result = _run_async(
            tool.execute(
                service=service,
                environment=environment,
                image_tag=image_tag,
            )
        )

        if result.success:
            deploy_id = result.data.get("deploy_id", "")
            deploy_msg = AIMessage(
                content=f"Deployment triggered: {deploy_id}",
                additional_kwargs={"action_category": "deploy"},
            )
            return {
                **state,
                "messages": [*messages, deploy_msg],
                "deploy_id": deploy_id,
                "deploy_status": result.data.get("status", "pending"),
                "status": "deploying",
                "deployment_evidence": _evidence(
                    state,
                    "deploy_trigger",
                    {
                        "status": "triggered",
                        "deploy_id": deploy_id,
                        "data": result.data,
                    },
                ),
            }
        else:
            error_msg = AIMessage(content=f"Deployment failed: {result.error}")
            return {
                **state,
                "messages": [*messages, error_msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "deploy_trigger",
                    {"status": "failed", "error": result.error},
                ),
            }
    except Exception as exc:
        logger.exception("Deployment execution failed")
        error_msg = AIMessage(content=f"Deployment exception: {exc}")
        return {
            **state,
            "messages": [*messages, error_msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "deploy_trigger",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def argo_sync(state: DeploymentState) -> DeploymentState:
    """Refresh and sync the declared Argo CD application.

    This is intentionally separate from the Enclii deploy trigger so GitOps
    convergence has its own evidence and failure mode.
    """
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked", "error"):
        return state

    gitops_app = state.get("gitops_app", "")
    environment = state.get("environment", "staging")
    if not gitops_app:
        if environment == "production":
            msg = AIMessage(content="Argo sync blocked: production requires gitops_app.")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "argo_sync",
                    {"status": "failed", "reason": "gitops_app required for production"},
                ),
            }
        msg = AIMessage(
            content="Argo sync skipped: gitops_app not provided.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, msg],
            "deployment_evidence": _evidence(
                state,
                "argo_sync",
                {"status": "skipped", "reason": "gitops_app not provided"},
            ),
        }

    try:
        from selva_tools.builtins.argocd import ArgocdRefreshAppTool, ArgocdSyncAppTool

        refresh = _run_async(ArgocdRefreshAppTool().execute(name=gitops_app, type="hard"))
        if not refresh.success:
            msg = AIMessage(content=f"Argo refresh failed for {gitops_app}: {refresh.error}")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "argo_sync",
                    {"status": "failed", "phase": "refresh", "error": refresh.error},
                ),
            }

        sync = _run_async(ArgocdSyncAppTool().execute(name=gitops_app, prune=False, force=False))
        if not sync.success:
            msg = AIMessage(content=f"Argo sync failed for {gitops_app}: {sync.error}")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "argo_sync",
                    {"status": "failed", "phase": "sync", "error": sync.error},
                ),
            }

        msg = AIMessage(
            content=f"Argo sync triggered for {gitops_app}.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, msg],
            "deployment_evidence": _evidence(
                state,
                "argo_sync",
                {
                    "status": "triggered",
                    "app": gitops_app,
                    "refresh": refresh.data,
                    "sync": sync.data,
                },
            ),
        }
    except Exception as exc:
        logger.exception("Argo sync failed")
        msg = AIMessage(content=f"Argo sync exception: {exc}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "argo_sync",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def argo_health(state: DeploymentState) -> DeploymentState:
    """Require GitOps app to be synced and healthy before final status check."""
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked", "error"):
        return state

    gitops_app = state.get("gitops_app", "")
    environment = state.get("environment", "staging")
    if not gitops_app:
        return state

    try:
        from selva_tools.builtins.argocd import ArgocdGetAppTool

        result = _run_async(ArgocdGetAppTool().execute(name=gitops_app))
        if not result.success:
            msg = AIMessage(content=f"Argo health failed for {gitops_app}: {result.error}")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "argo_health",
                    {"status": "failed", "error": result.error},
                ),
            }

        sync_status = ((result.data or {}).get("sync") or {}).get("status", "Unknown")
        health_status = ((result.data or {}).get("health") or {}).get("status", "Unknown")
        msg = AIMessage(
            content=f"Argo {gitops_app}: sync={sync_status} health={health_status}",
            additional_kwargs={"action_category": "deploy"},
        )
        healthy = sync_status == "Synced" and health_status == "Healthy"
        if not healthy and environment == "production":
            terminal_status = "error"
        elif not healthy:
            terminal_status = "deploying"
        else:
            terminal_status = state.get("status", "deploying")

        return {
            **state,
            "messages": [*messages, msg],
            "argo_sync_status": sync_status,
            "argo_health_status": health_status,
            "status": terminal_status,
            "deployment_evidence": _evidence(
                state,
                "argo_health",
                {
                    "status": "passed" if healthy else "unhealthy",
                    "app": gitops_app,
                    "sync": sync_status,
                    "health": health_status,
                    "data": result.data,
                },
            ),
        }
    except Exception as exc:
        logger.exception("Argo health check failed")
        msg = AIMessage(content=f"Argo health exception: {exc}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "argo_health",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def smoke(state: DeploymentState) -> DeploymentState:
    """Run endpoint smoke checks after GitOps health is proven."""
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked", "error"):
        return state

    environment = state.get("environment", "staging")
    smoke_checks = state.get("smoke_checks", [])
    if not smoke_checks:
        if environment == "production":
            msg = AIMessage(content="Smoke check failed: production requires smoke_checks.")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "smoke_status": "missing",
                "deployment_evidence": _evidence(
                    state,
                    "smoke",
                    {"status": "failed", "reason": "smoke_checks required for production"},
                ),
            }
        msg = AIMessage(
            content="Smoke check skipped: smoke_checks not provided.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, msg],
            "smoke_status": "skipped",
            "deployment_evidence": _evidence(
                state,
                "smoke",
                {"status": "skipped", "reason": "smoke_checks not provided"},
            ),
        }

    try:
        from selva_tools.builtins.smoke import EndpointSmokeCheckTool

        result = _run_async(EndpointSmokeCheckTool().execute(endpoints=smoke_checks))
        smoke_data = result.data or {}
        smoke_status = str(smoke_data.get("verdict") or ("passed" if result.success else "blocked"))
        if result.success:
            msg = AIMessage(
                content=f"Smoke checks passed: {smoke_data.get('passed_count', 0)}/{len(smoke_checks)}.",
                additional_kwargs={"action_category": "deploy"},
            )
            return {
                **state,
                "messages": [*messages, msg],
                "smoke_status": smoke_status,
                "deployment_evidence": _evidence(
                    state,
                    "smoke",
                    {"status": "passed", **smoke_data},
                ),
            }

        msg = AIMessage(content=f"Smoke checks blocked deployment: {result.error or smoke_data}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "smoke_status": smoke_status,
            "deployment_evidence": _evidence(
                state,
                "smoke",
                {
                    "status": "blocked",
                    "error": result.error,
                    "data": smoke_data,
                },
            ),
        }
    except Exception as exc:
        logger.exception("Smoke checks failed")
        msg = AIMessage(content=f"Smoke check exception: {exc}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "smoke_status": "failed",
            "deployment_evidence": _evidence(
                state,
                "smoke",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def monitor(state: DeploymentState) -> DeploymentState:
    """Check deployment status via the DeployStatusTool.

    Skips if the deployment was not triggered.
    """
    messages = state.get("messages", [])
    deploy_id = state.get("deploy_id", "")

    if state.get("status") in ("denied", "blocked", "error"):
        return state
    if not deploy_id:
        return {
            **state,
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "status_check",
                {"status": "failed", "reason": "deploy_id missing"},
            ),
        }

    try:
        from selva_tools.builtins.deploy import DeployStatusTool

        tool = DeployStatusTool()
        result = _run_async(tool.execute(deploy_id=deploy_id))

        if result.success:
            deploy_status = str(result.data.get("status", "unknown")).lower()
            monitor_msg = AIMessage(
                content=f"Deploy {deploy_id} status: {deploy_status}",
                additional_kwargs={"action_category": "deploy"},
            )
            evidence = _evidence(
                state,
                "status_check",
                {
                    "status": deploy_status,
                    "data": result.data,
                },
            )
            if deploy_status in _SUCCESS_DEPLOY_STATUSES:
                terminal_status = "completed"
            elif deploy_status in _PENDING_DEPLOY_STATUSES:
                terminal_status = "deploying"
            else:
                terminal_status = "error"
            return {
                **state,
                "messages": [*messages, monitor_msg],
                "deploy_status": deploy_status,
                "status": terminal_status,
                "deployment_evidence": evidence,
            }
        else:
            error_msg = AIMessage(content=f"Status check failed: {result.error}")
            return {
                **state,
                "messages": [*messages, error_msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "status_check",
                    {"status": "failed", "error": result.error},
                ),
            }
    except Exception as exc:
        logger.warning("Deploy status check failed: %s", exc)
        return {
            **state,
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "status_check",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def rollback_evidence(state: DeploymentState) -> DeploymentState:
    """Record rollback pointer evidence after deploy proof is gathered.

    This node is non-destructive. It records pointers even when a previous
    proof phase failed, as long as the deployment was not explicitly denied or
    blocked before mutation.
    """
    messages = state.get("messages", [])
    if state.get("status") in ("denied", "blocked"):
        return state

    environment = state.get("environment", "staging")
    service = state.get("service", "")
    deploy_id = state.get("deploy_id", "") or "not-triggered"
    current_pointer = state.get("current_pointer", {})
    rollback_pointer = state.get("rollback_pointer", {})
    evidence = state.get("deployment_evidence") or {}

    if not current_pointer:
        current_pointer = {
            "service": service,
            "environment": environment,
            "image_tag": state.get("image_tag", ""),
            "gitops_app": state.get("gitops_app", ""),
            "deploy_id": state.get("deploy_id", ""),
            "deploy_status": state.get("deploy_status", ""),
            "argo_sync_status": state.get("argo_sync_status", ""),
            "argo_health_status": state.get("argo_health_status", ""),
        }

    if not rollback_pointer:
        if environment == "production":
            msg = AIMessage(content="Rollback evidence failed: production requires rollback_pointer.")
            return {
                **state,
                "messages": [*messages, msg],
                "status": "error",
                "deployment_evidence": _evidence(
                    state,
                    "rollback_evidence",
                    {"status": "failed", "reason": "rollback_pointer required for production"},
                ),
            }
        msg = AIMessage(
            content="Rollback evidence skipped: rollback_pointer not provided.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, msg],
            "deployment_evidence": _evidence(
                state,
                "rollback_evidence",
                {"status": "skipped", "reason": "rollback_pointer not provided"},
            ),
        }

    try:
        from selva_tools.builtins.rollback_evidence import RollbackEvidenceRecordTool

        smoke_result = evidence.get("smoke") if isinstance(evidence.get("smoke"), dict) else {}
        result = _run_async(
            RollbackEvidenceRecordTool().execute(
                service=service,
                environment=environment,
                deployment_id=deploy_id,
                current_pointer=current_pointer,
                rollback_pointer=rollback_pointer,
                smoke_result=smoke_result,
                evidence=[{"type": key, "value": value} for key, value in evidence.items()],
            )
        )
        if result.success:
            data = result.data or {}
            msg = AIMessage(
                content=f"Rollback evidence recorded: {data.get('storage_path', 'artifact')}.",
                additional_kwargs={"action_category": "deploy"},
            )
            return {
                **state,
                "messages": [*messages, msg],
                "rollback_evidence_artifact": data,
                "deployment_evidence": _evidence(
                    state,
                    "rollback_evidence",
                    {"status": "recorded", "artifact": data},
                ),
            }

        msg = AIMessage(content=f"Rollback evidence failed: {result.error}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "rollback_evidence",
                {"status": "failed", "error": result.error},
            ),
        }
    except Exception as exc:
        logger.exception("Rollback evidence capture failed")
        msg = AIMessage(content=f"Rollback evidence exception: {exc}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "rollback_evidence",
                {"status": "failed", "error": str(exc)},
            ),
        }


@instrumented_node
def evidence_policy(state: DeploymentState) -> DeploymentState:
    """Require complete production deployment evidence before success.

    This is a pure policy gate. It does not mutate infra. It prevents the
    deployment graph from reporting production success unless all required
    proof phases have produced acceptable evidence.
    """
    messages = state.get("messages", [])
    environment = state.get("environment", "staging")
    evidence = state.get("deployment_evidence") or {}

    if environment != "production":
        msg = AIMessage(
            content="Deployment evidence policy skipped: non-production environment.",
            additional_kwargs={"action_category": "deploy"},
        )
        return {
            **state,
            "messages": [*messages, msg],
            "deployment_evidence": _evidence(
                state,
                "evidence_policy",
                {"status": "skipped", "reason": "non-production"},
            ),
        }

    required = {
        "validation": {"passed"},
        "preflight": {"passed"},
        "approval": {"approved"},
        "deploy_trigger": {"triggered"},
        "argo_sync": {"triggered"},
        "argo_health": {"passed"},
        "smoke": {"passed"},
        "rollback_evidence": {"recorded"},
    }
    failures: list[dict[str, object]] = []
    for phase, accepted_statuses in required.items():
        phase_evidence = evidence.get(phase)
        if not isinstance(phase_evidence, dict):
            failures.append({"phase": phase, "reason": "missing"})
            continue
        phase_status = str(phase_evidence.get("status") or "")
        if phase_status not in accepted_statuses:
            failures.append(
                {
                    "phase": phase,
                    "reason": "unaccepted_status",
                    "status": phase_status,
                    "expected": sorted(accepted_statuses),
                }
            )

    status_check = evidence.get("status_check")
    if not isinstance(status_check, dict):
        failures.append({"phase": "status_check", "reason": "missing"})
    else:
        deploy_status = str(status_check.get("status") or "").lower()
        if deploy_status not in _SUCCESS_DEPLOY_STATUSES:
            failures.append(
                {
                    "phase": "status_check",
                    "reason": "unaccepted_status",
                    "status": deploy_status,
                    "expected": sorted(_SUCCESS_DEPLOY_STATUSES),
                }
            )

    if state.get("status") != "completed":
        failures.append(
            {
                "phase": "graph_status",
                "reason": "not_completed",
                "status": state.get("status", ""),
            }
        )

    if failures:
        msg = AIMessage(content=f"Deployment evidence policy failed: {failures}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "error",
            "deployment_evidence": _evidence(
                state,
                "evidence_policy",
                {"status": "failed", "failures": failures},
            ),
        }

    msg = AIMessage(
        content="Deployment evidence policy passed.",
        additional_kwargs={"action_category": "deploy"},
    )
    return {
        **state,
        "messages": [*messages, msg],
        "status": "completed",
        "deployment_evidence": _evidence(
            state,
            "evidence_policy",
            {"status": "passed"},
        ),
    }


# -- Graph construction -------------------------------------------------------


def build_deployment_graph() -> StateGraph:
    """Construct the deployment workflow state graph.

    Flow::

        validate -> preflight -> deploy_gate -> deploy -> argo_sync -> argo_health -> smoke -> monitor -> rollback_evidence -> evidence_policy -> END
    """
    graph = StateGraph(DeploymentState)

    graph.add_node("validate", validate)
    graph.add_node("preflight", preflight)
    graph.add_node("deploy_gate", deploy_gate)
    graph.add_node("deploy", deploy)
    graph.add_node("argo_sync", argo_sync)
    graph.add_node("argo_health", argo_health)
    graph.add_node("smoke", smoke)
    graph.add_node("monitor", monitor)
    graph.add_node("rollback_evidence", rollback_evidence)
    graph.add_node("evidence_policy", evidence_policy)

    graph.set_entry_point("validate")
    graph.add_edge("validate", "preflight")
    graph.add_edge("preflight", "deploy_gate")
    graph.add_edge("deploy_gate", "deploy")
    graph.add_edge("deploy", "argo_sync")
    graph.add_edge("argo_sync", "argo_health")
    graph.add_edge("argo_health", "smoke")
    graph.add_edge("smoke", "monitor")
    graph.add_edge("monitor", "rollback_evidence")
    graph.add_edge("rollback_evidence", "evidence_policy")
    graph.add_edge("evidence_policy", END)

    return graph
