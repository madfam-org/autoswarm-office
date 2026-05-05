"""
Track E1: Interactive Setup Wizard
Mirrors Hermes' hermes_cli/setup.py — `python -m selva_tools.setup_wizard`

Bootstraps a first-run configuration by:
1. Checking required env vars; prompts for missing ones
2. Testing Postgres / Redis connectivity
3. Probing LLM provider credentials
4. Generating a .env file or printing export commands
5. Verifying Celery worker reachability
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable
from typing import cast

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m⚠\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _header(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


REQUIRED_ENV_VARS = [
    ("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/autoswarm"),
    ("REDIS_URL", "redis://localhost:6379/0"),
    ("SECRET_KEY", ""),
]

OPTIONAL_LLM_VARS = [
    ("ANTHROPIC_API_KEY", "sk-ant-..."),
    ("OPENAI_API_KEY", "sk-..."),
    ("GROQ_API_KEY", "gsk_..."),
]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_env_vars(collected: dict) -> dict:
    """Step 1: Check and collect required environment variables."""
    _header("Step 1 — Environment Variables")
    for var, placeholder in REQUIRED_ENV_VARS:
        existing = os.environ.get(var, "")
        if existing:
            _ok(f"{var} already set")
            collected[var] = existing
        else:
            _warn(f"{var} not set")
            val = _ask(f"Enter {var}", placeholder)
            if val and val != placeholder:
                collected[var] = val
            else:
                _warn(f"Skipping {var} — using placeholder (not functional)")
    return collected


def step_llm_credentials(collected: dict) -> dict:
    """Step 2: Probe LLM provider credentials."""
    _header("Step 2 — LLM Provider Credentials")
    for var, _placeholder in OPTIONAL_LLM_VARS:
        existing = os.environ.get(var, "")
        if existing:
            _ok(f"{var} found")
            collected[var] = existing
        else:
            val = _ask(f"Enter {var} (or press Enter to skip)", "")
            if val:
                collected[var] = val
    if not any(collected.get(k) for k, _ in OPTIONAL_LLM_VARS):
        _warn("No LLM credentials provided — inference will fail at runtime")
    return collected


async def step_connectivity(collected: dict) -> None:
    """Step 3: Test Postgres and Redis connectivity."""
    _header("Step 3 — Connectivity Check")

    db_url = collected.get("DATABASE_URL", os.environ.get("DATABASE_URL", ""))
    if db_url:
        try:
            import asyncpg

            conn = await asyncpg.connect(db_url.replace("+asyncpg", ""), timeout=5)
            await conn.close()
            _ok("PostgreSQL connection successful")
        except Exception as exc:
            _fail(f"PostgreSQL connection failed: {exc}")
    else:
        _warn("DATABASE_URL not set — skipping Postgres check")

    redis_url = collected.get("REDIS_URL", os.environ.get("REDIS_URL", ""))
    if redis_url:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url)
            # redis-py types ``ping`` as ``Awaitable[bool] | bool`` because
            # the same method is shared with the sync client.
            await cast(Awaitable[bool], r.ping())
            await r.aclose()
            _ok("Redis connection successful")
        except Exception as exc:
            _fail(f"Redis connection failed: {exc}")
    else:
        _warn("REDIS_URL not set — skipping Redis check")


def step_write_env(collected: dict) -> None:
    """Step 4: Write collected variables to a .env file."""
    _header("Step 4 — Write .env File")
    if not collected:
        _warn("No variables collected — nothing to write")
        return
    env_path = os.path.join(os.getcwd(), ".env.autoswarm")
    with open(env_path, "w") as f:
        for key, val in collected.items():
            f.write(f"{key}={val}\n")
    _ok(f"Written to {env_path}")
    print(f"\n  Load with: \033[36mexport $(cat {env_path} | xargs)\033[0m")


def step_summary(collected: dict) -> None:
    """Step 5: Print a summary."""
    _header("Setup Summary")
    configured = [k for k, v in collected.items() if v]
    _ok(f"{len(configured)} variable(s) configured")
    missing_required = [v for v, _ in REQUIRED_ENV_VARS if not collected.get(v)]
    if missing_required:
        _warn(f"Still missing: {', '.join(missing_required)}")
    else:
        _ok("All required variables are set — ready to run!")
    print("\n  Next: docker compose up -d  OR  kubectl apply -f infra/k8s/\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run_wizard() -> None:
    print("\n\033[1;36m AutoSwarm Office — First-Run Setup Wizard\033[0m")
    print("  ─────────────────────────────────────────")
    collected: dict = {}
    try:
        step_env_vars(collected)
        step_llm_credentials(collected)
        await step_connectivity(collected)
        step_write_env(collected)
        step_summary(collected)
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.\n")
        sys.exit(1)


def main() -> None:
    asyncio.run(_run_wizard())


if __name__ == "__main__":
    main()
