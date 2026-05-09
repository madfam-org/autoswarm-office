"""Kubernetes ConfigMap tools (RFC 0007 Sprint 1).

Implements the ``config.*`` tool family -- the non-secret cousin of RFC
0005's ``secrets.*``. Enables operator-cadence changes to feature flags
and non-secret configuration without ``kubectl edit configmap`` toil:

- ``ReadConfigMapTool`` (``config.read_configmap``): read-only, ALLOW
  everywhere. Returns the full ``data`` dict for the named ConfigMap.
- ``SetConfigMapValueTool`` (``config.set_configmap_value``): create or
  patch a single key. Creates the ConfigMap if missing when
  ``create_if_missing=True``. HITL: dev=ALLOW, staging=ASK, prod=ASK.
  Feature-flag-shaped keys (``FEATURE_*``, ``ENABLE_*``, ``*_ENABLED``)
  in prod auto-escalate to ASK_DUAL per RFC 0007 §"HITL gates".
- ``DeleteConfigMapKeyTool`` (``config.delete_configmap_key``): remove a
  single key from a ConfigMap. Same HITL schedule as set.
- ``ListConfigMapsTool`` (``config.list_configmaps``): list ConfigMaps
  in a namespace, optionally filtered by label selector. ALLOW
  everywhere; primary use-case is drift audits.

Differences from ``k8s_secret.KubernetesSecretWriteTool`` (RFC 0005
Sprint 1a):

1. **Values ARE readable.** ConfigMaps aren't credentials; workers
   legitimately need to inspect config. The SA has ``get`` + ``list``
   verbs on ConfigMaps (see ``selva-config-writer-role.yaml``).
2. **Plaintext still never crosses the audit boundary.** Only the
   8-char SHA-256 prefix of the stringified value is persisted. A
   ``previous_value_sha256_prefix`` is ALSO recorded so a forensic
   reviewer can reconstruct a key-flip diff without plaintext on
   either side (RFC 0007 §"Audit trail").
3. **Feature-flag keys auto-escalate in prod.** A naming-convention
   match on ``FEATURE_*``, ``ENABLE_*``, ``*_ENABLED`` in the prod
   cluster bumps the HITL gate from ASK to ASK_DUAL, because those
   keys control external charges and customer-visible behaviour. Non-
   matching keys (``MIN_SOAK_MINUTES``, ``PROBE_TOKEN``, etc.) stay at
   single-approver ASK to avoid approval fatigue.
4. **Misroute guard is the same.** ``cluster=madfam-prod`` +
   ``namespace=*-staging`` (and the inverse) is rejected pre-API,
   identical to RFC 0005.

Transport: uses the ``kubernetes`` Python SDK and reads the projected
ServiceAccount token from
``/var/run/secrets/kubernetes.io/serviceaccount/token`` inside the
cluster. For local dev (or tests) it falls back to ``~/.kube/config``.

RFC references:
- ``internal-devops/rfcs/0007-selva-configmap-and-feature-flag-tool.md``
- RBAC: ``infra/k8s/production/selva-config-writer-{sa,role,rolebinding}.yaml``
- Audit: migration 0020, model ``ConfigmapAuditLog``, helpers
  ``nexus_api.audit.configmap_audit``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from enum import StrEnum
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.tools.k8s_configmap")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Same 3 target clusters as RFC 0005.
ALLOWED_CLUSTERS = frozenset({"madfam-dev", "madfam-staging", "madfam-prod"})

# Namespaces in which the ``selva-config-writer`` SA has a RoleBinding.
# Adding a namespace requires a manifest PR under
# ``infra/k8s/production/selva-config-writer-rolebinding.yaml`` AND an
# update to this list. Mirrors ``k8s_secret.ALLOWED_NAMESPACES`` so the
# surface of "namespaces Selva can touch at all" is one set.
ALLOWED_NAMESPACES = frozenset(
    {
        "karafiel",
        "karafiel-staging",
        "dhanam",
        "dhanam-staging",
        "janua",
        "janua-staging",
        "autoswarm-office",
        "phynd-crm",
        "phynd-crm-staging",
    }
)

# Feature-flag-shaped keys that auto-escalate HITL to ASK_DUAL in prod.
# Matches RFC 0007 §"HITL gates" and the naming conventions in the
# problem statement: ``FEATURE_CFDI_AUTO_ISSUE``, ``ENABLE_STRIPE_MXN``,
# ``AUTO_PROMOTE_ENABLED``. We use ``re.fullmatch`` so partial matches
# don't trigger (``MY_FEATURE_LABEL`` stays ASK; ``FEATURE_FOO`` escalates).
FEATURE_FLAG_KEY_PATTERNS = (
    re.compile(r"FEATURE_[A-Z0-9_]+"),
    re.compile(r"ENABLE_[A-Z0-9_]+"),
    re.compile(r"[A-Z0-9_]+_ENABLED"),
)

# Per-RFC-0007 size cap. K8s allows ~1 MiB per ConfigMap; our use-case
# is flags + URLs + tunables. 256 KiB per key with headroom.
MAX_VALUE_BYTES = 256 * 1024

SERVICEACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


class ConfigOperation(StrEnum):
    """Operation types recorded in ``configmap_audit_log.operation``."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    LIST = "list"


