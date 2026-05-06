"""RFC 0005 Sprint 1b — tests for ``secrets.write_kubernetes_secret``.

These tests exercise ``KubernetesSecretWriteTool`` (Sprint 1a) at the
unit level. The K8s SDK and the nexus-api audit module are stubbed so
the tests run with no cluster, no DB, and no network.

Invariants under test (each maps to one or more tests below):

1.  Happy path — dev cluster write returns ``status="applied"``, the
    value never appears in the output/data/logs, and only the 8-char
    ``sha256`` prefix is surfaced.
2.  Idempotency — a second call with the same value short-circuits to
    ``status="already_applied"`` without touching the K8s API.
3.  Misroute guards — prod+``*-staging`` namespace is rejected before
    the API is touched; so is the reverse (staging cluster + prod
    namespace). Neither rejection contains the value.
4.  Allow-list guards — unknown cluster and unknown namespace are both
    rejected at the validation step.
5.  HITL gate per env — dev=ALLOW, staging=ASK, prod=ASK_DUAL.
6.  Missing / bad required args — cleanly surface ``ValidationError``-
    shaped errors without echoing the value.
7.  K8s API failure — when ``patch_namespaced_secret`` raises, the tool
    returns an error with no value, and writes a ``status="failed"``
    audit row.
8.  Audit row contents — happy path writes one row carrying the correct
    sha_prefix, source, rationale, approval_request_id, and status.
9.  Signature verification — fresh row verifies ``True``; mutated row
    verifies ``False``.
10. Source-level lint contract — the tool's own source file never
    references the parameter ``value`` outside the SHA-256 path.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from kubernetes import client as k8s_client  # type: ignore[import-not-found]
from kubernetes import config as k8s_config  # type: ignore[import-not-found]
from kubernetes.client.rest import ApiException  # type: ignore[import-not-found]

from selva_tools.base import ToolResult
from selva_tools.builtins import k8s_secret as k8s_secret_mod
from selva_tools.builtins.k8s_secret import (
    ALLOWED_CLUSTERS,
    ALLOWED_NAMESPACES,
    KubernetesSecretWriteTool,
    _sha256_full,
    sha256_prefix,
)

# A value that must never appear in logs, returned data, or errors.
SECRET_VALUE = "super-secret-stripe-whsec-DO-NOT-LEAK-aaaaaaaa"
SECRET_SHA_PREFIX = sha256_prefix(SECRET_VALUE)
SECRET_SHA_FULL = _sha256_full(SECRET_VALUE)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_v1() -> MagicMock:
    """Mocked CoreV1Api — records patch/create/read calls."""
    v1 = MagicMock(name="CoreV1Api")
    v1.patch_namespaced_secret = MagicMock(return_value=MagicMock())
    v1.create_namespaced_secret = MagicMock(return_value=MagicMock())
    # read_namespaced_secret is used for idempotency; default to 404
    # (secret absent), which forces the tool to rely on the audit log.
    v1.read_namespaced_secret = MagicMock(side_effect=ApiException(status=404, reason="Not Found"))
    return v1


@pytest.fixture
def audit_spy() -> dict[str, Any]:
    """Capture everything the tool would have written to ``secret_audit_log``.

    Returns a dict with ``rows`` (list of captured append_audit_row kwargs)
    and ``already`` (callable substitute for ``was_already_applied``).
    """
    spy: dict[str, Any] = {"rows": [], "already_return": False}

    def fake_already(**kwargs: Any) -> bool:
        return bool(spy["already_return"])

    def fake_append(**kwargs: Any) -> None:
        spy["rows"].append(kwargs)

    spy["already_fn"] = fake_already
    spy["append_fn"] = fake_append
    return spy


@pytest.fixture
def wired_tool(
    monkeypatch: pytest.MonkeyPatch, mock_v1: MagicMock, audit_spy: dict[str, Any]
) -> KubernetesSecretWriteTool:
    """A fully wired tool: no real k8s, no real DB, no real config load."""
    # Stub the k8s config loader (no ~/.kube/config read).
    monkeypatch.setattr(k8s_secret_mod, "_load_k8s_config", lambda: None, raising=True)
    # The tool does a lazy ``from kubernetes import client`` inside
    # ``_apply_secret`` and ``_get_current_sha``, then calls
    # ``client.CoreV1Api()``. Patching the class on the already-imported
    # kubernetes.client module intercepts both call sites.
    monkeypatch.setattr(k8s_client, "CoreV1Api", lambda: mock_v1, raising=True)

    # Patch the audit helpers at their use-site. The tool calls them by
    # name from the module, so replacing the module attribute is enough.
    monkeypatch.setattr(
        k8s_secret_mod,
        "_audit_already_applied",
        lambda **kw: audit_spy["already_fn"](**kw),
        raising=True,
    )
    monkeypatch.setattr(
        k8s_secret_mod,
        "_audit_record",
        lambda **kw: audit_spy["append_fn"](**kw),
        raising=True,
    )
    return KubernetesSecretWriteTool()


def _base_args(**overrides: Any) -> dict[str, Any]:
    """Valid argset pointed at the dev cluster by default."""
    args: dict[str, Any] = {
        "cluster": "madfam-dev",
        "namespace": "autoswarm-office",
        "secret_name": "karafiel-secrets",
        "key": "STRIPE_WEBHOOK_SECRET",
        "value": SECRET_VALUE,
        "source": "stripe_api",
        "rationale": "rotating webhook signing secret per runbook ops-031",
        "agent_id": None,
        "actor_user_sub": "auth0|tester",
    }
    args.update(overrides)
    return args


def _assert_no_value_leak(blob: str) -> None:
    """Guard every surface we can reach against the plaintext value."""
    assert SECRET_VALUE not in blob, "plaintext secret value leaked!"


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_dev_applies_and_never_leaks(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dev cluster write: status=applied, sha prefix surfaced, value scrubbed."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.k8s_secret")

    result = await wired_tool.execute(**_base_args())

    assert isinstance(result, ToolResult)
    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["value_sha256_prefix"] == SECRET_SHA_PREFIX
    assert "approval_request_id" in result.data
    assert result.data["hitl_level"] == "allow"

    # The value must not appear in output, data, error, or any log line.
    _assert_no_value_leak(result.output or "")
    _assert_no_value_leak(str(result.data))
    _assert_no_value_leak(result.error or "")
    for record in caplog.records:
        _assert_no_value_leak(record.getMessage())

    # Exactly one patch attempt was made (idempotency check consulted
    # the audit log, not the K8s API).
    assert mock_v1.patch_namespaced_secret.call_count == 1

    # One audit row appended with status=applied.
    assert len(audit_spy["rows"]) == 1
    row = audit_spy["rows"][0]
    assert row["status"] == "applied"
    assert row["sha_full"] == SECRET_SHA_FULL  # only prefix gets persisted


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_replay_short_circuits(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
) -> None:
    """Second identical call returns already_applied without touching K8s."""
    audit_spy["already_return"] = True

    result = await wired_tool.execute(**_base_args())

    assert result.success is True
    assert result.data["status"] == "already_applied"
    assert result.data["value_sha256_prefix"] == SECRET_SHA_PREFIX
    # Zero K8s API traffic on replay.
    assert mock_v1.patch_namespaced_secret.call_count == 0
    assert mock_v1.create_namespaced_secret.call_count == 0
    # No audit row is appended for a no-op replay.
    assert audit_spy["rows"] == []


# ---------------------------------------------------------------------------
# 3 & 4. Misroute guards (bidirectional)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prod_cluster_with_staging_namespace_rejected(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
) -> None:
    """cluster=madfam-prod + namespace=*-staging is rejected pre-API."""
    result = await wired_tool.execute(
        **_base_args(cluster="madfam-prod", namespace="karafiel-staging")
    )

    assert result.success is False
    assert "misroute" in (result.error or "").lower()
    assert "madfam-prod" in (result.error or "")
    assert "karafiel-staging" in (result.error or "")
    _assert_no_value_leak(result.error or "")
    assert mock_v1.patch_namespaced_secret.call_count == 0
    # No audit row for pre-validation rejections.
    assert audit_spy["rows"] == []


@pytest.mark.asyncio
async def test_staging_cluster_with_prod_namespace_rejected(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
) -> None:
    """cluster=madfam-staging + non-staging namespace rejected.

    ``autoswarm-office`` is the one documented exception (Selva's own
    namespace). We pick ``karafiel`` (prod-shaped) to exercise the guard.
    """
    result = await wired_tool.execute(**_base_args(cluster="madfam-staging", namespace="karafiel"))

    assert result.success is False
    assert "misroute" in (result.error or "").lower()
    _assert_no_value_leak(result.error or "")
    assert mock_v1.patch_namespaced_secret.call_count == 0
    assert audit_spy["rows"] == []


# ---------------------------------------------------------------------------
# 5 & 6. Allow-list guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_cluster_rejected(
    wired_tool: KubernetesSecretWriteTool, mock_v1: MagicMock
) -> None:
    """Any cluster not in ALLOWED_CLUSTERS is rejected."""
    result = await wired_tool.execute(**_base_args(cluster="some-random-cluster"))

    assert result.success is False
    assert "cluster must be one of" in (result.error or "")
    _assert_no_value_leak(result.error or "")
    assert mock_v1.patch_namespaced_secret.call_count == 0


@pytest.mark.asyncio
async def test_unknown_namespace_rejected(
    wired_tool: KubernetesSecretWriteTool, mock_v1: MagicMock
) -> None:
    """Namespaces without an allow-list RoleBinding are rejected.

    Per the tool docstring: "defense in depth so the tool never quietly
    tries to write into a namespace it doesn't have RBAC for."
    """
    assert "kube-system" not in ALLOWED_NAMESPACES

    result = await wired_tool.execute(**_base_args(namespace="kube-system"))

    assert result.success is False
    err = result.error or ""
    assert "allow-list" in err or "allow_list" in err or "not in the allow-list" in err
    _assert_no_value_leak(err)
    assert mock_v1.patch_namespaced_secret.call_count == 0


# ---------------------------------------------------------------------------
# 7. HITL gate per environment (parametrised)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cluster", "namespace", "expected_status", "expected_hitl"),
    [
        ("madfam-dev", "autoswarm-office", "applied", "allow"),
        ("madfam-staging", "karafiel-staging", "pending_approval", "ask"),
        ("madfam-prod", "karafiel", "pending_approval", "ask_dual"),
    ],
)
async def test_hitl_gate_per_env(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
    cluster: str,
    namespace: str,
    expected_status: str,
    expected_hitl: str,
) -> None:
    """dev=ALLOW, staging=ASK, prod=ASK_DUAL per RFC 0005."""
    result = await wired_tool.execute(**_base_args(cluster=cluster, namespace=namespace))

    assert result.success is True, result.error
    assert result.data["status"] == expected_status
    assert result.data["hitl_level"] == expected_hitl
    assert result.data["value_sha256_prefix"] == SECRET_SHA_PREFIX

    if expected_status == "pending_approval":
        # HITL gate MUST NOT have touched the API.
        assert mock_v1.patch_namespaced_secret.call_count == 0
        # But MUST have written a pending_approval audit row.
        assert len(audit_spy["rows"]) == 1
        assert audit_spy["rows"][0]["status"] == "pending_approval"
    else:
        # dev=ALLOW executes now.
        assert mock_v1.patch_namespaced_secret.call_count == 1
        assert audit_spy["rows"][0]["status"] == "applied"


# ---------------------------------------------------------------------------
# 8. Missing required arg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_rationale_surfaces_cleanly(
    wired_tool: KubernetesSecretWriteTool, mock_v1: MagicMock
) -> None:
    """Missing/too-short rationale → ToolResult error, no value leak."""
    args = _base_args(rationale="")  # empty rationale
    result = await wired_tool.execute(**args)

    assert result.success is False
    assert "rationale" in (result.error or "").lower()
    _assert_no_value_leak(result.error or "")
    assert mock_v1.patch_namespaced_secret.call_count == 0


@pytest.mark.asyncio
async def test_missing_value_surfaces_cleanly(
    wired_tool: KubernetesSecretWriteTool, mock_v1: MagicMock
) -> None:
    """Missing ``value`` → ToolResult error (no crash, no leak)."""
    args = _base_args()
    args["value"] = None
    result = await wired_tool.execute(**args)

    assert result.success is False
    assert "value" in (result.error or "").lower()
    assert mock_v1.patch_namespaced_secret.call_count == 0


# ---------------------------------------------------------------------------
# 9. K8s API failure — audit row written, value never leaks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k8s_api_failure_writes_failed_audit_row(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
    mock_v1: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """patch raises → error surfaces, audit row status='failed', no value leak."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.k8s_secret")
    mock_v1.patch_namespaced_secret.side_effect = ApiException(
        status=500, reason="Internal Server Error"
    )

    result = await wired_tool.execute(**_base_args())

    assert result.success is False
    assert result.error is not None
    _assert_no_value_leak(result.error)
    _assert_no_value_leak(result.output or "")
    for record in caplog.records:
        _assert_no_value_leak(record.getMessage())

    # An audit row MUST still be written, with status=failed.
    assert len(audit_spy["rows"]) == 1
    assert audit_spy["rows"][0]["status"] == "failed"
    assert audit_spy["rows"][0]["error_message"]  # non-empty diagnostic
    # ``sha_full`` crosses the boundary but value never does.
    assert audit_spy["rows"][0]["sha_full"] == SECRET_SHA_FULL


