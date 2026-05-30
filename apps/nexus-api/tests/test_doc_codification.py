"""CI drift gate: documentation claims match codebase invariants.

Prevents regression of the 2026-05-30 doc-truth remediation:
- PORTS.md is the SSOT for k8s container ports and health paths
- docs/ must not reference pre-rebrand worker paths
- Tool registry count floor tracks registered builtins
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PORTS_MD = _REPO_ROOT / "docs" / "PORTS.md"
_DOCS_DIR = _REPO_ROOT / "docs"
_AGENTS_MD = _REPO_ROOT / "AGENTS.md"

# Stale k8s container ports — must not appear in PORTS.md k8s section.
_STALE_K8S_PORTS = ("8000", "2567", "3001")

# Canonical k8s container ports — must appear in PORTS.md.
_CANONICAL_K8S_PORTS = ("4300", "4303", "3000", "4304", "4305")

# Health paths that prod/code expose — must be documented in PORTS.md.
_REQUIRED_HEALTH_PATHS = (
    "/health",
    "/api/v1/health/health",
    "/api/v1/health/ready",
)

_MIN_BUILTIN_TOOLS = 268

_AUTONOMOUS_OPS_PROGRAM = _REPO_ROOT / "docs" / "AUTONOMOUS_OPERATIONS_PROGRAM.md"
_ROADMAP_MD = _REPO_ROOT / "ROADMAP.md"
_DNS_RECORDS = _REPO_ROOT / "infra" / "cloudflare" / "dns-records.yaml"
_TUNNEL_ROUTES = _REPO_ROOT / "infra" / "cloudflare" / "tunnel-routes.yaml"

_REQUIRED_DNS_HOSTNAMES = (
    "app.selva.town",
    "gw.selva.town",
    "staging-api.selva.town",
    "staging.selva.town",
    "staging-admin.selva.town",
    "staging-ws.selva.town",
    "staging-gw.selva.town",
)

_REQUIRED_TUNNEL_HOSTNAMES = _REQUIRED_DNS_HOSTNAMES


class TestPortsDoc:
    def test_ports_md_exists(self) -> None:
        assert _PORTS_MD.exists(), "docs/PORTS.md is the port SSOT"

    def test_k8s_section_lists_canonical_container_ports(self) -> None:
        text = _PORTS_MD.read_text(encoding="utf-8")
        k8s_section = text.split("## Container ports (k8s)", 1)[1].split("##", 1)[0]
        for port in _CANONICAL_K8S_PORTS:
            assert port in k8s_section, (
                f"PORTS.md k8s section must document container port {port}"
            )

    def test_k8s_section_does_not_list_stale_container_ports(self) -> None:
        text = _PORTS_MD.read_text(encoding="utf-8")
        k8s_section = text.split("## Container ports (k8s)", 1)[1].split("##", 1)[0]
        for port in _STALE_K8S_PORTS:
            assert port not in k8s_section, (
                f"PORTS.md k8s section still lists stale container port {port}"
            )

    def test_health_endpoints_documented(self) -> None:
        text = _PORTS_MD.read_text(encoding="utf-8")
        health_section = text.split("## Health and readiness endpoints", 1)[1].split("##", 1)[0]
        for path in _REQUIRED_HEALTH_PATHS:
            assert path in health_section, (
                f"PORTS.md health section must document {path}"
            )


class TestDocsLegacyPaths:
    def test_docs_do_not_reference_autoswarm_workers(self) -> None:
        offenders: list[str] = []
        for md_file in _DOCS_DIR.rglob("*.md"):
            if "autoswarm_workers" in md_file.read_text(encoding="utf-8"):
                offenders.append(str(md_file.relative_to(_REPO_ROOT)))
        assert not offenders, (
            "docs/ must use selva_workers paths, not autoswarm_workers. "
            f"Offenders: {offenders}"
        )


class TestToolCountFloor:
    def test_registered_builtin_tools_meets_floor(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        count = len(get_builtin_tools())
        assert count >= _MIN_BUILTIN_TOOLS, (
            f"Registered built-in tools dropped below {_MIN_BUILTIN_TOOLS} "
            f"(got {count}). Bump _MIN_BUILTIN_TOOLS intentionally if tools "
            "were removed, or restore registrations."
        )


class TestAgentsToolClaim:
    def test_agents_md_cites_current_tool_count_floor(self) -> None:
        """AGENTS.md should cite a count >= the CI floor (not stale 240)."""
        text = _AGENTS_MD.read_text(encoding="utf-8")
        match = re.search(r"(\d+)\s+built-in tools", text)
        assert match, "AGENTS.md must cite built-in tool count near registry line"
        cited = int(match.group(1))
        assert cited >= _MIN_BUILTIN_TOOLS, (
            f"AGENTS.md cites {cited} tools but floor is {_MIN_BUILTIN_TOOLS}"
        )


class TestCloudflareInfra:
    def test_dns_records_lists_prod_and_staging_hostnames(self) -> None:
        text = _DNS_RECORDS.read_text(encoding="utf-8")
        for hostname in _REQUIRED_DNS_HOSTNAMES:
            assert hostname in text, (
                f"infra/cloudflare/dns-records.yaml must declare {hostname}"
            )

    def test_dns_records_target_shared_enclii_prod_tunnel(self) -> None:
        text = _DNS_RECORDS.read_text(encoding="utf-8")
        assert "tunnel: enclii-prod" in text, (
            "dns-records.yaml must CNAME to enclii-prod (shared live tunnel)"
        )
        assert "autoswarm-office.cfargotunnel.com" not in text, (
            "dns-records.yaml must not point at the defunct autoswarm-office tunnel"
        )

    def test_tunnel_routes_lists_prod_and_staging_hostnames(self) -> None:
        text = _TUNNEL_ROUTES.read_text(encoding="utf-8")
        for hostname in _REQUIRED_TUNNEL_HOSTNAMES:
            assert f"hostname: {hostname}" in text, (
                f"infra/cloudflare/tunnel-routes.yaml must route {hostname}"
            )
        assert "autoswarm-staging.svc.cluster.local" in text, (
            "tunnel-routes.yaml must target autoswarm-staging namespace"
        )


class TestAutonomousOperationsProgram:
    def test_program_doc_exists(self) -> None:
        assert _AUTONOMOUS_OPS_PROGRAM.exists(), (
            "docs/AUTONOMOUS_OPERATIONS_PROGRAM.md is the north-star SSOT"
        )

    def test_roadmap_links_program(self) -> None:
        text = _ROADMAP_MD.read_text(encoding="utf-8")
        assert "AUTONOMOUS_OPERATIONS_PROGRAM.md" in text, (
            "ROADMAP.md must link to the autonomous operations program"
        )
        assert "Phase 0" in text and "Phase 6" in text, (
            "ROADMAP.md must summarize program phases 0–6"
        )

    def test_tulana_import_endpoint_documented(self) -> None:
        tulana_doc = _REPO_ROOT / "docs" / "TULANA_SKU_CAMPAIGN_ORCHESTRATION_2026-05-29.md"
        text = tulana_doc.read_text(encoding="utf-8")
        assert "POST /api/v1/campaigns/import-tulana-pack" in text or (
            "import-tulana-pack" in text
        ), "Tulana orchestration doc must reference the import endpoint"


class TestCampaignsApi:
    _MAIN_PY = _REPO_ROOT / "apps" / "nexus-api" / "nexus_api" / "main.py"

    def test_main_registers_campaigns_router(self) -> None:
        text = self._MAIN_PY.read_text(encoding="utf-8")
        assert "campaigns.router" in text, (
            "main.py must include campaigns router for Tulana import"
        )

    def test_campaigns_router_module_exists(self) -> None:
        router_path = _REPO_ROOT / "apps" / "nexus-api" / "nexus_api" / "routers" / "campaigns.py"
        assert router_path.exists(), "campaigns router must exist"
        text = router_path.read_text(encoding="utf-8")
        assert "/import-tulana-pack" in text

    def test_staging_keda_patch_exists(self) -> None:
        patch = _REPO_ROOT / "infra" / "k8s" / "overlays" / "staging" / "patch-keda-staging.yaml"
        assert patch.exists(), "staging KEDA pin patch must exist for RWO PVC"
        text = patch.read_text(encoding="utf-8")
        assert "maxReplicaCount" in text and "value: 1" in text

    def test_observability_patches_exist(self) -> None:
        patch_dir = _REPO_ROOT / "infra" / "k8s" / "production" / "patches"
        for name in (
            "observability-nexus-api.yaml",
            "observability-workers.yaml",
            "observability-gateway.yaml",
        ):
            path = patch_dir / name
            assert path.exists(), f"missing {name}"
            text = path.read_text(encoding="utf-8")
            assert "autoswarm-observability-secrets" in text
            assert "optional: true" in text