# ---------------------------------------------------------------------------
# Helpers (pure -- no K8s, no DB)
# ---------------------------------------------------------------------------


def _sha256_full(value: str) -> str:
    """SHA-256 hex digest of the stringified value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_prefix(value: str) -> str:
    """First 8 hex chars of SHA-256(value). Safe to log and persist.

    Exported so tests and audit tooling can derive the same prefix from
    a known value offline.
    """
    return _sha256_full(value)[:8]


def _resolve_env(cluster: str) -> str:
    """Map a cluster name to its HITL environment bucket."""
    if cluster == "madfam-prod":
        return "prod"
    if cluster == "madfam-staging":
        return "staging"
    return "dev"


def _is_feature_flag_key(key: str) -> bool:
    """Return True if ``key`` matches a known feature-flag naming pattern.

    Matches per RFC 0007 §"HITL gates": ``FEATURE_*``, ``ENABLE_*``,
    or ``*_ENABLED`` (case-sensitive; K8s ConfigMap keys are usually
    SCREAMING_SNAKE_CASE for env-shaped keys).
    """
    return any(p.fullmatch(key) for p in FEATURE_FLAG_KEY_PATTERNS)


def _validate_route(cluster: str, namespace: str) -> str | None:
    """Return an error message if the cluster/namespace combo is misrouted.

    Identical to ``k8s_secret._validate_route`` -- same risk shape:
    prod cluster pointing at a ``*-staging`` namespace (or the reverse)
    is almost always an agent picking up the wrong config file.
    """
    if cluster == "madfam-prod" and namespace.endswith("-staging"):
        return (
            f"misroute guard: namespace '{namespace}' ends with '-staging' "
            f"but cluster is '{cluster}'. Refusing."
        )
    if cluster == "madfam-staging" and not (
        namespace.endswith("-staging") or namespace == "autoswarm-office"
    ):
        return (
            f"misroute guard: namespace '{namespace}' does not end with "
            f"'-staging' but cluster is '{cluster}'. Refusing."
        )
    return None


# ---------------------------------------------------------------------------
# K8s API layer (thin wrapper around the kubernetes SDK)
# ---------------------------------------------------------------------------


class _K8sClientError(Exception):
    """Surfaced when the K8s API returns an unrecoverable error."""


class _K8sAuthError(Exception):
    """Raised when the SA token mount is missing or the API returns 403.

    Separate from ``_K8sClientError`` so callers can surface a specific
    "RBAC / auth" failure without swallowing it into a generic bucket.
    """


def _load_k8s_config() -> None:
    """Load the appropriate K8s config for the current environment.

    In-cluster: projected SA token at the standard path. Local dev:
    kubeconfig from ``KUBECONFIG`` or ``~/.kube/config``. Raises
    ``_K8sAuthError`` when neither is available -- the RFC 0007 tool
    refuses to fall back to anonymous access.
    """
    from kubernetes import config as k8s_config

    if os.path.exists(SERVICEACCOUNT_TOKEN_PATH):
        k8s_config.load_incluster_config()
        return

    # Local dev / test fallback. We explicitly check for a kubeconfig
    # file rather than letting ``load_kube_config`` try to use whatever
    # cluster the user is logged into: the tool must fail loudly when
    # no SA token is mounted, rather than silently hitting the dev
    # cluster's API server with ambient kubectl credentials in prod.
    kubeconfig_env = os.environ.get("KUBECONFIG", "")
    default_kubeconfig = os.path.expanduser("~/.kube/config")
    if kubeconfig_env or os.path.exists(default_kubeconfig):
        k8s_config.load_kube_config()
        return

    raise _K8sAuthError(
        f"no ServiceAccount token at {SERVICEACCOUNT_TOKEN_PATH} and "
        "no kubeconfig available; refusing to issue anonymous requests"
    )


def _read_configmap(namespace: str, name: str) -> dict[str, str] | None:
    """Return the ``data`` dict for the named ConfigMap, or None if missing.

    Raises ``_K8sAuthError`` on 403 so callers can distinguish missing-
    ConfigMap (None) from RBAC failure.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    try:
        cm = v1.read_namespaced_config_map(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        if exc.status == 403:
            raise _K8sAuthError(
                f"read_namespaced_config_map forbidden: status={exc.status}"
            ) from exc
        raise _K8sClientError(f"read_namespaced_config_map failed: status={exc.status}") from exc

    data = getattr(cm, "data", None) or {}
    # ``data`` values are always strings in K8s ConfigMaps (binaryData
    # is a separate field we intentionally ignore for v0.1).
    return dict(data)


def _list_configmaps(namespace: str, label_selector: str | None) -> list[dict[str, Any]]:
    """Return a compact list of ConfigMaps in the namespace."""
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    try:
        result = v1.list_namespaced_config_map(
            namespace=namespace,
            label_selector=label_selector or "",
        )
    except ApiException as exc:
        if exc.status == 403:
            raise _K8sAuthError(
                f"list_namespaced_config_map forbidden: status={exc.status}"
            ) from exc
        raise _K8sClientError(f"list_namespaced_config_map failed: status={exc.status}") from exc

    items = getattr(result, "items", None) or []
    compact: list[dict[str, Any]] = []
    for item in items:
        meta = getattr(item, "metadata", None)
        if meta is None:
            continue
        data = getattr(item, "data", None) or {}
        compact.append(
            {
                "name": getattr(meta, "name", ""),
                "namespace": getattr(meta, "namespace", ""),
                "labels": dict(getattr(meta, "labels", None) or {}),
                "key_count": len(data),
                "resource_version": getattr(meta, "resource_version", None),
            }
        )
    return compact


def _apply_configmap_key(
    namespace: str,
    name: str,
    key: str,
    value: str,
    *,
    create_if_missing: bool,
) -> str:
    """Create-or-patch a single key in the named ConfigMap.

    Returns ``"create"`` if the ConfigMap didn't exist and was created,
    ``"update"`` if it existed and was patched.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    body = client.V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        metadata=client.V1ObjectMeta(name=name, namespace=namespace),
        data={key: value},
    )

    try:
        v1.patch_namespaced_config_map(name=name, namespace=namespace, body=body)
        return "update"
    except ApiException as exc:
        if exc.status == 404:
            if not create_if_missing:
                raise _K8sClientError(
                    f"ConfigMap {namespace}/{name} does not exist and create_if_missing=False"
                ) from exc
            try:
                v1.create_namespaced_config_map(namespace=namespace, body=body)
                return "create"
            except ApiException as create_exc:
                raise _K8sClientError(
                    f"create_namespaced_config_map failed: status={create_exc.status}"
                ) from create_exc
        if exc.status == 403:
            raise _K8sAuthError(
                f"patch_namespaced_config_map forbidden: status={exc.status}"
            ) from exc
        raise _K8sClientError(f"patch_namespaced_config_map failed: status={exc.status}") from exc


def _delete_configmap_key(namespace: str, name: str, key: str) -> bool:
    """Remove a single key from a ConfigMap. Returns True if the key existed.

    Uses a strategic-merge-patch with ``$patch: delete`` semantics on
    the key. If the ConfigMap itself is missing, returns False.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    # JSON-merge-patch: setting a data key to null removes it.
    patch_body = {"data": {key: None}}

    try:
        v1.patch_namespaced_config_map(
            name=name,
            namespace=namespace,
            body=patch_body,
        )
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        if exc.status == 403:
            raise _K8sAuthError(
                f"patch_namespaced_config_map (delete) forbidden: status={exc.status}"
            ) from exc
        raise _K8sClientError(
            f"patch_namespaced_config_map (delete) failed: status={exc.status}"
        ) from exc


# ---------------------------------------------------------------------------
# Audit log layer -- thin facade around the nexus-api DB
# ---------------------------------------------------------------------------


def _audit_record(
    *,
    approval_request_id: str,
    agent_id: str | None,
    actor_user_sub: str | None,
    request_id: str | None,
    cluster: str,
    namespace: str,
    configmap_name: str,
    key: str | None,
    operation: str,
    value_sha_full: str | None,
    previous_value_sha_full: str | None,
    rationale: str,
    hitl_level: str,
    status: str,
    error_message: str | None,
) -> None:
    """Append a row to ``configmap_audit_log``. Lazy import so tests can stub.

    NOTE: plaintext values NEVER reach this function. Callers pass the
    full SHA-256 hex digest (``*_sha_full``); only ``[:8]`` is persisted.
    """
    try:
        from nexus_api.audit.configmap_audit import (
            append_audit_row,
        )
    except Exception:  # pragma: no cover -- missing dep is dev-only
        logger.debug("nexus_api audit module unavailable; skipping DB write")
        return
    try:
        append_audit_row(
            approval_request_id=approval_request_id,
            agent_id=agent_id,
            actor_user_sub=actor_user_sub,
            request_id=request_id,
            target_cluster=cluster,
            target_namespace=namespace,
            target_configmap_name=configmap_name,
            target_key=key,
            operation=operation,
            value_sha256_prefix=(value_sha_full[:8] if value_sha_full else None),
            previous_value_sha256_prefix=(
                previous_value_sha_full[:8] if previous_value_sha_full else None
            ),
            rationale=rationale,
            hitl_level=hitl_level,
            status=status,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001 — audit failures must not leak
        logger.error("configmap audit append failed", exc_info=True)


# ---------------------------------------------------------------------------
# HITL evaluation
# ---------------------------------------------------------------------------


def _resolve_hitl_level(env: str, *, feature_flag: bool) -> str:
    """Return the HITL level for (env, feature-flag-status).

    Policy (RFC 0007 §"HITL gates"):
      - dev     -> ALLOW (every op)
      - staging -> ASK
      - prod    -> ASK for non-flag keys; ASK_DUAL for feature-flag keys
    """
    try:
        from selva_permissions.engine import PermissionEngine
        from selva_permissions.types import (
            ActionCategory,
            PermissionLevel,
        )
    except Exception:  # pragma: no cover
        # Permissions package unavailable => fail closed to ASK.
        return "ask"

    if env == "dev":
        override = PermissionLevel.ALLOW
    elif env == "staging":
        override = PermissionLevel.ASK
    elif env == "prod" and feature_flag:
        override = PermissionLevel.ASK_DUAL
    else:
        override = PermissionLevel.ASK

    engine = PermissionEngine(overrides={ActionCategory.K8S_CONFIGMAP_WRITE: override})
    result = engine.evaluate(ActionCategory.K8S_CONFIGMAP_WRITE)
    return result.level.value


# ---------------------------------------------------------------------------
# Shared argument validation
# ---------------------------------------------------------------------------


def _validate_common_args(
    *,
    cluster: str,
    namespace: str,
    configmap_name: str,
) -> str | None:
    """Return an error message if any common arg is invalid, else None."""
    if cluster not in ALLOWED_CLUSTERS:
        return f"cluster must be one of {sorted(ALLOWED_CLUSTERS)}; got {cluster!r}"
    if namespace not in ALLOWED_NAMESPACES:
        return (
            f"namespace {namespace!r} is not in the allow-list. "
            "Add a RoleBinding manifest under "
            "infra/k8s/production/ and update ALLOWED_NAMESPACES."
        )
    if not configmap_name:
        return "configmap_name is required"
    route_err = _validate_route(cluster, namespace)
    if route_err:
        return route_err
    return None


# ---------------------------------------------------------------------------
# Tool 1: read_configmap
# ---------------------------------------------------------------------------


class ReadConfigMapTool(BaseTool):
    """``config.read_configmap`` -- read-only ConfigMap inspection.

    Returns the full ``data`` dict. ALLOW everywhere (read access to
    ConfigMaps is not privileged); emits a ``status="applied"`` audit
    row with ``operation="read"`` so drift audits can see who looked
    when.
    """

    name = "config_read_configmap"
    description = (
        "Read a Kubernetes ConfigMap's full data dict. Read-only; no "
        "HITL gate, but emits an audit row for drift/forensic review. "
        "Use for inspecting feature flags, routing tables, tool "
        "allow-lists before proposing a change."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                    "description": "Target cluster.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Target namespace (must be allow-listed).",
                },
                "configmap_name": {
                    "type": "string",
                    "description": "Name of the ConfigMap (e.g. 'karafiel-config').",
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "Human-readable reason for the read. Required so "
                        "audit log entries are self-describing."
                    ),
                },
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["cluster", "namespace", "configmap_name", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        cluster = str(kwargs.get("cluster") or "")
        namespace = str(kwargs.get("namespace") or "")
        configmap_name = str(kwargs.get("configmap_name") or "")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        err = _validate_common_args(
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
        )
        if err:
            return ToolResult(success=False, error=err)
        if not rationale or len(rationale) < 10:
            return ToolResult(
                success=False,
                error="rationale is required (>= 10 chars, human-readable why)",
            )

        approval_request_id = str(uuid.uuid4())
        hitl_level = "allow"  # reads are ALLOW in every env (RFC 0007)

        try:
            _load_k8s_config()
            data = _read_configmap(namespace, configmap_name)
        except _K8sAuthError as exc:
            msg = str(exc)
            logger.error(
                "configmap read auth failure cluster=%s ns=%s name=%s err=%s",
                cluster,
                namespace,
                configmap_name,
                msg,
            )
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=None,
                operation=ConfigOperation.READ.value,
                value_sha_full=None,
                previous_value_sha_full=None,
                rationale=rationale,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"rbac/auth error: {msg}")
        except _K8sClientError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=None,
                operation=ConfigOperation.READ.value,
                value_sha_full=None,
                previous_value_sha_full=None,
                rationale=rationale,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"k8s api error: {msg}")

        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            request_id=str(request_id) if request_id else None,
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
            key=None,
            operation=ConfigOperation.READ.value,
            value_sha_full=None,
            previous_value_sha_full=None,
            rationale=rationale,
            hitl_level=hitl_level,
            status="applied",
            error_message=None,
        )

        if data is None:
            return ToolResult(
                output=(f"ConfigMap {namespace}/{configmap_name} does not exist."),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "not_found",
                    "hitl_level": hitl_level,
                    "data": None,
                    "key_count": 0,
                },
            )

        return ToolResult(
            output=(f"Read {len(data)} keys from {namespace}/{configmap_name}."),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "data": data,
                "key_count": len(data),
            },
        )


