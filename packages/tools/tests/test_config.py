"""RFC 0007 Sprint 1 — tests for the ``config.*`` ConfigMap tool family.

Exercises ``ReadConfigMapTool``, ``SetConfigMapValueTool``,
``DeleteConfigMapKeyTool``, and ``ListConfigMapsTool`` at the unit
level. The K8s SDK and the nexus-api audit module are stubbed so the
tests run with no cluster, no DB, and no network.

Invariants under test:

1.  Read path -- happy path returns full data dict, emits an audit row
    with ``operation="read"`` and ``status="applied"``.
2.  Write path (dev) -- new value applied, audit row records the new
    SHA-256 prefix AND the predecessor prefix, plaintext never leaks.
3.  Write path (prod, non-flag key) -- gates at ASK (single approver),
    does NOT touch the K8s API.
4.  Write path (prod, feature-flag key) -- gates at ASK_DUAL
    (two approvers), still does not touch the API.
5.  Delete path -- removes a key, records predecessor hash.
6.  List path with label selector -- passes selector through, returns
    compact summary.
7.  HITL denial path -- staging/prod set_configmap_value returns
    pending_approval with no API call.
8.  Audit row emits SHA-256 prefix (8 chars), not raw value.
9.  Missing SA-token + missing kubeconfig -> ``_K8sAuthError``.
10. K8s API 403 on read -> ``_K8sAuthError`` surfaced, failed audit row.
11. Feature-flag key classification is strict (``FEATURE_*``, ``ENABLE_*``,
    ``*_ENABLED`` match; ``MY_FEATURE`` does NOT).
12. Misroute guard rejects prod+staging and staging+prod combos.
13. Allow-list guard rejects unknown namespaces.
14. Rationale/reason validation (min 10 chars).
15. Sanity: tool names + allow-lists expose the right shapes.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from kubernetes import client as k8s_client  # type: ignore[import-not-found]
from kubernetes.client.rest import ApiException  # type: ignore[import-not-found]

from selva_tools.base import ToolResult
from selva_tools.builtins import k8s_configmap as cfg_mod
from selva_tools.builtins.k8s_configmap import (
    ALLOWED_CLUSTERS,
    ALLOWED_NAMESPACES,
    DeleteConfigMapKeyTool,
    ListConfigMapsTool,
    ReadConfigMapTool,
    SetConfigMapValueTool,
    _is_feature_flag_key,
    _K8sAuthError,
    _sha256_full,
    sha256_prefix,
)

# A value that must never appear as plaintext in any audit-bound log.
CONFIG_VALUE = "https://sat.gob.mx/portal-cfdi-4-2-webhook"
CONFIG_SHA_PREFIX = sha256_prefix(CONFIG_VALUE)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cm(name: str, namespace: str, data: dict[str, str]) -> MagicMock:
    """Shape a V1ConfigMap-like mock the way the tool consumes it."""
    cm = MagicMock(name=f"V1ConfigMap-{name}")
    cm.metadata = MagicMock()
    cm.metadata.name = name
    cm.metadata.namespace = namespace
    cm.metadata.labels = {"app.kubernetes.io/part-of": "karafiel"}
    cm.metadata.resource_version = "12345"
    cm.data = dict(data)
    return cm


@pytest.fixture
def mock_v1() -> MagicMock:
    """Mocked CoreV1Api wired for all four operations."""
    v1 = MagicMock(name="CoreV1Api")
    # Default: ConfigMap karafiel-config has one flag already set.
    current_cm = _make_cm(
        "karafiel-config",
        "karafiel",
        {"FEATURE_CFDI_AUTO_ISSUE": "false", "EMAIL_FROM": "ops@madfam.io"},
    )
    v1.read_namespaced_config_map = MagicMock(return_value=current_cm)
    v1.patch_namespaced_config_map = MagicMock(return_value=MagicMock())
    v1.create_namespaced_config_map = MagicMock(return_value=MagicMock())
    list_result = MagicMock()
    list_result.items = [current_cm]
    v1.list_namespaced_config_map = MagicMock(return_value=list_result)
    return v1


@pytest.fixture
def audit_spy() -> dict[str, Any]:
    """Capture everything the tool would have written to ``configmap_audit_log``."""
    spy: dict[str, Any] = {"rows": []}

    def fake_record(**kwargs: Any) -> None:
        spy["rows"].append(kwargs)

    spy["record_fn"] = fake_record
    return spy


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch, mock_v1: MagicMock, audit_spy: dict[str, Any]
) -> dict[str, Any]:
    """Fully wired test environment: no real k8s, no real DB, no config load."""
    # Stub the k8s config loader (no ~/.kube/config read).
    monkeypatch.setattr(cfg_mod, "_load_k8s_config", lambda: None, raising=True)
    # Patch CoreV1Api on the already-imported kubernetes.client module.
    monkeypatch.setattr(k8s_client, "CoreV1Api", lambda: mock_v1, raising=True)
    # Patch audit at its use-site.
    monkeypatch.setattr(
        cfg_mod,
        "_audit_record",
        lambda **kw: audit_spy["record_fn"](**kw),
        raising=True,
    )
    return {
        "read": ReadConfigMapTool(),
        "set": SetConfigMapValueTool(),
        "delete": DeleteConfigMapKeyTool(),
        "list": ListConfigMapsTool(),
        "v1": mock_v1,
        "audit": audit_spy,
    }


def _base_read_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "cluster": "madfam-dev",
        "namespace": "selva-office",
        "configmap_name": "karafiel-config",
        "rationale": "pre-flight read before flag flip per runbook ops-045",
        "agent_id": None,
        "actor_user_sub": "auth0|tester",
    }
    args.update(overrides)
    return args


def _base_set_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "cluster": "madfam-dev",
        "namespace": "selva-office",
        "configmap_name": "karafiel-config",
        "key": "EMAIL_FROM",  # non-flag key by default
        "value": CONFIG_VALUE,
        "reason": "rotating the ops email alias per runbook ops-045",
        "agent_id": None,
        "actor_user_sub": "auth0|tester",
    }
    args.update(overrides)
    return args


def _assert_no_value_leak(blob: str) -> None:
    assert CONFIG_VALUE not in blob, "plaintext config value leaked!"


# ---------------------------------------------------------------------------
# 1. Read path -- happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_configmap_returns_data_and_audit(
    wired: dict[str, Any],
) -> None:
    """Read returns full data dict + applied audit row."""
    result = await wired["read"].execute(**_base_read_args())

    assert isinstance(result, ToolResult)
    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["hitl_level"] == "allow"
    assert "FEATURE_CFDI_AUTO_ISSUE" in result.data["data"]
    assert result.data["key_count"] == 2

    # Audit row emitted with read operation.
    assert len(wired["audit"]["rows"]) == 1
    row = wired["audit"]["rows"][0]
    assert row["operation"] == "read"
    assert row["status"] == "applied"
    assert row["hitl_level"] == "allow"
    assert row["key"] is None  # read is configmap-scoped, not key-scoped


@pytest.mark.asyncio
async def test_read_configmap_missing_returns_not_found(
    wired: dict[str, Any],
) -> None:
    """Missing ConfigMap returns status=not_found without erroring."""
    wired["v1"].read_namespaced_config_map.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    result = await wired["read"].execute(**_base_read_args())
    assert result.success is True
    assert result.data["status"] == "not_found"
    assert result.data["data"] is None


# ---------------------------------------------------------------------------
# 2. Write path (dev) -- happy path, predecessor hash recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_value_dev_applies_and_records_both_hashes(
    wired: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dev cluster set: status=applied, new AND predecessor hash recorded."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.k8s_configmap")

    result = await wired["set"].execute(**_base_set_args())

    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["new_value_sha256_prefix"] == CONFIG_SHA_PREFIX
    # Predecessor was "ops@madfam.io" per fixture.
    expected_prev = sha256_prefix("ops@madfam.io")
    assert result.data["previous_value_sha256_prefix"] == expected_prev
    assert result.data["hitl_level"] == "allow"
    assert result.data["is_feature_flag_key"] is False

    # Raw value never in output/data/error/logs.
    _assert_no_value_leak(result.output or "")
    _assert_no_value_leak(str(result.data))
    for record in caplog.records:
        _assert_no_value_leak(record.getMessage())

    # Exactly one patch attempt.
    assert wired["v1"].patch_namespaced_config_map.call_count == 1

    # Audit row.
    assert len(wired["audit"]["rows"]) == 1
    row = wired["audit"]["rows"][0]
    assert row["operation"] == "write"
    assert row["status"] == "applied"
    assert row["value_sha_full"] == _sha256_full(CONFIG_VALUE)
    assert row["previous_value_sha_full"] == _sha256_full("ops@madfam.io")


# ---------------------------------------------------------------------------
# 3. Write path (prod, non-flag key) -- single ASK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_value_prod_non_flag_gates_single_ask(
    wired: dict[str, Any],
) -> None:
    """Prod + non-flag key returns pending_approval at ASK level."""
    args = _base_set_args(
        cluster="madfam-prod",
        namespace="karafiel",
        key="EMAIL_FROM",  # non-flag
    )
    result = await wired["set"].execute(**args)

    assert result.success is True
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask"
    assert result.data["is_feature_flag_key"] is False

    # API MUST NOT have been touched.
    assert wired["v1"].patch_namespaced_config_map.call_count == 0

    # Audit row written with pending_approval status.
    assert len(wired["audit"]["rows"]) == 1
    assert wired["audit"]["rows"][0]["status"] == "pending_approval"
    assert wired["audit"]["rows"][0]["hitl_level"] == "ask"


# ---------------------------------------------------------------------------
# 4. Write path (prod, feature-flag key) -- ASK_DUAL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag_key",
    [
        "FEATURE_CFDI_AUTO_ISSUE",
        "ENABLE_STRIPE_MXN_LIVE",
        "AUTO_PROMOTE_ENABLED",
    ],
)
async def test_set_value_prod_feature_flag_escalates_to_ask_dual(
    wired: dict[str, Any], flag_key: str
) -> None:
    """Prod + feature-flag-shaped key returns pending_approval at ASK_DUAL."""
    args = _base_set_args(
        cluster="madfam-prod",
        namespace="karafiel",
        key=flag_key,
        value="true",
    )
    result = await wired["set"].execute(**args)

    assert result.success is True
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask_dual"
    assert result.data["is_feature_flag_key"] is True
    assert wired["v1"].patch_namespaced_config_map.call_count == 0


# ---------------------------------------------------------------------------
# 5. Delete path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_key_dev_applies_and_records_predecessor(
    wired: dict[str, Any],
) -> None:
    """Dev delete: removes key, records predecessor hash, no new-value hash."""
    args = {
        "cluster": "madfam-dev",
        "namespace": "selva-office",
        "configmap_name": "karafiel-config",
        "key": "FEATURE_CFDI_AUTO_ISSUE",
        "reason": "deprecating this flag; CFDI auto-issue is now default on",
        "actor_user_sub": "auth0|tester",
    }
    result = await wired["delete"].execute(**args)

    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["existed"] is True
    # Predecessor was "false" per fixture.
    assert result.data["previous_value_sha256_prefix"] == sha256_prefix("false")

    assert len(wired["audit"]["rows"]) == 1
    row = wired["audit"]["rows"][0]
    assert row["operation"] == "delete"
    assert row["value_sha_full"] is None
    assert row["previous_value_sha_full"] == _sha256_full("false")


# ---------------------------------------------------------------------------
# 6. List path with label selector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_configmaps_passes_label_selector_through(
    wired: dict[str, Any],
) -> None:
    """list_configmaps hands label_selector to K8s and returns compact summary."""
    result = await wired["list"].execute(
        cluster="madfam-dev",
        namespace="selva-office",
        label_selector="app.kubernetes.io/part-of=karafiel",
        rationale="drift audit: are our declared ConfigMaps still on-cluster?",
        actor_user_sub="auth0|tester",
    )

    assert result.success is True, result.error
    assert result.data["count"] == 1
    assert result.data["items"][0]["name"] == "karafiel-config"
    assert result.data["items"][0]["key_count"] == 2
    assert "app.kubernetes.io/part-of" in result.data["items"][0]["labels"]

    # label_selector was forwarded to the K8s SDK.
    wired["v1"].list_namespaced_config_map.assert_called_once()
    _, kwargs = wired["v1"].list_namespaced_config_map.call_args
    assert kwargs["label_selector"] == "app.kubernetes.io/part-of=karafiel"

    # Audit row with operation=list.
    assert wired["audit"]["rows"][0]["operation"] == "list"


# ---------------------------------------------------------------------------
# 7. HITL denial -- staging returns pending_approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cluster", "namespace", "expected_hitl"),
    [
        ("madfam-dev", "selva-office", "allow"),
        ("madfam-staging", "karafiel-staging", "ask"),
        ("madfam-prod", "karafiel", "ask"),
    ],
)
async def test_hitl_gate_by_env_non_flag_key(
    wired: dict[str, Any],
    cluster: str,
    namespace: str,
    expected_hitl: str,
) -> None:
    """dev=ALLOW, staging=ASK, prod=ASK for non-flag keys."""
    result = await wired["set"].execute(
        **_base_set_args(
            cluster=cluster,
            namespace=namespace,
            key="EMAIL_FROM",
        )
    )
    assert result.success is True, result.error
    assert result.data["hitl_level"] == expected_hitl
    if expected_hitl == "allow":
        assert result.data["status"] == "applied"
        assert wired["v1"].patch_namespaced_config_map.call_count == 1
    else:
        assert result.data["status"] == "pending_approval"
        assert wired["v1"].patch_namespaced_config_map.call_count == 0


# ---------------------------------------------------------------------------
# 8. Audit row emits SHA-256 prefix not raw value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_row_carries_hash_not_raw_value(
    wired: dict[str, Any],
) -> None:
    """On applied writes, the audit row's sha_full matches SHA-256(value)."""
    await wired["set"].execute(**_base_set_args())

    row = wired["audit"]["rows"][0]
    # Expected: the audit layer receives the full digest; only :8 persists.
    assert row["value_sha_full"] == _sha256_full(CONFIG_VALUE)
    # The raw value must NOT appear anywhere in the audit kwargs.
    for v in row.values():
        if isinstance(v, str):
            _assert_no_value_leak(v)


