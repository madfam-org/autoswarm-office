"""Regression test for the PLATFORM-tagged tool inventory.

Every tool listed in ``PLATFORM_TOOL_NAMES`` below must be tagged
``Audience.PLATFORM``. If this test fails, either:

- A platform-only tool was added without tagging → tag it with
  ``_cls.audience = Audience.PLATFORM`` at the bottom of its module, OR
- A tool in this list was renamed/removed → update this list, OR
- A tool's classification changed on purpose → update this list AND
  leave a comment in the PR explaining the semantic shift.

The list is hardcoded intentionally: it catches accidental regressions
(someone adds a new K8s/Cloudflare/Janua-admin tool and forgets to tag
it) faster than any naming-convention heuristic.
"""

from __future__ import annotations

import pytest

from selva_tools import Audience, get_tool_registry

# Tools that operate on platform-owned infra, cross-tenant data, or the
# Selva internals. These MUST be tagged PLATFORM so tenant swarms never
# see them in their spec list.
PLATFORM_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # ArgoCD — application sync / state reads
        "argocd_list_apps",
        "argocd_get_app",
        "argocd_sync_app",
        "argocd_refresh_app",
        # pgBackRest — platform-owned Postgres backups
        "pgbackrest_info",
        "pgbackrest_backup",
        "pgbackrest_check",
        # Cloudflare — zones, DNS, Page Rules, Tunnel, R2, SaaS
        "cloudflare_create_zone",
        "cloudflare_list_zones",
        "cloudflare_create_dns_record",
        "cloudflare_list_dns_records",
        "cloudflare_create_redirect_rule",
        "cloudflare_list_page_rules",
        "r2_bucket_list",
        "r2_bucket_create",
        "r2_bucket_delete",
        "r2_cors_set",
        "cf_saas_hostname_add",
        "cf_saas_hostname_status",
        "cf_saas_hostname_list",
        "cf_saas_hostname_delete",
        "cf_tunnel_list",
        "cf_tunnel_create",
        "cf_tunnel_get_ingress",
        "cf_tunnel_put_ingress",
        # DNS — Porkbun
        "porkbun_list_domains",
        "porkbun_get_nameservers",
        "porkbun_update_nameservers",
        "porkbun_list_dns_records",
        "porkbun_create_dns_record",
        "porkbun_delete_dns_record",
        "porkbun_ping",
        "porkbun_domain_health_check",
        "porkbun_list_url_forwarding",
        "porkbun_delete_url_forwarding",
        # DB lifecycle — Postgres dump/restore (platform-owned)
        "db_dump_to_r2",
        "db_restore_from_r2",
        "db_mask_and_copy",
        "db_size_report",
        # Enclii — infra ops (exec/restart/scale/logs/health/secrets)
        "enclii_exec",
        "enclii_restart",
        "enclii_scale",
        "enclii_logs",
        "enclii_health",
        "enclii_secrets",
        # Factory manifest — platform self-declaration
        "factory_manifest_get_for_repo",
        "factory_manifest_verify",
        "factory_manifest_publish",
        # GitHub org admin
        "github_admin_create_team",
        "github_admin_set_team_membership",
        "github_admin_set_branch_protection",
        "github_admin_audit_team_membership",
        # Grafana — observability
        "grafana_dashboard_list",
        "grafana_panel_export",
        # HITL introspection — self-introspection of Bayesian trust state
        "hitl_get_my_bucket_state",
        "hitl_get_effective_tier",
        "hitl_recent_decisions",
        "hitl_why_asked",
        # Janua admin — OAuth client + org create (platform onboards)
        "janua_oauth_client_create",
        "janua_oauth_client_update",
        "janua_oauth_client_rotate_secret",
        "janua_oauth_client_delete",
        "janua_org_create",
        # K8s — ConfigMap / diagnostics / Secret writer
        "config_read_configmap",
        "config_set_configmap_value",
        "config_delete_configmap_key",
        "config_list_configmaps",
        "k8s_get_pods",
        "k8s_describe_pod",
        "k8s_get_events",
        "k8s_get_replicasets",
        "k8s_rollout_status",
        "write_kubernetes_secret",
        # Kustomize — manifest editing (GitOps)
        "kustomize_list_images",
        "kustomize_set_image",
        "kustomize_build",
        # Loki — log queries
        "loki_query_range",
        "loki_labels",
        # Meta-harness — self-improvement loop
        "meta_harness_budget_gate",
        "meta_harness_route",
        "meta_harness_role_summary",
        "meta_harness_convergence_check",
        "meta_harness_submit_round",
        "meta_harness_escalate_tier",
        # NPM registry (Verdaccio)
        "selva_npm_check_expiry",
        "selva_npm_create_token",
        "selva_npm_rotate_token",
        "selva_npm_update_github_secrets",
        # Prometheus — query + alertmanager
        "prom_query",
        "prom_query_range",
        "prom_alerts_active",
        "prom_silence_create",
        # Resend domain management (platform-mediated BYOD)
        "resend_domain_add",
        "resend_domain_verify",
        "resend_domain_list",
        "resend_domain_delete",
        # Selva Office seat provisioning
        "selva_office_seat_create",
        "selva_office_seat_assign_department",
        "selva_office_seat_revoke",
        # Sentry — error tracking (platform-owned DSNs)
        "sentry_issue_list",
        "sentry_issue_get",
        "sentry_issue_update",
        "sentry_event_list_for_issue",
        "sentry_breadcrumbs_get",
        # Skill performance — self-introspection / bandit signal
        "skill_record_outcome",
        "skill_get_metrics",
        # Stripe Connect — platform creates tenant Connect accounts
        "stripe_connect_account_create",
        "stripe_connect_account_link",
        "stripe_connect_account_status",
        # Tenant identities — central cross-service ID map
        "tenant_create_identity_record",
        "tenant_resolve",
        "tenant_validate_consistency",
        # Tool catalog — meta-self-introspection
        "list_my_tools",
        "search_tools_by_capability",
        "describe_tool",
        # Vault — secret storage
        "selva_vault_store",
        "selva_vault_retrieve",
        "selva_vault_list",
        "selva_vault_delete",
        "selva_vault_rotate",
        # Provider webhook management (OUR platform's webhooks)
        "webhooks_stripe_create",
        "webhooks_stripe_list",
        "webhooks_stripe_delete",
        "webhooks_resend_create",
        "webhooks_janua_register_oidc_redirect",
        # Mixed-module platform-specific tools
        "dhanam_space_create",
        "dhanam_subscription_create",
        "dhanam_subscription_update",
        "phyndcrm_tenant_create",
        "phyndcrm_pipeline_bootstrap",
        "karafiel_org_create",
        "karafiel_sat_cert_upload",
        "karafiel_pac_register",
    }
)