# ---------------------------------------------------------------------------
# 10. Audit row contents on happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_row_contents_on_success(
    wired_tool: KubernetesSecretWriteTool,
    audit_spy: dict[str, Any],
) -> None:
    """Happy path writes exactly one row with the right metadata."""
    result = await wired_tool.execute(**_base_args())

    assert result.success is True
    assert len(audit_spy["rows"]) == 1
    row = audit_spy["rows"][0]

    assert row["cluster"] == "madfam-dev"
    assert row["namespace"] == "autoswarm-office"
    assert row["secret_name"] == "karafiel-secrets"
    assert row["key"] == "STRIPE_WEBHOOK_SECRET"
    assert row["source"] == "stripe_api"
    assert row["rationale"].startswith("rotating webhook signing secret")
    assert row["status"] == "applied"
    assert row["approval_request_id"] == result.data["approval_request_id"]
    # Caller hands sha_full across; only prefix persists downstream.
    assert row["sha_full"] == SECRET_SHA_FULL
    # Value ABSOLUTELY must not be in the audit call.
    for v in row.values():
        if isinstance(v, str):
            _assert_no_value_leak(v)


# ---------------------------------------------------------------------------
# 11 & 12. Signature verify — real helpers from nexus_api.audit.secret_audit
# ---------------------------------------------------------------------------