# ---------------------------------------------------------------------------
# 9. Missing SA token + kubeconfig -> _K8sAuthError
# ---------------------------------------------------------------------------


def test_load_k8s_config_raises_auth_error_when_nothing_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SA token + no kubeconfig => _K8sAuthError (not a kubectl fallthrough)."""
    # Pretend nothing is available.
    monkeypatch.setattr("os.path.exists", lambda p: False, raising=True)
    monkeypatch.setenv("KUBECONFIG", "")
    # Expand user returns a path that also doesn't exist (above).
    with pytest.raises(_K8sAuthError):
        cfg_mod._load_k8s_config()


# ---------------------------------------------------------------------------
# 10. K8s API 403 on read -> _K8sAuthError surfaced, failed audit row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_403_surfaces_auth_error_and_writes_failed_audit(
    wired: dict[str, Any],
) -> None:
    """403 from the K8s API maps to rbac/auth error and a failed audit row."""
    wired["v1"].read_namespaced_config_map.side_effect = ApiException(
        status=403, reason="Forbidden"
    )
    result = await wired["read"].execute(**_base_read_args())

    assert result.success is False
    assert "rbac" in (result.error or "").lower() or "auth" in (result.error or "").lower()
    assert len(wired["audit"]["rows"]) == 1
    assert wired["audit"]["rows"][0]["status"] == "failed"
    assert wired["audit"]["rows"][0]["error_message"]


# ---------------------------------------------------------------------------
# 11. Feature-flag classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "is_flag"),
    [
        # Positive
        ("FEATURE_CFDI_AUTO_ISSUE", True),
        ("FEATURE_FOO", True),
        ("ENABLE_STRIPE_MXN_LIVE", True),
        ("AUTO_PROMOTE_ENABLED", True),
        ("DARK_MODE_ENABLED", True),
        # Negative: partial matches must not trigger ASK_DUAL
        ("MY_FEATURE_LABEL", False),  # contains FEATURE_ but not at start
        ("feature_lowercase", False),  # regex is uppercase-only
        ("EMAIL_FROM", False),
        ("DATABASE_URL", False),
        ("MIN_SOAK_MINUTES", False),
        ("ENABLER_STATE", False),  # contains ENABLE but not ENABLE_
    ],
)
def test_feature_flag_classifier_strict_match(key: str, is_flag: bool) -> None:
    assert _is_feature_flag_key(key) is is_flag


# ---------------------------------------------------------------------------
# 12. Misroute guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prod_cluster_with_staging_namespace_rejected(
    wired: dict[str, Any],
) -> None:
    """cluster=madfam-prod + namespace=*-staging is rejected pre-API."""
    result = await wired["set"].execute(
        **_base_set_args(
            cluster="madfam-prod",
            namespace="karafiel-staging",
        )
    )
    assert result.success is False
    assert "misroute" in (result.error or "").lower()
    assert wired["v1"].patch_namespaced_config_map.call_count == 0
    assert wired["audit"]["rows"] == []


@pytest.mark.asyncio
async def test_staging_cluster_with_prod_namespace_rejected(
    wired: dict[str, Any],
) -> None:
    """cluster=madfam-staging + non-staging namespace rejected."""
    result = await wired["set"].execute(
        **_base_set_args(
            cluster="madfam-staging",
            namespace="karafiel",  # prod-shaped
        )
    )
    assert result.success is False
    assert "misroute" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 13. Allow-list guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_namespace_rejected(wired: dict[str, Any]) -> None:
    assert "kube-system" not in ALLOWED_NAMESPACES
    result = await wired["set"].execute(**_base_set_args(namespace="kube-system"))
    assert result.success is False
    assert "allow-list" in (result.error or "") or "allow_list" in (result.error or "")


@pytest.mark.asyncio
async def test_unknown_cluster_rejected(wired: dict[str, Any]) -> None:
    result = await wired["set"].execute(**_base_set_args(cluster="some-cluster"))
    assert result.success is False
    assert "cluster must be one of" in (result.error or "")


# ---------------------------------------------------------------------------
# 14. Rationale / reason validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_reason_rejected(wired: dict[str, Any]) -> None:
    result = await wired["set"].execute(**_base_set_args(reason="short"))
    assert result.success is False
    assert "reason" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_missing_rationale_on_read_rejected(wired: dict[str, Any]) -> None:
    result = await wired["read"].execute(**_base_read_args(rationale=""))
    assert result.success is False
    assert "rationale" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 15. Create-if-missing behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_if_missing_true_creates_new_configmap(
    wired: dict[str, Any],
) -> None:
    """create_if_missing=True + 404 on patch -> falls through to create."""
    wired["v1"].patch_namespaced_config_map.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    # Predecessor read also returns 404 (no existing CM).
    wired["v1"].read_namespaced_config_map.side_effect = ApiException(
        status=404, reason="Not Found"
    )

    result = await wired["set"].execute(
        **_base_set_args(
            configmap_name="new-config",
            create_if_missing=True,
        )
    )
    assert result.success is True, result.error
    assert result.data["status"] == "applied"
    assert result.data["operation"] == "create"
    assert wired["v1"].create_namespaced_config_map.call_count == 1


@pytest.mark.asyncio
async def test_create_if_missing_false_refuses_to_conjure(
    wired: dict[str, Any],
) -> None:
    """Default create_if_missing=False fails when the ConfigMap is absent."""
    wired["v1"].patch_namespaced_config_map.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    wired["v1"].read_namespaced_config_map.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    result = await wired["set"].execute(**_base_set_args(configmap_name="ghost-config"))
    assert result.success is False
    assert "does not exist" in (result.error or "")


# ---------------------------------------------------------------------------
# Sanity: allow-list shapes + tool name registration
# ---------------------------------------------------------------------------


def test_allowed_clusters_and_namespaces_are_frozenset() -> None:
    assert isinstance(ALLOWED_CLUSTERS, frozenset)
    assert isinstance(ALLOWED_NAMESPACES, frozenset)
    assert "madfam-prod" in ALLOWED_CLUSTERS
    assert "selva-office" in ALLOWED_NAMESPACES


def test_tool_names_are_unique_and_config_prefixed() -> None:
    names = {
        ReadConfigMapTool().name,
        SetConfigMapValueTool().name,
        DeleteConfigMapKeyTool().name,
        ListConfigMapsTool().name,
    }
    assert len(names) == 4  # all unique
    assert all(n.startswith("config_") for n in names)
