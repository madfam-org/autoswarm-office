"""Org-level configuration for inference routing and agent personnel.

Loads ``~/.selva/org-config.yaml`` (or a custom path) and provides
typed models for provider registration, task-type model assignments,
and agent templates.  All API keys are referenced by *env var name*,
never stored as plaintext.
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".selva" / "org-config.yaml"


class TaskType(StrEnum):
    """Categories of LLM work — the router picks the best model per type."""

    PLANNING = "planning"
    CODING = "coding"
    FAST_CODING = "fast_coding"
    REVIEW = "review"
    RESEARCH = "research"
    CRM = "crm"
    SUPPORT = "support"
    VISION = "vision"
    EMBEDDING = "embedding"


class ModelAssignment(BaseModel):
    """Maps a task type to a specific provider + model."""

    provider: str
    model: str
    max_tokens: int = 4096
    temperature: float = 0.7


class ProviderConfig(BaseModel):
    """Connection details for an OpenAI-compatible provider."""

    base_url: str
    api_key_env: str
    vision: bool = True
    timeout: float = 120.0


class AgentTemplate(BaseModel):
    """Declarative agent definition for seeding."""

    name: str
    role: str
    level: int = 1
    department_slug: str
    skill_ids: list[str] = []


class ServiceConfig(BaseModel):
    """External service account details for the org."""

    provider: str
    service_type: str  # email, billing, llm, crm, auth, infrastructure, devops
    api_key_env: str  # env var name (never plaintext)
    plan: str = ""  # pro, free, enterprise, pay_as_you_go, self_hosted
    plan_details: str = ""
    payment_method: str = ""  # credit_card, invoice, none
    capacity: dict[str, Any] = {}
    consumption_tracking: bool = False
    status: str = "active"  # active, setup, disabled, pending_key
    notes: str = ""


class OrgConfig(BaseModel):
    """Top-level org configuration loaded from YAML."""

    providers: dict[str, ProviderConfig] = {}
    model_assignments: dict[TaskType, ModelAssignment] = {}
    cloud_priority: list[str] | None = None
    cheapest_priority: list[str] | None = None
    agents: list[AgentTemplate] = []
    services: dict[str, ServiceConfig] = {}
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"


def _resolve_api_key(env_var_name: str) -> str | None:
    """Resolve an API key from an environment variable name."""
    return os.environ.get(env_var_name)


def _parse_yaml(raw: dict[str, Any]) -> OrgConfig:
    """Parse a raw YAML dict into an OrgConfig, handling TaskType key conversion."""
    # Convert string task-type keys to TaskType enums
    if "model_assignments" in raw and isinstance(raw["model_assignments"], dict):
        converted: dict[TaskType, Any] = {}
        for key, value in raw["model_assignments"].items():
            try:
                converted[TaskType(key)] = value
            except ValueError:
                logger.warning("Unknown task type in org config: %s", key)
        raw["model_assignments"] = converted
    return OrgConfig(**raw)


@lru_cache(maxsize=1)
def load_org_config(path: Path | None = None) -> OrgConfig:
    """Load org config from YAML, returning defaults if the file is missing.

    The result is cached per process via ``@lru_cache``.
    """
    config_path = path or _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.debug("No org config at %s — using defaults", config_path)
        return OrgConfig()

    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text()) or {}
        config = _parse_yaml(raw)
        logger.info(
            "Loaded org config from %s (%d providers, %d assignments)",
            config_path,
            len(config.providers),
            len(config.model_assignments),
        )
        return config
    except ImportError:
        logger.warning("PyYAML not installed — cannot load org config; using defaults")
        return OrgConfig()
    except Exception:
        logger.warning(
            "Failed to parse org config at %s — using defaults", config_path, exc_info=True
        )
        return OrgConfig()