def test_verify_signature_true_on_fresh_row() -> None:
    """A freshly computed signature verifies against a matching row."""
    from datetime import UTC, datetime

    try:
        from nexus_api.audit.secret_audit import compute_signature, verify_signature
        from nexus_api.models import SecretAuditLog
    except Exception:
        pytest.skip("nexus-api audit module not importable in this environment")

    now = datetime.now(UTC).replace(microsecond=0)
    approval_id = "11111111-1111-1111-1111-111111111111"
    sig = compute_signature(
        target_cluster="madfam-dev",
        target_namespace="autoswarm-office",
        target_secret_name="karafiel-secrets",
        target_key="STRIPE_WEBHOOK_SECRET",
        operation="create",
        value_sha256_prefix=SECRET_SHA_PREFIX,
        source="stripe_api",
        rationale="rotating per runbook ops-031",
        approval_request_id=approval_id,
        status="applied",
        created_at=now,
    )

    import uuid

    entry = SecretAuditLog(
        approval_request_id=uuid.UUID(approval_id),
        agent_id=None,
        actor_user_sub=None,
        target_cluster="madfam-dev",
        target_namespace="autoswarm-office",
        target_secret_name="karafiel-secrets",
        target_key="STRIPE_WEBHOOK_SECRET",
        operation="create",
        value_sha256_prefix=SECRET_SHA_PREFIX,
        predecessor_sha256_prefix=None,
        source="stripe_api",
        rationale="rotating per runbook ops-031",
        approval_chain=[],
        status="applied",
        error_message=None,
        rollback_of_id=None,
        signature_sha256=sig,
        created_at=now,
    )
    assert verify_signature(entry) is True


