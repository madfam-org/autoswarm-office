"""
Tests for the Hermes integration environment variables registered in Settings.
Verifies default values, type expectations, and that the new keys are present.
"""

from __future__ import annotations

from nexus_api.config import Settings


def test_hermes_secrets_have_empty_string_defaults(monkeypatch):
    """All new gateway/MCP secrets default to empty string (not None)."""
    # Force a minimal valid config
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("COLYSEUS_SECRET", "test-secret-passphrase-32-chars!!")
    monkeypatch.setenv("ENVIRONMENT", "development")

    s = Settings()
    assert s.telegram_bot_token == ""
    assert s.telegram_webhook_secret == ""
    assert s.discord_webhook_secret == ""
    assert s.tavily_api_key == ""
    assert s.github_token == ""


def test_hermes_paths_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("COLYSEUS_SECRET", "test-secret-passphrase-32-chars!!")
    monkeypatch.setenv("ENVIRONMENT", "development")

    s = Settings()
    assert s.selva_skills_dir == "/var/lib/selva/skills"
    assert s.selva_state_db_path == "/var/lib/selva/selva_state.db"


def test_hermes_secrets_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("COLYSEUS_SECRET", "test-secret-passphrase-32-chars!!")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot12345:token")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc123")

    s = Settings()
    assert s.telegram_bot_token == "bot12345:token"
    assert s.tavily_api_key == "tvly-abc123"
