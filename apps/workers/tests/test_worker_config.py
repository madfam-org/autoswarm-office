"""Tests for worker Settings configuration."""

from __future__ import annotations

import warnings

import pytest

from selva_workers.config import Settings


def _make_settings(**overrides: object) -> Settings:
    """Create a Settings instance that ignores .env files."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class TestWorkerSettings:
    """Settings class handles .env extras gracefully."""

    def test_extra_ignore_allows_unknown_fields(self) -> None:
        """Settings with extra='ignore' should not crash on unknown env vars."""
        # Simulate nexus-api-specific vars that would appear in a shared .env
        settings = Settings(
            _env_file=None,
            JANUA_ISSUER_URL="https://auth.example.com",  # type: ignore[call-arg]
            COLYSEUS_SECRET="test-secret",  # type: ignore[call-arg]
            UNKNOWN_VAR="should-be-ignored",  # type: ignore[call-arg]
        )
        assert settings.redis_url == "redis://localhost:6379"

    def test_known_fields_still_parsed(self) -> None:
        """Known fields are still correctly parsed."""
        settings = _make_settings(
            redis_url="redis://custom:6380",
            github_token="gh-test-token",
        )
        assert settings.redis_url == "redis://custom:6380"
        assert settings.github_token == "gh-test-token"


class TestWorkerRedisURLValidation:
    """REDIS_URL must start with 'redis'."""

    def test_redis_url_accepted(self) -> None:
        settings = _make_settings(redis_url="redis://localhost:6379")
        assert settings.redis_url.startswith("redis")

    def test_rediss_url_accepted(self) -> None:
        settings = _make_settings(redis_url="rediss://secure:6380")
        assert settings.redis_url.startswith("rediss")

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="REDIS_URL must start with"):
            _make_settings(redis_url="http://not-redis:6379")


class TestWorkerNexusAPIURLValidation:
    """NEXUS_API_URL must start with 'http'."""

    def test_http_url_accepted(self) -> None:
        settings = _make_settings(nexus_api_url="http://localhost:4300")
        assert settings.nexus_api_url.startswith("http")

    def test_https_url_accepted(self) -> None:
        settings = _make_settings(nexus_api_url="https://api.example.com")
        assert settings.nexus_api_url.startswith("https")

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="NEXUS_API_URL must start with"):
            _make_settings(nexus_api_url="ftp://bad-protocol:4300")


class TestWorkerInferenceKeyWarning:
    """Worker should warn when no inference API keys are configured."""

    def test_warns_with_no_keys(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings()
        inference_warnings = [x for x in w if "No inference API keys configured" in str(x.message)]
        assert len(inference_warnings) == 1

    def test_no_warning_with_anthropic_key(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(anthropic_api_key="sk-test")
        inference_warnings = [x for x in w if "No inference API keys configured" in str(x.message)]
        assert len(inference_warnings) == 0

    def test_no_warning_with_openai_key(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(openai_api_key="sk-test")
        inference_warnings = [x for x in w if "No inference API keys configured" in str(x.message)]
        assert len(inference_warnings) == 0

    def test_no_warning_with_groq_key(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(groq_api_key="gsk-test")
        inference_warnings = [x for x in w if "No inference API keys configured" in str(x.message)]
        assert len(inference_warnings) == 0


class TestWorkerGitIdentitySettings:
    """Git identity settings for agent commits."""

    def test_defaults_to_madfam_bot(self) -> None:
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            settings = _make_settings()
        assert settings.git_author_name == "selva-bot"
        assert settings.git_author_email == "bot@selva.town"

    def test_custom_git_identity(self) -> None:
        settings = _make_settings(
            git_author_name="custom-bot",
            git_author_email="custom@example.com",
        )
        assert settings.git_author_name == "custom-bot"
        assert settings.git_author_email == "custom@example.com"


class TestWorkerDefaultSettingsValid:
    """Default Settings (with warnings) must not raise."""

    def test_defaults_pass_validation(self) -> None:
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            settings = _make_settings()
        assert settings.redis_url.startswith("redis")
        assert settings.nexus_api_url.startswith("http")