# ---------------------------------------------------------------------------
# Tool 2: set_configmap_value
# ---------------------------------------------------------------------------


class SetConfigMapValueTool(BaseTool):
    """``config.set_configmap_value`` -- create or patch one ConfigMap key.

    HITL per RFC 0007:
      - dev     -> ALLOW
      - staging -> ASK
      - prod    -> ASK (single approver)
      - prod + feature-flag-shaped key -> ASK_DUAL (two approvers)

    Feature-flag shape: ``FEATURE_*``, ``ENABLE_*``, ``*_ENABLED``.
    Any other key in prod stays at ASK to avoid approval fatigue.

    On successful write, emits an audit row recording BOTH the new
    ``value_sha256_prefix`` AND the ``previous_value_sha256_prefix`` so
    forensics can reconstruct a diff without plaintext on either side.
    """

    name = "config_set_configmap_value"
    description = (
        "Set a single key in a Kubernetes ConfigMap. HITL-gated per env "
        "(dev=ALLOW, staging=ASK, prod=ASK; feature-flag-shaped keys "
        "FEATURE_*/ENABLE_*/*_ENABLED in prod escalate to ASK_DUAL). "
        "Records both the new and predecessor SHA-256 prefixes in the "
        "audit log for diff reconstruction."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                },
                "namespace": {"type": "string"},
                "configmap_name": {"type": "string"},
                "key": {
                    "type": "string",
                    "description": (
                        "ConfigMap data key (e.g. 'FEATURE_CFDI_AUTO_ISSUE'). "
                        "Must be non-empty and <= 253 chars per K8s naming."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "New value. ConfigMaps carry plaintext config; do "
                        "NOT put secrets here (use secrets.* tool instead). "
                        f"Max {MAX_VALUE_BYTES} bytes."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Human-readable reason for the change. Required "
                        "and >= 10 chars so audit rows are self-describing."
                    ),
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": (
                        "If True and the ConfigMap doesn't exist, create "
                        "it with just this key. Default False: the tool "
                        "refuses to silently conjure new ConfigMaps, "
                        "which would bypass GitOps declaration."
                    ),
                    "default": False,
                },
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": [
                "cluster",
                "namespace",
                "configmap_name",
                "key",
                "value",
                "reason",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        cluster = str(kwargs.get("cluster") or "")
        namespace = str(kwargs.get("namespace") or "")
        configmap_name = str(kwargs.get("configmap_name") or "")
        key = str(kwargs.get("key") or "")
        new_value = kwargs.get("value")
        reason = str(kwargs.get("reason") or "")
        create_if_missing = bool(kwargs.get("create_if_missing", False))
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        err = _validate_common_args(
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
        )
        if err:
            return ToolResult(success=False, error=err)
        if not key:
            return ToolResult(success=False, error="key is required")
        if new_value is None or not isinstance(new_value, str):
            return ToolResult(success=False, error="value is required (string)")
        if len(new_value.encode("utf-8")) > MAX_VALUE_BYTES:
            return ToolResult(success=False, error="value exceeds per-key size limit")
        if not reason or len(reason) < 10:
            return ToolResult(
                success=False,
                error="reason is required (>= 10 chars, human-readable why)",
            )

        env = _resolve_env(cluster)
        is_flag = _is_feature_flag_key(key)
        hitl_level = _resolve_hitl_level(env, feature_flag=is_flag)

        new_sha_full = _sha256_full(new_value)
        new_sha_pref = new_sha_full[:8]

        approval_request_id = str(uuid.uuid4())

        logger.info(
            "configmap write requested cluster=%s ns=%s name=%s key=%s "
            "is_flag=%s hitl=%s approval_id=%s new_sha_prefix=%s",
            cluster,
            namespace,
            configmap_name,
            key,
            is_flag,
            hitl_level,
            approval_request_id,
            new_sha_pref,
        )

        # HITL gate: staging/prod return pending_approval without touching
        # the API. Only dev (ALLOW) executes inline.
        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.WRITE.value,
                value_sha_full=new_sha_full,
                previous_value_sha_full=None,  # unknown until approver executes
                rationale=reason,
                hitl_level=hitl_level,
                status="pending_approval",
                error_message=None,
            )
            return ToolResult(
                output=(
                    f"ConfigMap write for {namespace}/{configmap_name}:{key} "
                    f"pending {hitl_level} approval (new_sha_prefix={new_sha_pref})."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "new_value_sha256_prefix": new_sha_pref,
                    "hitl_level": hitl_level,
                    "is_feature_flag_key": is_flag,
                },
            )

        # dev=ALLOW: execute now.
        previous_sha_full: str | None = None
        try:
            _load_k8s_config()
            # Fetch the current value BEFORE patching so we can record the
            # predecessor hash for forensic diff reconstruction.
            try:
                current = _read_configmap(namespace, configmap_name)
                if current is not None and key in current:
                    previous_sha_full = _sha256_full(current[key])
            except (_K8sAuthError, _K8sClientError):
                # Read failure isn't fatal -- we can still write. Predecessor
                # prefix just ends up NULL in the audit row.
                previous_sha_full = None

            operation = _apply_configmap_key(
                namespace,
                configmap_name,
                key,
                new_value,
                create_if_missing=create_if_missing,
            )
        except _K8sAuthError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.WRITE.value,
                value_sha_full=new_sha_full,
                previous_value_sha_full=previous_sha_full,
                rationale=reason,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"rbac/auth error: {msg}")
        except _K8sClientError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.WRITE.value,
                value_sha_full=new_sha_full,
                previous_value_sha_full=previous_sha_full,
                rationale=reason,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"k8s api error: {msg}")

        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            request_id=str(request_id) if request_id else None,
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
            key=key,
            operation=ConfigOperation.WRITE.value,
            value_sha_full=new_sha_full,
            previous_value_sha_full=previous_sha_full,
            rationale=reason,
            hitl_level=hitl_level,
            status="applied",
            error_message=None,
        )

        return ToolResult(
            output=(
                f"ConfigMap {namespace}/{configmap_name}:{key} {operation}d "
                f"(new_sha_prefix={new_sha_pref})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "new_value_sha256_prefix": new_sha_pref,
                "previous_value_sha256_prefix": (
                    previous_sha_full[:8] if previous_sha_full else None
                ),
                "hitl_level": hitl_level,
                "operation": operation,
                "is_feature_flag_key": is_flag,
            },
        )