def test_verify_signature_false_on_mutated_row() -> None:
    """Mutating any field after signing causes verify_signature to return False."""
    from datetime import UTC, datetime

    try:
        from nexus_api.audit.secret_audit import compute_signature, verify_signature
        from nexus_api.models import SecretAuditLog
    except Exception:
        pytest.skip("nexus-api audit module not importable in this environment")

    now = datetime.now(UTC).replace(microsecond=0)
    approval_id = "22222222-2222-2222-2222-222222222222"
    original_status = "applied"
    sig = compute_signature(
        target_cluster="madfam-dev",
        target_namespace="autoswarm-office",
        target_secret_name="karafiel-secrets",
        target_key="STRIPE_WEBHOOK_SECRET",
        operation="create",
        value_sha256_prefix=SECRET_SHA_PREFIX,
        source="stripe_api",
        rationale="rotating per runbook ops-031",
        approval_request_id=approval_id,
        status=original_status,
        created_at=now,
    )

    import uuid

    entry = SecretAuditLog(
        approval_request_id=uuid.UUID(approval_id),
        agent_id=None,
        actor_user_sub=None,
        target_cluster="madfam-dev",
        target_namespace="autoswarm-office",
        target_secret_name="karafiel-secrets",
        target_key="STRIPE_WEBHOOK_SECRET",
        operation="create",
        value_sha256_prefix=SECRET_SHA_PREFIX,
        predecessor_sha256_prefix=None,
        source="stripe_api",
        rationale="rotating per runbook ops-031",
        approval_chain=[],
        status=original_status,
        error_message=None,
        rollback_of_id=None,
        signature_sha256=sig,
        created_at=now,
    )
    # Tamper: flip the status field post-sign.
    entry.status = "failed"
    assert verify_signature(entry) is False


