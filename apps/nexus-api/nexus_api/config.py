"""Application configuration via environment variables and .env files."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the Nexus API.

    All values are read from environment variables (case-insensitive) and
    can be overridden via a ``.env`` file at the project root.
    """

    # -- Infrastructure -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://autoswarm:autoswarm@localhost:5432/autoswarm"
    redis_url: str = "redis://localhost:6379"

    # -- Auth (Janua OIDC) ----------------------------------------------------
    janua_issuer_url: str = "https://auth.madfam.io"
    janua_client_id: str = "autoswarm-office"
    janua_client_secret: str = ""

    # -- Billing (Dhanam) -----------------------------------------------------
    dhanam_api_url: str = "https://api.dhan.am"
    dhanam_webhook_secret: str = ""

    # -- Gateway (GitHub webhooks) ---------------------------------------------
    github_webhook_secret: str = ""

    # -- AI Inference ---------------------------------------------------------
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # -- Colyseus -------------------------------------------------------------
    colyseus_secret: str = "change-me-in-production"

    # -- Server ---------------------------------------------------------------
    environment: str = "production"
    port: int = 4300
    cors_origins: list[str] = [
        "http://localhost:4301",
        "http://localhost:4302",
    ]

    # -- Security -------------------------------------------------------------
    dev_auth_bypass: bool = False
    rate_limit_per_minute: int = 60
    log_format: str = "json"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