# ---------------------------------------------------------------------------
# Tool 3: delete_configmap_key
# ---------------------------------------------------------------------------


class DeleteConfigMapKeyTool(BaseTool):
    """``config.delete_configmap_key`` -- remove a single key from a ConfigMap.

    Same HITL schedule as ``set_configmap_value``: flag-shaped keys in
    prod escalate to ASK_DUAL. Records the predecessor SHA-256 prefix so
    the deletion is reversible (caller can re-issue a set with the same
    hash to confirm a restore).
    """

    name = "config_delete_configmap_key"
    description = (
        "Delete a single key from a Kubernetes ConfigMap. HITL-gated per "
        "env (same schedule as set_configmap_value). Does NOT delete the "
        "whole ConfigMap (that would cascade into missing-config bugs); "
        "deleting the ConfigMap object itself requires operator UI."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                },
                "namespace": {"type": "string"},
                "configmap_name": {"type": "string"},
                "key": {"type": "string"},
                "reason": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": [
                "cluster",
                "namespace",
                "configmap_name",
                "key",
                "reason",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        cluster = str(kwargs.get("cluster") or "")
        namespace = str(kwargs.get("namespace") or "")
        configmap_name = str(kwargs.get("configmap_name") or "")
        key = str(kwargs.get("key") or "")
        reason = str(kwargs.get("reason") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        err = _validate_common_args(
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
        )
        if err:
            return ToolResult(success=False, error=err)
        if not key:
            return ToolResult(success=False, error="key is required")
        if not reason or len(reason) < 10:
            return ToolResult(
                success=False,
                error="reason is required (>= 10 chars, human-readable why)",
            )

        env = _resolve_env(cluster)
        is_flag = _is_feature_flag_key(key)
        hitl_level = _resolve_hitl_level(env, feature_flag=is_flag)
        approval_request_id = str(uuid.uuid4())

        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.DELETE.value,
                value_sha_full=None,
                previous_value_sha_full=None,
                rationale=reason,
                hitl_level=hitl_level,
                status="pending_approval",
                error_message=None,
            )
            return ToolResult(
                output=(
                    f"ConfigMap delete for {namespace}/{configmap_name}:{key} "
                    f"pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "is_feature_flag_key": is_flag,
                },
            )

        # dev=ALLOW: execute now, capture predecessor hash.
        previous_sha_full: str | None = None
        try:
            _load_k8s_config()
            try:
                current = _read_configmap(namespace, configmap_name)
                if current is not None and key in current:
                    previous_sha_full = _sha256_full(current[key])
            except (_K8sAuthError, _K8sClientError):
                previous_sha_full = None
            existed = _delete_configmap_key(namespace, configmap_name, key)
        except _K8sAuthError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.DELETE.value,
                value_sha_full=None,
                previous_value_sha_full=previous_sha_full,
                rationale=reason,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"rbac/auth error: {msg}")
        except _K8sClientError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name=configmap_name,
                key=key,
                operation=ConfigOperation.DELETE.value,
                value_sha_full=None,
                previous_value_sha_full=previous_sha_full,
                rationale=reason,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"k8s api error: {msg}")

        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            request_id=str(request_id) if request_id else None,
            cluster=cluster,
            namespace=namespace,
            configmap_name=configmap_name,
            key=key,
            operation=ConfigOperation.DELETE.value,
            value_sha_full=None,
            previous_value_sha_full=previous_sha_full,
            rationale=reason,
            hitl_level=hitl_level,
            status="applied",
            error_message=None,
        )

        return ToolResult(
            output=(
                f"ConfigMap key {namespace}/{configmap_name}:{key} "
                f"{'deleted' if existed else 'was already absent'}."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "existed": existed,
                "previous_value_sha256_prefix": (
                    previous_sha_full[:8] if previous_sha_full else None
                ),
                "hitl_level": hitl_level,
                "is_feature_flag_key": is_flag,
            },
        )


