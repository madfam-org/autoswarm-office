"""Worker process configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for LangGraph execution workers.

    Values are read from environment variables and can be overridden with
    a ``.env`` file in the worker root.
    """

    # -- Infrastructure -------------------------------------------------------
    redis_url: str = "redis://localhost:6379"
    nexus_api_url: str = "http://localhost:4300"

    # -- AI Inference ---------------------------------------------------------
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
