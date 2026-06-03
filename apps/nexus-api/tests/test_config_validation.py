"""Tests for nexus-api Settings validation."""

from __future__ import annotations

import warnings

import pytest

from nexus_api.config import Settings


def _make_settings(**overrides: object) -> Settings:
    """Create a Settings instance that ignores .env files."""
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://selva:selva@localhost:5432/selva",
        "redis_url": "redis://localhost:6379",
        "environment": "development",
        "dev_auth_bypass": False,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


class TestDatabaseURLValidation:
    """DATABASE_URL must start with 'postgresql' or 'sqlite'."""

    def test_postgresql_url_accepted(self) -> None:
        settings = _make_settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )
        assert settings.database_url.startswith("postgresql")

    def test_sqlite_url_accepted(self) -> None:
        settings = _make_settings(database_url="sqlite+aiosqlite://")
        assert settings.database_url.startswith("sqlite")

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="DATABASE_URL must start with"):
            _make_settings(database_url="mysql://localhost/db")


class TestRedisURLValidation:
    """REDIS_URL must start with 'redis'."""

    def test_redis_url_accepted(self) -> None:
        settings = _make_settings(redis_url="redis://localhost:6379")
        assert settings.redis_url.startswith("redis")

    def test_rediss_url_accepted(self) -> None:
        settings = _make_settings(redis_url="rediss://secure-redis:6380")
        assert settings.redis_url.startswith("rediss")

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="REDIS_URL must start with"):
            _make_settings(redis_url="http://not-redis:6379")


class TestDevAuthBypass:
    """DEV_AUTH_BYPASS should warn in non-development environments."""

    def test_no_warning_in_development(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(dev_auth_bypass=True, environment="development")
        auth_warnings = [x for x in w if "DEV_AUTH_BYPASS" in str(x.message)]
        assert len(auth_warnings) == 0

    def test_warns_in_production(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(dev_auth_bypass=True, environment="production")
        auth_warnings = [x for x in w if "DEV_AUTH_BYPASS" in str(x.message)]
        assert len(auth_warnings) == 1
        assert "security risk" in str(auth_warnings[0].message).lower()

    def test_warns_in_staging(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(dev_auth_bypass=True, environment="staging")
        auth_warnings = [x for x in w if "DEV_AUTH_BYPASS" in str(x.message)]
        assert len(auth_warnings) == 1


class TestColyseusSecret:
    """COLYSEUS_SECRET default should warn in non-development environments."""

    def test_no_warning_in_development(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(
                colyseus_secret="change-me-in-production",
                environment="development",
            )
        secret_warnings = [x for x in w if "COLYSEUS_SECRET" in str(x.message)]
        assert len(secret_warnings) == 0

    def test_warns_in_production(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(
                colyseus_secret="change-me-in-production",
                environment="production",
            )
        secret_warnings = [x for x in w if "COLYSEUS_SECRET" in str(x.message)]
        assert len(secret_warnings) == 1

    def test_no_warning_with_custom_secret(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _make_settings(
                colyseus_secret="my-secure-random-secret",
                environment="production",
            )
        secret_warnings = [x for x in w if "COLYSEUS_SECRET" in str(x.message)]
        assert len(secret_warnings) == 0


class TestDefaultSettingsValid:
    """Default Settings must pass validation in development mode."""

    def test_defaults_pass_in_development(self) -> None:
        settings = _make_settings(environment="development")
        assert settings.environment == "development"
        assert settings.database_url.startswith("postgresql")
        assert settings.redis_url.startswith("redis")
