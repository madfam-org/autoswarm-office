"""A2A AgentCard must surface the configured public app URL, not CORS origins."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nexus_api.config import Settings


def test_public_app_url_prefers_public_app_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.selva.town")
    monkeypatch.setenv("CORS_ORIGINS", "https://admin.selva.town,https://api.selva.town")
    settings = Settings()
    assert settings.public_app_url == "https://app.selva.town"


def test_public_app_url_falls_back_to_next_public_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "https://staging.selva.town")
    settings = Settings()
    assert settings.public_app_url == "https://staging.selva.town"


def test_cors_origins_parses_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://app.selva.town,https://admin.selva.town,https://api.selva.town",
    )
    settings = Settings()
    assert settings.cors_origins == [
        "https://app.selva.town",
        "https://admin.selva.town",
        "https://api.selva.town",
    ]


def test_a2a_agent_card_uses_public_app_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration: mounted A2A router reads public_app_url, not cors_origins[0]."""
    import nexus_api.main as main_mod

    custom = Settings(
        database_url="sqlite+aiosqlite://",
        environment="development",
        public_app_url="https://app.selva.town",
        cors_origins=["https://admin.selva.town", "https://api.selva.town"],
    )
    monkeypatch.setattr(main_mod, "get_settings", lambda: custom)

    app = main_mod.create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/a2a/.well-known/agent.json")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://app.selva.town"