# ---------------------------------------------------------------------------
# 13. BONUS: source-level lint — ``value`` never reaches log/format/return
# ---------------------------------------------------------------------------


def _strip_strings_and_comments(source: str) -> str:
    """Remove string literals and comments so we only lint real code.

    The tool's source legitimately contains words like "value is required"
    inside error-message string literals and comments like ``# value``.
    The regex-based lint below should only fire on *code* references to
    the ``value`` identifier, so we blank out strings first.
    """
    # Remove line comments.
    no_comments = re.sub(r"#[^\n]*", "", source)
    # Remove triple-quoted strings (both flavours, non-greedy, DOTALL).
    no_triple = re.sub(r'"""[\s\S]*?"""', '""', no_comments)
    no_triple = re.sub(r"'''[\s\S]*?'''", "''", no_triple)
    # Remove single-line strings (including f-strings).
    no_strings = re.sub(r'(?:rb|br|r|b|f|rf|fr)?"(?:\\.|[^"\\\n])*"', '""', no_triple)
    no_strings = re.sub(r"(?:rb|br|r|b|f|rf|fr)?'(?:\\.|[^'\\\n])*'", "''", no_strings)
    return no_strings


def test_tool_source_never_logs_or_returns_value() -> None:
    """Static grep on the tool's source: the ``value`` identifier must only
    appear in the SHA-256 / size-check paths.

    This is a test-enforced contract around the "never log the secret
    value" invariant. If someone adds ``logger.info("... %s", value)``
    or ``ToolResult(output=value)`` to the tool, this test catches it
    before CI. String literals and comments are stripped first so that
    human-readable error messages containing the word ``value`` don't
    trip the lint.
    """
    src_path = Path(k8s_secret_mod.__file__).resolve()
    source_raw = src_path.read_text(encoding="utf-8")
    source = _strip_strings_and_comments(source_raw)

    forbidden_patterns: list[tuple[str, str]] = [
        # f-string-style interpolation would have been caught before
        # stripping; but direct stringification must never happen.
        (r"\bstr\(\s*value\s*\)", "str(value)"),
        (r"\bvalue\.decode\b", "value.decode"),
        (r"\brepr\(\s*value\s*\)", "repr(value)"),
        # %-formatting with value.
        (r"%\s*value\b", "% value"),
        # .format(... value ...) passing the raw identifier as an arg.
        (r"\.format\([^)]*\bvalue\b[^)]*\)", ".format(... value ...)"),
        # Logger calls that pass the value identifier through.
        (
            r"logger\.(?:debug|info|warning|error|critical)\([^)]*\bvalue\b[^)]*\)",
            "logger.<level>(... value ...)",
        ),
        # Returning value or putting it in a ToolResult field.
        (r"\breturn\s+value\b", "return value"),
        (r"ToolResult\([^)]*\bvalue\b[^)]*\)", "ToolResult(... value ...)"),
    ]

    offenders: list[tuple[str, str]] = []
    for pattern, label in forbidden_patterns:
        for m in re.finditer(pattern, source):
            # Grab the line for diagnostics.
            line_start = source.rfind("\n", 0, m.start()) + 1
            line_end = source.find("\n", m.end())
            if line_end == -1:
                line_end = len(source)
            line = source[line_start:line_end]
            offenders.append((label, line.strip()))

    assert offenders == [], (
        "Forbidden use of `value` identifier in tool source — would leak "
        f"secret. Offenders: {offenders}"
    )

    # Positive check: the allowed sites actually exist in the raw source.
    assert "hashlib.sha256(value.encode" in source_raw
    assert "len(value.encode" in source_raw