# Tools that MUST stay tenant-audience even though their module contains
# platform-tagged siblings. Belt-and-braces against a PR that accidentally
# promotes them.
EXPECTED_TENANT_TOOLS_IN_MIXED_MODULES: frozenset[str] = frozenset(
    {
        "dhanam_credit_ledger_query",
        "phyndcrm_tenant_config_get",
        "karafiel_invoice_series_create",
    }
)


@pytest.fixture(scope="module")
def registry():
    return get_tool_registry()


class TestPlatformToolRegistry:
    def test_every_listed_tool_is_tagged_platform(self, registry) -> None:
        """Each name in PLATFORM_TOOL_NAMES must resolve + be PLATFORM."""
        missing: list[str] = []
        mistagged: list[tuple[str, Audience]] = []
        for name in sorted(PLATFORM_TOOL_NAMES):
            tool = registry.get(name)
            if tool is None:
                missing.append(name)
            elif tool.audience is not Audience.PLATFORM:
                mistagged.append((name, tool.audience))
        assert not missing, f"PLATFORM tools missing from registry: {missing}"
        assert not mistagged, f"PLATFORM tools wrongly tagged: {mistagged}"

    def test_mixed_module_tenant_tools_stay_tenant(self, registry) -> None:
        """Tenant-audience tools in platform-heavy modules must stay tenant."""
        mistagged: list[tuple[str, Audience]] = []
        for name in sorted(EXPECTED_TENANT_TOOLS_IN_MIXED_MODULES):
            tool = registry.get(name)
            if tool is None:
                continue  # If the tool was removed, that's a separate concern.
            if tool.audience is not Audience.TENANT:
                mistagged.append((name, tool.audience))
        assert not mistagged, f"Tenant-audience tools wrongly promoted to PLATFORM: {mistagged}"

    def test_tenant_filter_hides_all_platform_tools(self, registry) -> None:
        """From a tenant swarm's perspective, no PLATFORM tool is visible."""
        visible_to_tenant = set(registry.list_tools(audience=Audience.TENANT))
        leaked = visible_to_tenant & PLATFORM_TOOL_NAMES
        assert not leaked, f"Platform tools visible to tenant audience (filter bug): {leaked}"

    def test_platform_audience_sees_platform_and_tenant(self, registry) -> None:
        """Platform audience is a superset — sees both buckets."""
        visible_to_platform = set(registry.list_tools(audience=Audience.PLATFORM))
        # Every platform tool should be visible
        assert PLATFORM_TOOL_NAMES.issubset(visible_to_platform)
        # Every tenant-audience tool should also be visible
        all_tools = set(registry.list_tools())
        assert all_tools == visible_to_platform

    def test_platform_filter_removes_about_half(self, registry) -> None:
        """Sanity: the filter actually removes a meaningful portion."""
        total = len(registry.list_tools())
        tenant_visible = len(registry.list_tools(audience=Audience.TENANT))
        # We expect ~130 platform tools today. Assert at least 100 are
        # filtered out so we catch regressions where tagging got lost.
        assert (total - tenant_visible) >= 100, (
            f"Expected ≥100 platform-only tools, found {total - tenant_visible}"
        )
