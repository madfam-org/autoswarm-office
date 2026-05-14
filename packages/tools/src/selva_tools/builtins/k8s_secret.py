"""Kubernetes Secret writer tool (RFC 0005 Sprint 1a).

Implements ``secrets.write_kubernetes_secret`` — the Selva-side half of
the secret-management capability described in
``internal-devops/rfcs/0005-selva-secret-management.md``. The tool:

- Creates or patches a single key inside a K8s ``Secret`` object.
- Never logs, returns, or echoes the secret value. Only a SHA-256 prefix
  is ever surfaced (for rotation correlation).
- Is idempotent on ``(cluster, namespace, secret_name, key, sha256)`` —
  replays of the same value short-circuit to ``already_applied`` without
  touching the API.
- Writes an append-only row to ``secret_audit_log`` recording
  provenance, rationale, hash prefix, and approval chain.
- Gates on the HITL action category ``K8S_SECRET_WRITE``:
  dev = ALLOW, staging = ASK, prod = ASK_DUAL (per RFC 0005).
- Rejects the prod-cluster-into-staging-namespace misroute (and the
  reverse) as a compile-time-shaped check before the API is touched.

What this tool deliberately does NOT do (deferred to later sprints):

- **Read** secrets. There is no ``read_kubernetes_secret`` counterpart;
  workers consume values via ``envFrom`` on their own pod spec. That
  eliminates the biggest exfiltration vector.
- **Delete** secret keys. Separate tool, separate HITL path (Sprint 2).
- **Rotate** secrets. ``secrets.rotate_kubernetes_secret`` with
  ``rotation_plan`` lands in Sprint 2.
- **Write to Vault**. Vault backend migration is Sprint 3.

Transport: uses the ``kubernetes`` Python SDK and prefers the projected
``selva-secret-writer`` ServiceAccount token mounted at
``/var/run/secrets/selva/secret-writer/token`` inside worker pods. It
loads the in-cluster CA/server config from the pod default token mount,
then swaps the bearer token to the dedicated writer token. For local dev
(or tests) it falls back to ``~/.kube/config``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import uuid
from enum import StrEnum
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.tools.k8s_secret")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Allowed target clusters. RFC 0005 §"Kubeconfig mounting strategy"
# lists exactly three cluster names; anything else is rejected before
# the tool reaches the K8s API.
ALLOWED_CLUSTERS = frozenset({"madfam-dev", "madfam-staging", "madfam-prod"})

# Namespaces that the ``selva-secret-writer`` SA has a RoleBinding in.
# Adding a new namespace requires a manifest PR under
# ``infra/k8s/production/selva-secret-writer-rolebinding.yaml`` AND
# an update to this list — defense in depth so the tool never quietly
# tries to write into a namespace it doesn't have RBAC for.
ALLOWED_NAMESPACES = frozenset(
    {
        "karafiel",
        "karafiel-staging",
        "dhanam",
        "dhanam-staging",
        "janua",
        "janua-staging",
        "autoswarm",
        "autoswarm-office",
        "forgesight",
        "forgesight-staging",
        "phynd-crm",
        "phynd-crm-staging",
    }
)

# Per-RFC-0005 size limit. K8s allows 1 MiB per Secret object, but the
# use-case here is API credentials, not blobs. 64 KiB per key with room
# to grow.
MAX_VALUE_BYTES = 64 * 1024

DEFAULT_SERVICEACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SERVICEACCOUNT_TOKEN_PATH = "/var/run/secrets/selva/secret-writer/token"


class SecretSource(StrEnum):
    """Provenance of the value being written."""

    STRIPE_API = "stripe_api"
    JANUA_API = "janua_api"
    PAC_VENDOR_API = "pac_vendor_api"
    MANUAL_INPUT = "manual_input"
    VAULT_SYNC = "vault_sync"
    ROTATION = "rotation"
    IMPORT = "import"


# ---------------------------------------------------------------------------
# Helpers (pure — no K8s, no DB)
# ---------------------------------------------------------------------------


def _sha256_full(value: str) -> str:
    """SHA-256 hex digest of the value. Never returned to callers."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_prefix(value: str) -> str:
    """First 8 hex chars of SHA-256(value). Safe to log and return.

    Exported so tests and audit utilities can derive the same prefix
    from a raw value offline.
    """
    return _sha256_full(value)[:8]


