"""Tool-level audience split — platform (MADFAM) vs tenant swarms.

Two-layer defense:

- **Spec-time filter** (primary): ``ToolRegistry.get_specs(audience=...)``
  strips PLATFORM tools when the swarm is tenant-audience. The LLM
  literally can't call what it can't see.
- **Execute-time guard** (belt-and-braces): ``enforce_audience(tool)``
  reads the current audience from a ContextVar and raises
  ``AudienceMismatch`` if a platform tool is invoked in tenant context.

Superset relationship: PLATFORM sees all tools; TENANT sees only
TENANT-tagged tools. No separate SHARED bucket — platform is a superset.

Default for ``BaseTool.audience`` is ``TENANT`` so new tools don't
accidentally reserve themselves to platform. Dangerous tools must be
opted-in to PLATFORM explicitly. In production, enforcement defaults
on and unbound callers fail closed for PLATFORM tools.
"""

from __future__ import annotations

import enum
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Same env var as selva_permissions.audience.AUDIENCE_FILTER_ENABLED_ENV.
# Duplicated here so selva_tools doesn't have to depend on
# selva_permissions — the permissions package already imports from
# selva_tools (via tool_catalog) in principle, so we avoid the
# cross-dep by reading the env directly.
_AUDIENCE_FILTER_ENABLED_ENV = "AUDIENCE_FILTER_ENABLED"


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _falsey(raw: str) -> bool:
    return raw.strip().lower() in ("0", "false", "no", "off")


def _production_environment() -> bool:
    """Best-effort production detection shared by API, workers, and CLIs."""
    for key in ("SELVA_ENV", "APP_ENV", "ENVIRONMENT", "NODE_ENV"):
        if os.environ.get(key, "").strip().lower() == "production":
            return True
    return False


def _enforcement_enabled() -> bool:
    raw = os.environ.get(_AUDIENCE_FILTER_ENABLED_ENV)
    if raw is None:
        return _production_environment()
    if _falsey(raw):
        return False
    return _truthy(raw)


def _fail_closed_unbound() -> bool:
    """Production callers must bind an audience before using platform tools."""
    return _enforcement_enabled()


class Audience(enum.StrEnum):
    """Swarm audience: platform (MADFAM) or tenant (customer orgs)."""

    PLATFORM = "platform"
    TENANT = "tenant"


class AudienceMismatch(RuntimeError):  # noqa: N818 (name is intentional: "mismatch", not an error suffix)
    """Raised when a tool is invoked by a swarm that lacks audience access."""


# Tracks the current swarm's audience during a task execution.
# Workers bind this via ``with_audience(Audience.TENANT)`` at task start;
# tools can assert the binding matches their required audience.
_current_audience: ContextVar[Audience | None] = ContextVar("selva_tool_audience", default=None)


def get_current_audience() -> Audience | None:
    """Return the audience bound for the current task, or None if unbound."""
    return _current_audience.get()


@contextmanager
def with_audience(audience: Audience) -> Iterator[None]:
    """Bind a swarm's audience for the duration of a block.

    Typical use (in a worker at task dispatch time)::

        with with_audience(Audience.TENANT):
            await run_graph(task)
    """
    token = _current_audience.set(audience)
    try:
        yield
    finally:
        _current_audience.reset(token)


def can_access(tool_audience: Audience, swarm_audience: Audience | None) -> bool:
    """True iff a swarm with ``swarm_audience`` may use a tool tagged ``tool_audience``.

    Rules:
    - Platform swarms see everything.
    - Tenant swarms see only TENANT-tagged tools.
    - If the swarm audience is not bound (None), development stays
      permissive for backward compatibility. Production/enforced mode
      fails closed for PLATFORM tools and permits only TENANT tools.
    """
    if swarm_audience is None:
        return tool_audience is Audience.TENANT if _fail_closed_unbound() else True
    if swarm_audience is Audience.PLATFORM:
        return True
    return tool_audience is Audience.TENANT


def enforce_audience(tool_audience: Audience, tool_name: str | None = None) -> None:
    """Raise ``AudienceMismatch`` if the current swarm can't access the tool.

    Tools that want defense-in-depth can call this at the top of
    ``execute()``. The spec-time filter (``get_specs``) is the primary
    gate; this is the belt-and-braces for bugs where the filter
    regresses or a tool is invoked via a non-standard path.

    Shadow mode: when ``AUDIENCE_FILTER_ENABLED`` is NOT truthy, the
    check is observational only — log a structured "would-block" line
    and return. This lets ops verify the production rate of would-be
    blocks before flipping the flag to enforce.
    """
    swarm_audience = get_current_audience()
    if can_access(tool_audience, swarm_audience):
        return
    label = tool_name or "unknown-tool"
    if _enforcement_enabled():
        raise AudienceMismatch(
            f"tool={label} requires audience={tool_audience.value}, "
            f"current swarm audience={swarm_audience.value if swarm_audience else 'unbound'}"
        )
    # Shadow: log + allow.
    logger.warning(
        "audience_shadow_block tool=%s required=%s swarm=%s (permitting — "
        "AUDIENCE_FILTER_ENABLED off)",
        label,
        tool_audience.value,
        swarm_audience.value if swarm_audience else "unbound",
    )
