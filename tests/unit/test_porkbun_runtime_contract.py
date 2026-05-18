from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_workers_mount_porkbun_credentials_from_autoswarm_secrets() -> None:
    manifest = (ROOT / "infra/k8s/production/workers.yaml").read_text()

    assert "name: PORKBUN_API_KEY" in manifest
    assert "key: PORKBUN_API_KEY" in manifest
    assert "name: PORKBUN_SECRET_KEY" in manifest
    assert "key: PORKBUN_SECRET_KEY" in manifest
    assert manifest.count("name: autoswarm-secrets") >= 2


def test_madfam_org_config_declares_porkbun_provider_contract() -> None:
    config = (ROOT / "infra/k8s/production/org-config.yaml").read_text()

    assert "porkbun:" in config
    assert "provider: porkbun" in config
    assert "service_type: registrar" in config
    assert "api_key_env: PORKBUN_API_KEY" in config
    assert "secret_key_env: PORKBUN_SECRET_KEY" in config
    assert "direct API use is break-glass" in config