def _resolve_env(cluster: str) -> str:
    """Map a cluster name to its HITL environment bucket."""
    if cluster == "madfam-prod":
        return "prod"
    if cluster == "madfam-staging":
        return "staging"
    return "dev"


def _validate_route(cluster: str, namespace: str) -> str | None:
    """Return an error message if the cluster/namespace combo is misrouted.

    The original motivating case: an agent calls
    ``cluster="madfam-prod", namespace="karafiel-staging"`` because it
    picked up the namespace from a staging config file. That write must
    never reach prod.
    """
    if cluster == "madfam-prod" and namespace.endswith("-staging"):
        return (
            f"misroute guard: namespace '{namespace}' ends with '-staging' "
            f"but cluster is '{cluster}'. Refusing."
        )
    if cluster == "madfam-staging" and not (
        namespace.endswith("-staging") or namespace == "autoswarm"
    ):
        # autoswarm is Selva's own namespace; it's the same name
        # in both clusters and is the one documented exception.
        return (
            f"misroute guard: namespace '{namespace}' does not end with "
            f"'-staging' but cluster is '{cluster}'. Refusing."
        )
    return None


# ---------------------------------------------------------------------------
# K8s API layer (thin wrapper around the kubernetes SDK)
# ---------------------------------------------------------------------------


class _K8sClientError(Exception):
    """Surfaced when the K8s API returns an unrecoverable error.

    The message MUST NOT contain the secret value. Callers strip any
    server-side error payload before raising.
    """


def _load_k8s_config() -> None:
    """Load the appropriate K8s config for the current environment.

    In-cluster: load the pod CA/server config, then prefer the projected
    ``selva-secret-writer`` token over the pod's default ServiceAccount token.
    Local dev: kubeconfig from ``KUBECONFIG`` env var or ``~/.kube/config``.
    """
    from kubernetes import client
    from kubernetes import config as k8s_config

    if os.path.exists(SERVICEACCOUNT_TOKEN_PATH):
        k8s_config.load_incluster_config()
        with open(SERVICEACCOUNT_TOKEN_PATH, encoding="utf-8") as token_file:
            writer_token = token_file.read().strip()
        configuration = client.Configuration.get_default_copy()
        configuration.api_key["authorization"] = f"Bearer {writer_token}"
        client.Configuration.set_default(configuration)
    elif os.path.exists(DEFAULT_SERVICEACCOUNT_TOKEN_PATH):
        k8s_config.load_incluster_config()
    else:
        # load_kube_config respects KUBECONFIG env var itself.
        k8s_config.load_kube_config()


def _get_current_sha(namespace: str, secret_name: str, key: str) -> str | None:
    """Return the SHA-256 of the current value at (secret_name, key), or None.

    Used purely for idempotency. The SA does NOT have ``get`` on secrets
    in the production RBAC (RFC 0005 §"Kubeconfig mounting strategy" —
    workers can't exfil values via API). So this call is expected to
    return ``None`` (permission denied) in prod; idempotency in that
    case relies on the audit log instead — see ``_audit_already_applied``.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    try:
        secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404 or exc.status == 403:
            return None
        raise _K8sClientError(f"read_namespaced_secret failed: status={exc.status}") from exc

    data = getattr(secret, "data", None) or {}
    encoded = data.get(key)
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:  # noqa: BLE001 — any decode error is "unknown current"
        return None
    return _sha256_full(decoded)


def _apply_secret(namespace: str, secret_name: str, key: str, value: str) -> str:
    """Create-or-patch a single key in the named Secret. Returns operation type.

    Returns ``"create"`` if the Secret didn't exist and was created,
    ``"update"`` if it existed and was patched.
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    v1 = client.CoreV1Api()
    encoded_value = base64.b64encode(value.encode("utf-8")).decode("ascii")

    body = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
        type="Opaque",
        data={key: encoded_value},
    )

    # Try patch first (update path); fall through to create on 404.
    try:
        v1.patch_namespaced_secret(name=secret_name, namespace=namespace, body=body)
        return "update"
    except ApiException as exc:
        if exc.status == 404:
            try:
                v1.create_namespaced_secret(namespace=namespace, body=body)
                return "create"
            except ApiException as create_exc:
                raise _K8sClientError(
                    f"create_namespaced_secret failed: status={create_exc.status}"
                ) from create_exc
        raise _K8sClientError(f"patch_namespaced_secret failed: status={exc.status}") from exc


