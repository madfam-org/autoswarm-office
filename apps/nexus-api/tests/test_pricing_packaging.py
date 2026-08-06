"""CI drift gate: the canonical pricing JSON actually ships in the image.

``billing_tiers._load_pricing`` resolves ``infra/pricing/selva-tiers.json``
relative to the repo root. The production image never COPY'd ``infra/``, so
the loader ran on its emergency fallback in production with nobody noticing —
the documented silent-fail-open defect class. Two invariants pin the fix:

1. ``Dockerfile.nexus-api`` copies ``infra/pricing/`` into the runtime image,
   and the deploy workflow rebuilds nexus-api when ``infra/pricing/`` changes
   (an image is stale the moment its baked-in pricing file is).
2. When the JSON is missing anyway, the fallback is LOUD: a CRITICAL record
   with a stable marker that alerting can key on.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _REPO_ROOT / "infra" / "docker" / "Dockerfile.nexus-api"
_DEPLOY_YML = _REPO_ROOT / ".github" / "workflows" / "deploy.yml"


class TestImagePackaging:
    def test_dockerfile_copies_pricing_json(self) -> None:
        assert _DOCKERFILE.exists(), f"Dockerfile missing at {_DOCKERFILE}"
        text = _DOCKERFILE.read_text(encoding="utf-8")
        assert "COPY infra/pricing/ infra/pricing/" in text, (
            "Dockerfile.nexus-api must COPY infra/pricing/ into the runtime "
            "image — without it billing_tiers._load_pricing silently runs on "
            "its emergency fallback in production."
        )

    def test_deploy_workflow_rebuilds_on_pricing_change(self) -> None:
        assert _DEPLOY_YML.exists(), f"deploy workflow missing at {_DEPLOY_YML}"
        text = _DEPLOY_YML.read_text(encoding="utf-8")
        nexus_lines = [
            line for line in text.splitlines() if 'check_service "nexus-api"' in line
        ]
        assert nexus_lines, "deploy.yml lost its nexus-api change-detection line"
        assert all("infra/pricing/" in line for line in nexus_lines), (
            "deploy.yml must rebuild nexus-api when infra/pricing/ changes — "
            "the pricing JSON is baked into the image, so an image built "
            "before a pricing edit keeps serving the old numbers."
        )


class TestFallbackIsLoud:
    def test_missing_json_logs_critical_with_marker(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate the packaging accident: point the loader at a missing
        file and require the CRITICAL marker record. A fallback that only
        whispers is how this ran unnoticed in production."""
        from nexus_api import billing_tiers

        caplog.set_level(logging.CRITICAL, logger="nexus_api.billing_tiers")
        monkeypatch.setattr(billing_tiers, "_PRICING_JSON", tmp_path / "not-there.json")
        billing_tiers._load_pricing.cache_clear()
        try:
            pricing = billing_tiers._load_pricing()
        finally:
            monkeypatch.undo()
            billing_tiers._load_pricing.cache_clear()

        # The emergency values still keep the service running...
        assert "dhanam_subscription_daily_limits" in pricing
        # ...but the fallback announces itself at CRITICAL with the marker.
        assert any(
            r.levelno == logging.CRITICAL and "pricing_json_fallback_active" in r.getMessage()
            for r in caplog.records
        ), "the emergency pricing fallback must log CRITICAL with its marker"
