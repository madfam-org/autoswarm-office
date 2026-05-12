"""Worker process configuration."""

from __future__ import annotations

import warnings
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

# Resolve project root so env_file works regardless of CWD.
# config.py -> selva_workers -> workers -> apps -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuration for LangGraph execution workers.

    Values are read from environment variables and can be overridden with
    a ``.env`` file in the worker root.
    """

    # -- Infrastructure -------------------------------------------------------
    environment: str = "development"
    redis_url: str = "redis://localhost:6379"
    nexus_api_url: str = "http://localhost:4300"
    database_url: str | None = None

    # -- Phynd-CRM ------------------------------------------------------------
    phynd_crm_url: str | None = None
    phynd_crm_token: str | None = None

    # -- Search ---------------------------------------------------------------
    search_api_key: str | None = None
    search_provider: str = "tavily"
    repo_base_path: str = "~/.autoswarm/repos"

    # -- GitHub / Deployment ---------------------------------------------------
    github_token: str | None = None
    enclii_deploy_token: str | None = None
    worker_api_token: str = "dev-bypass"  # overridden by WORKER_API_TOKEN env var

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        """Reject insecure defaults in non-development environments."""
        if self.environment != "development" and self.worker_api_token == "dev-bypass":
            raise ValueError(
                "WORKER_API_TOKEN must be set in production (cannot use 'dev-bypass' default). "
                "Generate with: openssl rand -hex 32"
            )
        return self

    git_author_name: str = "autoswarm-bot"
    git_author_email: str = "bot@autoswarm.dev"

    # -- Concurrency / Timeouts -----------------------------------------------
    max_concurrent_tasks: int = 3
    worktree_stale_hours: int = 24
    approval_timeout: int = 300
    # Redis XREAD block timeout (ms). Tuned to balance shutdown
    # responsiveness vs Redis round-trips when the stream is idle.
    redis_block_timeout_ms: int = 5000
    # Per-event emit timeout (seconds) used by the synchronous fallback
    # path in event_emitter._fire when an instrumented LangGraph node
    # emits its node.entered/exited/error events from a sync context.
    event_emit_timeout_seconds: int = 3
    # Cross-tenant kanban overdue-notification scan cadence. Set to 0 to disable.
    kanban_overdue_scan_interval_seconds: int = 300

    # -- Learning / Memory ----------------------------------------------------
    memory_persist_dir: str = "/tmp/autoswarm-memory"
    bandit_persist_path: str = "/tmp/autoswarm-bandit.json"

    # -- AI Inference ---------------------------------------------------------
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    deepinfra_api_key: str | None = None
    siliconflow_api_key: str | None = None
    moonshot_api_key: str | None = None
    groq_api_key: str | None = None
    mistral_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "claude-sonnet-4-6"
    inference_sensitivity: str = "internal"
    org_config_path: str = "~/.autoswarm/org-config.yaml"

    model_config = {
        "env_file": (str(_PROJECT_ROOT / ".env"), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _validate_config(self) -> Settings:
        """Validate configuration values and warn about missing API keys."""
        api_keys = [
            self.anthropic_api_key,
            self.openai_api_key,
            self.openrouter_api_key,
            self.together_api_key,
            self.fireworks_api_key,
            self.deepinfra_api_key,
            self.siliconflow_api_key,
            self.moonshot_api_key,
            self.groq_api_key,
            self.mistral_api_key,
        ]
        if not any(api_keys):
            warnings.warn(
                "No inference API keys configured. Workers will fall back to static logic.",
                stacklevel=2,
            )

        if not self.redis_url.startswith("redis"):
            raise ValueError(
                f"REDIS_URL must start with 'redis://' or 'rediss://', "
                f"got: {self.redis_url[:20]}..."
            )

        if not self.nexus_api_url.startswith("http"):
            raise ValueError(
                f"NEXUS_API_URL must start with 'http://' or 'https://', "
                f"got: {self.nexus_api_url[:20]}..."
            )

        return self


def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
