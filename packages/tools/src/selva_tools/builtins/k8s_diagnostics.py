"""Read-side Kubernetes diagnostic tools.

Session 2026-04-18 spent 4+ hours doing cluster triage via raw ``kubectl``
invocations (describe, get events, get pods -l, rollout status). This module
surfaces those same operations as structured tools so agents can drive the
incident-runbook themselves.

Uses the in-cluster service-account credentials mounted at the standard path
(``/var/run/secrets/kubernetes.io/serviceaccount``) via the official
``kubernetes`` python client. RBAC is whatever the pod's SA is granted;
read-only verbs are enough for this module.
"""

from __future__ import annotations

import logging
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _load_clients() -> tuple[Any, Any, Any] | None:
    """Lazy import + load the kubernetes clients. Returns None on error."""
    try:
        from kubernetes import client, config
    except ImportError:
        logger.warning("kubernetes package not installed")
        return None
    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception as e:
            logger.warning("no k8s config available: %s", e)
            return None
    return client.CoreV1Api(), client.AppsV1Api(), client.EventsV1Api()


class K8sGetPodsTool(BaseTool):
    """List pods in a namespace, optionally filtered by label selector."""

    name = "k8s_get_pods"
    description = (
        "List pods in a namespace with ready/status/restarts/age. Optional "
        "'label_selector' (e.g. 'app=madlab-server') filters the result "
        "server-side. Returns a compact summary — use k8s_describe_pod for "
        "deep inspection of a single pod."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "label_selector": {"type": "string"},
            },
            "required": ["namespace"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        clients = _load_clients()
        if clients is None:
            return ToolResult(success=False, error="kubernetes client unavailable")
        core, _apps, _events = clients
        ns = kwargs["namespace"]
        label = kwargs.get("label_selector") or ""
        try:
            resp = core.list_namespaced_pod(namespace=ns, label_selector=label, timeout_seconds=15)
            pods = []
            for p in resp.items:
                container_statuses = p.status.container_statuses or []
                ready = sum(1 for c in container_statuses if c.ready)
                total = len(container_statuses)
                restarts = sum(c.restart_count for c in container_statuses)
                pods.append(
                    {
                        "name": p.metadata.name,
                        "ready": f"{ready}/{total}",
                        "status": p.status.phase,
                        "restarts": restarts,
                        "node": p.spec.node_name,
                        "ip": p.status.pod_ip,
                    }
                )
            return ToolResult(
                success=True,
                output=f"{ns}: {len(pods)} pod(s).",
                data={"pods": pods},
            )
        except Exception as e:
            logger.error("k8s_get_pods failed: %s", e)
            return ToolResult(success=False, error=str(e))


class K8sDescribePodTool(BaseTool):
    """Describe a single pod — containers, volumes, conditions, recent events."""

    name = "k8s_describe_pod"
    description = (
        "Describe one pod: container list with images + state + last "
        "termination reason, volume mounts, pod conditions, and the most "
        "recent events involving this pod. Use for root-causing "
        "CrashLoopBackOff, ImagePullBackOff, CreateContainerConfigError."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["namespace", "name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        clients = _load_clients()
        if clients is None:
            return ToolResult(success=False, error="kubernetes client unavailable")
        core, _apps, _events = clients
        ns = kwargs["namespace"]
        name = kwargs["name"]
        try:
            pod = core.read_namespaced_pod(name=name, namespace=ns)
            containers = []
            for c in pod.status.container_statuses or []:
                state: dict[str, Any] = {"ready": c.ready, "restarts": c.restart_count}
                if c.state.running:
                    state["running_since"] = c.state.running.started_at.isoformat()
                elif c.state.waiting:
                    state["waiting"] = {
                        "reason": c.state.waiting.reason,
                        "message": (c.state.waiting.message or "")[:500],
                    }
                elif c.state.terminated:
                    state["terminated"] = {
                        "reason": c.state.terminated.reason,
                        "exit_code": c.state.terminated.exit_code,
                        "message": (c.state.terminated.message or "")[:500],
                    }
                containers.append({"name": c.name, "image": c.image, "state": state})
            # Events scoped to the pod via field selector.
            ev = core.list_namespaced_event(
                namespace=ns,
                field_selector=f"involvedObject.name={name}",
                limit=20,
            )
            events = [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": (e.message or "")[:300],
                    "last": e.last_timestamp.isoformat() if e.last_timestamp else None,
                }
                for e in sorted(
                    ev.items,
                    key=lambda x: x.last_timestamp or x.event_time,
                    reverse=True,
                )
            ]
            conditions = [
                {"type": c.type, "status": c.status, "reason": c.reason}
                for c in (pod.status.conditions or [])
            ]
            return ToolResult(
                success=True,
                output=(
                    f"{ns}/{name} phase={pod.status.phase} "
                    f"containers={len(containers)} events={len(events)}"
                ),
                data={
                    "phase": pod.status.phase,
                    "containers": containers,
                    "conditions": conditions,
                    "events": events,
                },
            )
        except Exception as e:
            logger.error("k8s_describe_pod failed: %s", e)
            return ToolResult(success=False, error=str(e))


class K8sGetEventsTool(BaseTool):
    """Namespace-scoped event list sorted by most recent first."""

    name = "k8s_get_events"
    description = (
        "List cluster events in a namespace, most recent first. Optional "
        "'warning_only' filter (default False) narrows to Warning-type "
        "events, which is what you want during triage. 'limit' caps the "
        "response (default 50)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "warning_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["namespace"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        clients = _load_clients()
        if clients is None:
            return ToolResult(success=False, error="kubernetes client unavailable")
        core, _apps, _events = clients
        ns = kwargs["namespace"]
        limit = kwargs.get("limit", 50)
        try:
            field_sel = "type=Warning" if kwargs.get("warning_only") else ""
            resp = core.list_namespaced_event(namespace=ns, field_selector=field_sel, limit=limit)
            events = [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "involved": {
                        "kind": e.involved_object.kind,
                        "name": e.involved_object.name,
                    },
                    "message": (e.message or "")[:300],
                    "count": e.count,
                    "last": e.last_timestamp.isoformat() if e.last_timestamp else None,
                }
                for e in sorted(
                    resp.items,
                    key=lambda x: x.last_timestamp or x.event_time,
                    reverse=True,
                )
            ]
            return ToolResult(
                success=True,
                output=f"{ns}: {len(events)} event(s).",
                data={"events": events},
            )
        except Exception as e:
            logger.error("k8s_get_events failed: %s", e)
            return ToolResult(success=False, error=str(e))


class K8sGetReplicasetsTool(BaseTool):
    """List ReplicaSets with desired/current/ready counts."""

    name = "k8s_get_replicasets"
    description = (
        "List ReplicaSets in a namespace. Surfaces DESIRED/CURRENT/READY "
        "counts across ALL ReplicaSets including retired ones (DESIRED=0). "
        "Multiple DESIRED=1 sets in the same namespace = a rollout is stuck, "
        "which is exactly the signal that revealed the workers-selva-* "
        "ImagePullBackOff this session."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "label_selector": {"type": "string"},
            },
            "required": ["namespace"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        clients = _load_clients()
        if clients is None:
            return ToolResult(success=False, error="kubernetes client unavailable")
        _core, apps, _events = clients
        ns = kwargs["namespace"]
        label = kwargs.get("label_selector") or ""
        try:
            resp = apps.list_namespaced_replica_set(namespace=ns, label_selector=label)
            rss = [
                {
                    "name": r.metadata.name,
                    "desired": r.spec.replicas,
                    "current": r.status.replicas or 0,
                    "ready": r.status.ready_replicas or 0,
                    "age_seconds": int(
                        (r.metadata.creation_timestamp.timestamp())
                        if r.metadata.creation_timestamp
                        else 0
                    ),
                    "image": (
                        r.spec.template.spec.containers[0].image
                        if r.spec.template
                        and r.spec.template.spec
                        and r.spec.template.spec.containers
                        else None
                    ),
                }
                for r in resp.items
            ]
            return ToolResult(
                success=True,
                output=f"{ns}: {len(rss)} ReplicaSet(s).",
                data={"replicasets": rss},
            )
        except Exception as e:
            logger.error("k8s_get_replicasets failed: %s", e)
            return ToolResult(success=False, error=str(e))


class K8sRolloutStatusTool(BaseTool):
    """Rollout status for a Deployment / StatefulSet / DaemonSet."""

    name = "k8s_rollout_status"
    description = (
        "Equivalent of 'kubectl rollout status'. For a Deployment, reports "
        "observedGeneration vs generation, updated/available replicas, and "
        "the latest available/progressing conditions. Used to decide if a "
        "sync has actually settled."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["Deployment", "StatefulSet", "DaemonSet"],
                    "default": "Deployment",
                },
                "name": {"type": "string"},
            },
            "required": ["namespace", "name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        clients = _load_clients()
        if clients is None:
            return ToolResult(success=False, error="kubernetes client unavailable")
        _core, apps, _events = clients
        ns = kwargs["namespace"]
        name = kwargs["name"]
        kind = kwargs.get("kind", "Deployment")
        try:
            if kind == "Deployment":
                obj = apps.read_namespaced_deployment(name=name, namespace=ns)
            elif kind == "StatefulSet":
                obj = apps.read_namespaced_stateful_set(name=name, namespace=ns)
            else:  # DaemonSet
                obj = apps.read_namespaced_daemon_set(name=name, namespace=ns)
            s = obj.status
            conditions = [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": (c.message or "")[:300],
                }
                for c in (s.conditions or [])
            ]
            return ToolResult(
                success=True,
                output=(
                    f"{kind} {ns}/{name}: "
                    f"ready={s.ready_replicas or 0}/{getattr(s, 'replicas', 0) or 0}"
                ),
                data={
                    "generation": obj.metadata.generation,
                    "observed_generation": getattr(s, "observed_generation", None),
                    "replicas": getattr(s, "replicas", None),
                    "ready_replicas": getattr(s, "ready_replicas", None),
                    "updated_replicas": getattr(s, "updated_replicas", None),
                    "available_replicas": getattr(s, "available_replicas", None),
                    "conditions": conditions,
                },
            )
        except Exception as e:
            logger.error("k8s_rollout_status failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_k8s_diagnostic_tools() -> list[BaseTool]:
    return [
        K8sGetPodsTool(),
        K8sDescribePodTool(),
        K8sGetEventsTool(),
        K8sGetReplicasetsTool(),
        K8sRolloutStatusTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    K8sGetPodsTool,
    K8sDescribePodTool,
    K8sGetEventsTool,
    K8sGetReplicasetsTool,
    K8sRolloutStatusTool,
):
    _cls.audience = Audience.PLATFORM
