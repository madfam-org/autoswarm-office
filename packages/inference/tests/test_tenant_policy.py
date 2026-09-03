"""Tests for per-tenant inference policy: floors, caps, and rate limits."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from madfam_inference.tenant_policy import (
    InProcessRateLimiter,
    TenantPolicy,
    TenantPolicyBook,
    apply_floor,
    load_tenant_policies,
    sensitivity_rank,
)
from madfam_inference.types import Sensitivity

# The org id Crea Tu Mundo's MAP sends as X-Selva-Tenant-Org.
CREA_ORG_ID = "e6cbd51d-8329-4c4e-8c74-aba643ab4575"


class TestApplyFloor:
    def test_floor_raises_a_weaker_request(self) -> None:
        assert apply_floor(Sensitivity.PUBLIC, Sensitivity.RESTRICTED) is Sensitivity.RESTRICTED
        assert apply_floor(Sensitivity.INTERNAL, Sensitivity.RESTRICTED) is Sensitivity.RESTRICTED

    def test_floor_never_lowers_a_stronger_request(self) -> None:
        """A caller may always ask for MORE protection than its floor."""
        assert apply_floor(Sensitivity.RESTRICTED, Sensitivity.INTERNAL) is Sensitivity.RESTRICTED
        assert (
            apply_floor(Sensitivity.CONFIDENTIAL, Sensitivity.PUBLIC) is Sensitivity.CONFIDENTIAL
        )

    def test_no_floor_is_a_passthrough(self) -> None:
        for level in Sensitivity:
            assert apply_floor(level, None) is level

    def test_rank_order(self) -> None:
        assert (
            sensitivity_rank(Sensitivity.PUBLIC)
            < sensitivity_rank(Sensitivity.INTERNAL)
            < sensitivity_rank(Sensitivity.CONFIDENTIAL)
            < sensitivity_rank(Sensitivity.RESTRICTED)
        )


class TestPolicyBook:
    def test_unconfigured_org_has_no_policy(self) -> None:
        book = TenantPolicyBook()
        assert book.for_org("some-other-org") is None
        assert book.for_org(None) is None

    def test_defaults_apply_when_tenant_has_no_policy(self) -> None:
        book = TenantPolicyBook(
            default_request_timeout_seconds=45.0, default_max_tokens_cap=4096
        )
        assert book.timeout_for(None) == 45.0
        assert book.max_tokens_for(None) == 4096

    def test_tenant_overrides_defaults(self) -> None:
        policy = TenantPolicy(
            org_id=CREA_ORG_ID, request_timeout_seconds=30.0, max_tokens_cap=1500
        )
        book = TenantPolicyBook(tenants={CREA_ORG_ID: policy})
        assert book.timeout_for(policy) == 30.0
        assert book.max_tokens_for(policy) == 1500


class TestLoadFromYaml:
    def _write(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "tenant-policies.yaml"
        path.write_text(textwrap.dedent(body))
        load_tenant_policies.cache_clear()
        return path

    def test_missing_file_yields_empty_book(self, tmp_path: Path) -> None:
        load_tenant_policies.cache_clear()
        book = load_tenant_policies(tmp_path / "nope.yaml")
        assert book.tenants == {}

    def test_loads_crea_tenant_as_mapping(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            f"""
            default_request_timeout_seconds: 45
            default_max_tokens_cap: 4096
            tenants:
              "{CREA_ORG_ID}":
                display_name: Crea Tu Mundo
                sensitivity_floor: restricted
                allowed_task_types: [summarization, family-feedback]
                max_tokens_cap: 1500
                request_timeout_seconds: 40
                rate_limit_per_minute: 30
                daily_usd_budget: 2.0
            """,
        )
        book = load_tenant_policies(path)
        policy = book.for_org(CREA_ORG_ID)
        assert policy is not None
        assert policy.display_name == "Crea Tu Mundo"
        assert policy.sensitivity_floor is Sensitivity.RESTRICTED
        assert policy.allowed_task_types == ["summarization", "family-feedback"]
        assert policy.max_tokens_cap == 1500
        assert policy.rate_limit_per_minute == 30
        assert policy.daily_usd_budget == 2.0

    def test_loads_list_shape(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            f"""
            tenants:
              - org_id: "{CREA_ORG_ID}"
                sensitivity_floor: confidential
            """,
        )
        book = load_tenant_policies(path)
        assert book.for_org(CREA_ORG_ID).sensitivity_floor is Sensitivity.CONFIDENTIAL

    def test_malformed_entry_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """A bad entry must not take out the whole book — but the good
        tenants must still load, and the operator gets a WARNING."""
        path = self._write(
            tmp_path,
            f"""
            tenants:
              broken:
                sensitivity_floor: not-a-level
              "{CREA_ORG_ID}":
                sensitivity_floor: restricted
            """,
        )
        book = load_tenant_policies(path)
        assert "broken" not in book.tenants
        assert book.for_org(CREA_ORG_ID).sensitivity_floor is Sensitivity.RESTRICTED

    def test_unparseable_file_yields_empty_book(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "tenants: [ this is: not: valid: yaml")
        book = load_tenant_policies(path)
        assert book.tenants == {}

    def test_shipped_production_policy_file_declares_crea(self) -> None:
        """The manifest that actually ships must carry the Crea tenant with
        a restricted floor — a drift check, not a mock."""
        repo_root = Path(__file__).resolve().parents[3]
        manifest = repo_root / "infra" / "k8s" / "production" / "tenant-policies.yaml"
        assert manifest.exists(), f"missing {manifest}"

        import yaml

        rendered = yaml.safe_load(manifest.read_text())
        embedded = rendered["data"]["tenant-policies.yaml"]
        load_tenant_policies.cache_clear()
        book = TenantPolicyBook(
            **{
                k: v
                for k, v in yaml.safe_load(embedded).items()
                if k != "tenants"
            },
            tenants={
                org_id: TenantPolicy(org_id=org_id, **body)
                for org_id, body in yaml.safe_load(embedded)["tenants"].items()
            },
        )
        policy = book.for_org(CREA_ORG_ID)
        assert policy is not None, "Crea Tu Mundo tenant absent from production policy"
        assert policy.sensitivity_floor is Sensitivity.RESTRICTED
        assert policy.rate_limit_per_minute is not None
        assert policy.daily_usd_budget is not None


class TestRateLimiter:
    def test_unlimited_when_limit_is_none(self) -> None:
        limiter = InProcessRateLimiter()
        for _ in range(1000):
            allowed, _retry = limiter.check("org", None)
            assert allowed

    def test_denies_past_the_limit(self) -> None:
        limiter = InProcessRateLimiter()
        for _ in range(3):
            assert limiter.check("org", 3)[0] is True
        allowed, retry_after = limiter.check("org", 3)
        assert allowed is False
        assert retry_after >= 1

    def test_keys_are_independent(self) -> None:
        limiter = InProcessRateLimiter()
        assert limiter.check("org-a", 1)[0] is True
        assert limiter.check("org-a", 1)[0] is False
        assert limiter.check("org-b", 1)[0] is True

    def test_window_expiry_admits_again(self) -> None:
        limiter = InProcessRateLimiter(window_seconds=0.05)
        assert limiter.check("org", 1)[0] is True
        assert limiter.check("org", 1)[0] is False
        import time as _time

        _time.sleep(0.06)
        assert limiter.check("org", 1)[0] is True


@pytest.fixture(autouse=True)
def _clear_policy_cache():
    """Keep the module-level lru_cache from leaking between tests."""
    load_tenant_policies.cache_clear()
    yield
    load_tenant_policies.cache_clear()