# ---------------------------------------------------------------------------
# Audit log layer — thin facade around the nexus-api DB
# ---------------------------------------------------------------------------


def _audit_already_applied(
    *,
    cluster: str,
    namespace: str,
    secret_name: str,
    key: str,
    sha_full: str,
) -> bool:
    """Return True if the audit log already contains a successful write for this exact value.

    Consulted before touching K8s so replays become no-ops. Import is
    lazy so test code can stub out the whole function without needing
    the nexus-api package on the path.
    """
    try:
        from nexus_api.audit.secret_audit import (
            was_already_applied,
        )
    except Exception:  # pragma: no cover — missing dep is dev-only
        return False
    try:
        return bool(
            was_already_applied(
                cluster=cluster,
                namespace=namespace,
                secret_name=secret_name,
                key=key,
                sha_full=sha_full,
            )
        )
    except Exception:  # noqa: BLE001 — audit lookup never blocks writes
        logger.warning("audit idempotency lookup failed", exc_info=True)
        return False


def _audit_record(
    *,
    approval_request_id: str,
    agent_id: str | None,
    actor_user_sub: str | None,
    cluster: str,
    namespace: str,
    secret_name: str,
    key: str,
    operation: str,
    sha_full: str,
    source: str,
    rationale: str,
    status: str,
    error_message: str | None,
) -> None:
    """Append a row to ``secret_audit_log``. Import lazy for the same reason.

    NOTE: this function NEVER receives or logs the value itself. Only
    ``sha_full`` (the hex digest) crosses the function boundary, and
    only ``sha_full[:8]`` is persisted.
    """
    try:
        from nexus_api.audit.secret_audit import append_audit_row
    except Exception:  # pragma: no cover — missing dep is dev-only
        logger.debug("nexus_api audit module unavailable; skipping DB write")
        return
    try:
        append_audit_row(
            approval_request_id=approval_request_id,
            agent_id=agent_id,
            actor_user_sub=actor_user_sub,
            target_cluster=cluster,
            target_namespace=namespace,
            target_secret_name=secret_name,
            target_key=key,
            operation=operation,
            value_sha256_prefix=sha_full[:8],
            source=source,
            rationale=rationale,
            status=status,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001 — audit failures MUST NOT leak values
        logger.error("audit append failed (no value content in log)", exc_info=True)


# ---------------------------------------------------------------------------
# HITL evaluation
# ---------------------------------------------------------------------------


def _resolve_hitl_level(env: str) -> str:
    """Return the HITL level string for the environment bucket.

    Returns one of ``"allow"``, ``"ask"``, ``"ask_dual"``.
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

    env_overrides = {
        "dev": PermissionLevel.ALLOW,
        "staging": PermissionLevel.ASK,
        "prod": PermissionLevel.ASK_DUAL,
    }
    engine = PermissionEngine(overrides={ActionCategory.K8S_SECRET_WRITE: env_overrides[env]})
    result = engine.evaluate(ActionCategory.K8S_SECRET_WRITE)
    return result.level.value


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class KubernetesSecretWriteTool(BaseTool):
    """``secrets.write_kubernetes_secret`` — RFC 0005 Sprint 1a.

    Parameters (see RFC 0005 §"Tool surface"):

    - ``cluster``: one of ``madfam-dev``, ``madfam-staging``, ``madfam-prod``
    - ``namespace``: target namespace (must be in ``ALLOWED_NAMESPACES``)
    - ``secret_name``: K8s ``Secret`` object name
    - ``key``: key inside the Secret's ``.data``
    - ``value``: the secret material (NEVER logged, NEVER returned)
    - ``source``: provenance tag from ``SecretSource``
    - ``rationale``: human-readable reason for the write
    - ``rotation_plan`` (optional): deferred to Sprint 2

    Returns a ``ToolResult`` whose ``data`` contains:

    - ``approval_request_id``: str (UUID), correlates with the approval queue
    - ``status``: ``"pending_approval"`` | ``"already_applied"`` | ``"applied"``
    - ``value_sha256_prefix``: first 8 hex chars of SHA-256(value)
    - ``hitl_level``: the HITL gate level enforced for this call

    NEVER returns the value itself.
    """

    name = "write_kubernetes_secret"
    description = (
        "Create or patch a single key inside a Kubernetes Secret in an "
        "allowed namespace. Gated by the K8S_SECRET_WRITE action category "
        "(dev=ALLOW / staging=ASK / prod=ASK_DUAL). Idempotent on "
        "(cluster, namespace, secret_name, key, value_sha256). The value "
        "itself is never logged or returned."
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
                "secret_name": {
                    "type": "string",
                    "description": "Name of the Secret object (e.g. 'karafiel-secrets').",
                },
                "key": {
                    "type": "string",
                    "description": "Key inside the Secret data (e.g. 'STRIPE_WEBHOOK_SECRET').",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The secret material. NEVER logged, NEVER returned. "
                        f"Maximum {MAX_VALUE_BYTES} bytes."
                    ),
                },
                "source": {
                    "type": "string",
                    "enum": [s.value for s in SecretSource],
                    "description": "Provenance of the value.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Human-readable reason for the write.",
                },
                "rotation_plan": {
                    "type": "object",
                    "description": "Optional — deferred to Sprint 2.",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Proposing Selva agent UUID (from worker context).",
                },
                "actor_user_sub": {
                    "type": "string",
                    "description": "User JWT sub if triggered via /office.",
                },
            },
            "required": [
                "cluster",
                "namespace",
                "secret_name",
                "key",
                "value",
                "source",
                "rationale",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        # -- 1. Argument validation (no value-leaking branches) -------------
        cluster = str(kwargs.get("cluster") or "")
        namespace = str(kwargs.get("namespace") or "")
        secret_name = str(kwargs.get("secret_name") or "")
        key = str(kwargs.get("key") or "")
        value = kwargs.get("value")
        source_raw = str(kwargs.get("source") or "")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")

        if cluster not in ALLOWED_CLUSTERS:
            return ToolResult(
                success=False,
                error=(f"cluster must be one of {sorted(ALLOWED_CLUSTERS)}; got {cluster!r}"),
            )
        if namespace not in ALLOWED_NAMESPACES:
            return ToolResult(
                success=False,
                error=(
                    f"namespace {namespace!r} is not in the allow-list. "
                    "Add a RoleBinding manifest under "
                    "infra/k8s/production/ and update ALLOWED_NAMESPACES."
                ),
            )
        if not secret_name or not key:
            return ToolResult(
                success=False,
                error="secret_name and key are required",
            )
        if value is None or not isinstance(value, str) or value == "":
            return ToolResult(success=False, error="value is required")
        if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
            # Note: we intentionally do NOT echo the length either — the
            # ratio between declared max and actual length is enough
            # information to identify the key in some cases.
            return ToolResult(success=False, error="value exceeds per-key size limit")
        if source_raw not in {s.value for s in SecretSource}:
            return ToolResult(
                success=False,
                error=f"source must be one of {[s.value for s in SecretSource]}",
            )
        if not rationale or len(rationale) < 10:
            return ToolResult(
                success=False,
                error="rationale is required (>= 10 chars, human-readable why)",
            )

        route_err = _validate_route(cluster, namespace)
        if route_err:
            logger.warning("k8s secret write rejected: %s", route_err)
            return ToolResult(success=False, error=route_err)

        # -- 2. Derive hash (never log, only prefix-log) --------------------
        sha_full = _sha256_full(value)
        sha_pref = sha_full[:8]
        env = _resolve_env(cluster)
        hitl_level = _resolve_hitl_level(env)

        approval_request_id = str(uuid.uuid4())

        logger.info(
            "k8s secret write requested cluster=%s ns=%s name=%s key=%s "
            "sha_prefix=%s source=%s hitl=%s approval_id=%s",
            cluster,
            namespace,
            secret_name,
            key,
            sha_pref,
            source_raw,
            hitl_level,
            approval_request_id,
        )

        # -- 3. Idempotency check -----------------------------------------
        if _audit_already_applied(
            cluster=cluster,
            namespace=namespace,
            secret_name=secret_name,
            key=key,
            sha_full=sha_full,
        ):
            logger.info(
                "k8s secret write short-circuited (already_applied) "
                "cluster=%s ns=%s name=%s key=%s sha_prefix=%s",
                cluster,
                namespace,
                secret_name,
                key,
                sha_pref,
            )
            return ToolResult(
                output=(
                    f"Secret {namespace}/{secret_name}:{key} already at "
                    f"sha_prefix={sha_pref}; no write needed."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "already_applied",
                    "value_sha256_prefix": sha_pref,
                    "hitl_level": hitl_level,
                },
            )

        # -- 4. HITL gate --------------------------------------------------
        # dev=ALLOW executes immediately; staging/prod return
        # pending_approval with an audit row status "pending_approval".
        # The UI (Sprint 1b) and approval consumer drive the rest.
        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                cluster=cluster,
                namespace=namespace,
                secret_name=secret_name,
                key=key,
                operation="create",  # final op type known after approval+apply
                sha_full=sha_full,
                source=source_raw,
                rationale=rationale,
                status="pending_approval",
                error_message=None,
            )
            return ToolResult(
                output=(
                    f"Secret write for {namespace}/{secret_name}:{key} is "
                    f"pending {hitl_level} approval (sha_prefix={sha_pref})."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "value_sha256_prefix": sha_pref,
                    "hitl_level": hitl_level,
                },
            )

        # -- 5. dev=ALLOW: execute the write now --------------------------
        try:
            _load_k8s_config()
            operation = _apply_secret(namespace, secret_name, key, value)
        except _K8sClientError as exc:
            msg = str(exc)
            logger.error(
                "k8s secret write failed cluster=%s ns=%s name=%s key=%s sha_prefix=%s err=%s",
                cluster,
                namespace,
                secret_name,
                key,
                sha_pref,
                msg,
            )
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                cluster=cluster,
                namespace=namespace,
                secret_name=secret_name,
                key=key,
                operation="create",
                sha_full=sha_full,
                source=source_raw,
                rationale=rationale,
                status="failed",
                error_message=msg,
            )
            return ToolResult(success=False, error=f"k8s api error: {msg}")
        except Exception as exc:  # noqa: BLE001 — catch-all to avoid leaks
            # Any unknown exception is scrubbed before surfacing; callers
            # still get a useful status but never the value.
            err_class = type(exc).__name__
            logger.error(
                "k8s secret write unexpected failure cluster=%s ns=%s key=%s "
                "sha_prefix=%s err_class=%s",
                cluster,
                namespace,
                key,
                sha_pref,
                err_class,
            )
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                cluster=cluster,
                namespace=namespace,
                secret_name=secret_name,
                key=key,
                operation="create",
                sha_full=sha_full,
                source=source_raw,
                rationale=rationale,
                status="failed",
                error_message=err_class,
            )
            return ToolResult(
                success=False,
                error=f"k8s client failure ({err_class}); see audit row",
            )

        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            cluster=cluster,
            namespace=namespace,
            secret_name=secret_name,
            key=key,
            operation=operation,
            sha_full=sha_full,
            source=source_raw,
            rationale=rationale,
            status="applied",
            error_message=None,
        )

        return ToolResult(
            output=(
                f"Secret {namespace}/{secret_name}:{key} {operation}d (sha_prefix={sha_pref})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "value_sha256_prefix": sha_pref,
                "hitl_level": hitl_level,
                "operation": operation,
            },
        )


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (KubernetesSecretWriteTool,):
    _cls.audience = Audience.PLATFORM