# ---------------------------------------------------------------------------
# Tool 4: list_configmaps
# ---------------------------------------------------------------------------


class ListConfigMapsTool(BaseTool):
    """``config.list_configmaps`` -- discover ConfigMaps in a namespace.

    Read-only; ALLOW everywhere. Primary use is drift-audit flows
    comparing live ConfigMap inventory against the GitOps-declared set.
    Optional ``label_selector`` filters the server-side result.
    """

    name = "config_list_configmaps"
    description = (
        "List ConfigMaps in a namespace (optionally filtered by label "
        "selector). Returns a compact summary: name, labels, key_count, "
        "resource_version. Read-only; emits an audit row for forensics."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                },
                "namespace": {"type": "string"},
                "label_selector": {
                    "type": "string",
                    "description": (
                        "Optional K8s label selector (e.g. 'app.kubernetes.io/part-of=karafiel')."
                    ),
                },
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["cluster", "namespace", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        cluster = str(kwargs.get("cluster") or "")
        namespace = str(kwargs.get("namespace") or "")
        label_selector = kwargs.get("label_selector")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        # list doesn't have a configmap_name; reuse _validate_common_args
        # by passing a placeholder and then clearing configmap_name.
        if cluster not in ALLOWED_CLUSTERS:
            return ToolResult(
                success=False,
                error=(f"cluster must be one of {sorted(ALLOWED_CLUSTERS)}; got {cluster!r}"),
            )
        if namespace not in ALLOWED_NAMESPACES:
            return ToolResult(
                success=False,
                error=(f"namespace {namespace!r} is not in the allow-list."),
            )
        route_err = _validate_route(cluster, namespace)
        if route_err:
            return ToolResult(success=False, error=route_err)
        if not rationale or len(rationale) < 10:
            return ToolResult(
                success=False,
                error="rationale is required (>= 10 chars, human-readable why)",
            )
        if label_selector is not None and not isinstance(label_selector, str):
            return ToolResult(success=False, error="label_selector must be a string")

        approval_request_id = str(uuid.uuid4())
        hitl_level = "allow"

        try:
            _load_k8s_config()
            items = _list_configmaps(
                namespace, label_selector if isinstance(label_selector, str) else None
            )
        except _K8sAuthError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name="*",
                key=None,
                operation=ConfigOperation.LIST.value,
                value_sha_full=None,
                previous_value_sha_full=None,
                rationale=rationale,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"rbac/auth error: {msg}")
        except _K8sClientError as exc:
            msg = str(exc)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                request_id=str(request_id) if request_id else None,
                cluster=cluster,
                namespace=namespace,
                configmap_name="*",
                key=None,
                operation=ConfigOperation.LIST.value,
                value_sha_full=None,
                previous_value_sha_full=None,
                rationale=rationale,
                hitl_level=hitl_level,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"k8s api error: {msg}")

        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            request_id=str(request_id) if request_id else None,
            cluster=cluster,
            namespace=namespace,
            configmap_name="*",
            key=None,
            operation=ConfigOperation.LIST.value,
            value_sha_full=None,
            previous_value_sha_full=None,
            rationale=rationale,
            hitl_level=hitl_level,
            status="applied",
            error_message=None,
        )

        return ToolResult(
            output=(
                f"Listed {len(items)} ConfigMap(s) in {namespace}"
                + (f" matching '{label_selector}'" if label_selector else "")
                + "."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "items": items,
                "count": len(items),
            },
        )


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    ReadConfigMapTool,
    SetConfigMapValueTool,
    DeleteConfigMapKeyTool,
    ListConfigMapsTool,
):
    _cls.audience = Audience.PLATFORM