# ---------------------------------------------------------------------------
# Sanity: ALLOWED_CLUSTERS/ALLOWED_NAMESPACES expose the right shapes
# ---------------------------------------------------------------------------


def test_allowed_clusters_and_namespaces_are_frozenset() -> None:
    """Guard against accidental mutation of the allow-lists at runtime."""
    assert isinstance(ALLOWED_CLUSTERS, frozenset)
    assert isinstance(ALLOWED_NAMESPACES, frozenset)
    assert "madfam-prod" in ALLOWED_CLUSTERS
    assert "autoswarm-office" in ALLOWED_NAMESPACES


def test_load_k8s_config_prefers_projected_writer_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Workers run as autoswarm-sa but mount a narrower writer token.

    The Kubernetes SDK still needs the pod's in-cluster CA/server config, but
    write calls must authenticate with the projected selva-secret-writer token.
    """
    projected_token = tmp_path / "selva-secret-writer-token"
    default_token = tmp_path / "default-token"
    projected_token.write_text("writer-token\n")
    default_token.write_text("autoswarm-token\n")

    calls: list[str] = []

    class FakeConfiguration:
        def __init__(self) -> None:
            self.api_key: dict[str, str] = {"authorization": "Bearer autoswarm-token"}

        @staticmethod
        def get_default_copy() -> "FakeConfiguration":
            calls.append("get_default_copy")
            return FakeConfiguration()

        @staticmethod
        def set_default(configuration: "FakeConfiguration") -> None:
            calls.append(configuration.api_key["authorization"])

    monkeypatch.setattr(
        k8s_secret_mod,
        "SERVICEACCOUNT_TOKEN_PATH",
        str(projected_token),
        raising=True,
    )
    monkeypatch.setattr(
        k8s_secret_mod,
        "DEFAULT_SERVICEACCOUNT_TOKEN_PATH",
        str(default_token),
        raising=True,
    )
    monkeypatch.setattr(k8s_config, "load_incluster_config", lambda: calls.append("incluster"))
    monkeypatch.setattr(k8s_config, "load_kube_config", lambda: calls.append("kubeconfig"))
    monkeypatch.setattr(k8s_client, "Configuration", FakeConfiguration, raising=True)

    k8s_secret_mod._load_k8s_config()

    assert calls == ["incluster", "get_default_copy", "Bearer writer-token"]
