"""Per-tenant inference policy — sensitivity floor, caps, and rate limits.

The gateway's org-config (``org-config.yaml``) is *ecosystem-wide*: it
says which provider serves which task type. This module adds the missing
*per-tenant* layer: what a given ``X-Selva-Tenant-Org`` is allowed and
budgeted to do.

Why it exists
-------------
Before this, a tenant handling regulated data (Crea Tu Mundo's MAP holds
clinical notes about minors) depended entirely on its own client code
sending ``X-Sensitivity: restricted`` on every call. A dropped header, a
proxy that strips it, or a new surface that forgets it, and the request
silently degraded to ``public`` and went to a cloud vendor. The header is
now mandatory (the proxy rejects a request without it), and on top of that
a tenant can declare a **sensitivity floor**: the level its data can never
fall below, enforced server-side regardless of what the client sends.

Design notes
------------
- **Declarative, not code.** Policies load from YAML (``TENANT_POLICY_PATH``,
  shipped as a ConfigMap) so onboarding a regulated tenant is a config
  change reviewed in Git, not a deploy of new logic.
- **Absent policy = no extra restriction.** A tenant with no entry keeps
  today's behaviour exactly. This module only ever *tightens*.
- **The floor raises, never lowers.** A tenant with floor ``restricted``
  that sends ``public`` is served as ``restricted``. A tenant with floor
  ``internal`` that sends ``restricted`` is served as ``restricted`` —
  the caller may always ask for MORE protection than its floor.
- **Rate limiting is in-process** (per pod, fixed window). It is a blunt
  abuse/runaway brake, not a billing meter; the durable USD attribution is
  the ``inference_usage_ledger``. With N replicas the effective limit is
  N × the configured value — state that when you set the number.

No prompt or completion text ever reaches this module.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .types import Sensitivity

logger = logging.getLogger(__name__)

DEFAULT_TENANT_POLICY_PATH = "/etc/selva/tenant-policies.yaml"
ENV_TENANT_POLICY_PATH = "TENANT_POLICY_PATH"

# Ordered weakest → strongest. ``max()`` over this order is how the floor
# is applied, so a caller asking for MORE protection than its floor keeps
# the stronger level.
_SENSITIVITY_ORDER: dict[Sensitivity, int] = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.INTERNAL: 1,
    Sensitivity.CONFIDENTIAL: 2,
    Sensitivity.RESTRICTED: 3,
}


def sensitivity_rank(level: Sensitivity) -> int:
    """Return the ordinal strength of a sensitivity level (higher = stricter)."""
    return _SENSITIVITY_ORDER[level]


def apply_floor(requested: Sensitivity, floor: Sensitivity | None) -> Sensitivity:
    """Return the stricter of ``requested`` and ``floor``.

    ``floor`` of ``None`` (no tenant policy) returns ``requested`` unchanged.
    """
    if floor is None:
        return requested
    return requested if sensitivity_rank(requested) >= sensitivity_rank(floor) else floor


class TenantPolicy(BaseModel):
    """Server-side policy for one ``X-Selva-Tenant-Org``.

    Every field is optional; an omitted field means "no tenant-specific
    restriction, use the gateway default".
    """

    org_id: str
    #: Human name, for operator logs and the runbook. Never sent to a provider.
    display_name: str = ""
    #: The weakest sensitivity this tenant's data may ever be served at.
    #: A request that asks for less is RAISED to this level, not rejected.
    sensitivity_floor: Sensitivity | None = None
    #: Task types this tenant is allowed to send. Empty = all allowed.
    #: A denied task type is a 400, not a silent downgrade.
    allowed_task_types: list[str] = Field(default_factory=list)
    #: Hard ceiling on ``max_tokens`` for this tenant's requests.
    max_tokens_cap: int | None = None
    #: Server-side deadline for one completion, in seconds.
    request_timeout_seconds: float | None = None
    #: In-process fixed-window request cap. ``None`` = unlimited.
    rate_limit_per_minute: int | None = None
    #: Informational daily USD budget. Recorded for attribution and surfaced
    #: to operators; enforcement lives in the budget gate when it is armed.
    daily_usd_budget: float | None = None
    #: Free-text note carried into operator logs (contract reference, owner).
    notes: str = ""


class TenantPolicyBook(BaseModel):
    """The full set of tenant policies plus gateway-wide defaults."""

    #: Applied to every tenant that has no explicit policy of its own.
    default_request_timeout_seconds: float = 45.0
    default_max_tokens_cap: int = 4096
    tenants: dict[str, TenantPolicy] = Field(default_factory=dict)

    def for_org(self, org_id: str | None) -> TenantPolicy | None:
        """Return the policy for ``org_id``, or ``None`` when unconfigured."""
        if not org_id:
            return None
        return self.tenants.get(org_id)

    def timeout_for(self, policy: TenantPolicy | None) -> float:
        """Resolve the effective request timeout for a (possibly absent) policy."""
        if policy is not None and policy.request_timeout_seconds is not None:
            return policy.request_timeout_seconds
        return self.default_request_timeout_seconds

    def max_tokens_for(self, policy: TenantPolicy | None) -> int:
        """Resolve the effective ``max_tokens`` ceiling."""
        if policy is not None and policy.max_tokens_cap is not None:
            return policy.max_tokens_cap
        return self.default_max_tokens_cap


def _parse_book(raw: dict[str, Any]) -> TenantPolicyBook:
    """Build a :class:`TenantPolicyBook` from a raw YAML mapping.

    Tenants may be given either as a mapping keyed by org id or as a list
    of objects each carrying ``org_id`` — both shapes read naturally in a
    ConfigMap, so both are accepted.
    """
    tenants_raw = raw.get("tenants") or {}
    tenants: dict[str, TenantPolicy] = {}

    if isinstance(tenants_raw, dict):
        items = [
            {**(value or {}), "org_id": (value or {}).get("org_id", key)}
            for key, value in tenants_raw.items()
        ]
    elif isinstance(tenants_raw, list):
        items = [item for item in tenants_raw if isinstance(item, dict)]
    else:
        logger.warning("tenant policy: 'tenants' must be a mapping or a list; ignoring")
        items = []

    for item in items:
        try:
            policy = TenantPolicy(**item)
        except Exception:
            logger.warning(
                "tenant policy: skipping malformed entry for %s",
                item.get("org_id", "<unknown>"),
                exc_info=True,
            )
            continue
        tenants[policy.org_id] = policy

    book_kwargs: dict[str, Any] = {"tenants": tenants}
    for key in ("default_request_timeout_seconds", "default_max_tokens_cap"):
        if key in raw and raw[key] is not None:
            book_kwargs[key] = raw[key]
    return TenantPolicyBook(**book_kwargs)


@lru_cache(maxsize=1)
def load_tenant_policies(path: Path | None = None) -> TenantPolicyBook:
    """Load the tenant policy book from YAML, cached per process.

    A missing file is normal (most deployments have no regulated tenant)
    and yields an empty book with gateway defaults. A malformed file is a
    LOUD warning and also yields the empty book — it must never silently
    remove a floor that an operator believes is in force, so the runbook
    tells operators to verify the loaded tenant list at startup.
    """
    config_path = path or Path(
        os.environ.get(ENV_TENANT_POLICY_PATH, DEFAULT_TENANT_POLICY_PATH)
    ).expanduser()

    if not config_path.exists():
        logger.info(
            "tenant policy: no policy file at %s — no per-tenant floors in force",
            config_path,
        )
        return TenantPolicyBook()

    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text()) or {}
        book = _parse_book(raw)
        logger.info(
            "tenant policy: loaded %d tenant(s) from %s: %s",
            len(book.tenants),
            config_path,
            ", ".join(sorted(book.tenants)) or "(none)",
        )
        return book
    except ImportError:
        logger.warning("tenant policy: PyYAML not installed — no per-tenant floors in force")
        return TenantPolicyBook()
    except Exception:
        logger.error(
            "tenant policy: FAILED to parse %s — no per-tenant floors in force. "
            "Fix the file and restart; do not assume a floor is applied.",
            config_path,
            exc_info=True,
        )
        return TenantPolicyBook()


class InProcessRateLimiter:
    """Fixed-window per-key request limiter, in memory.

    Deliberately dependency-free: the inference gateway does not run Redis
    (see ``apps/inference-gateway/inference_gateway/main.py``), and adding
    one to enforce a tenant brake would put the LLM chokepoint's uptime
    behind a cache. With N replicas the effective ceiling is N × ``limit``;
    set the number knowing that, and treat it as a runaway brake rather
    than a billing meter.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int | None) -> tuple[bool, int]:
        """Record a hit for ``key``; return ``(allowed, retry_after_seconds)``.

        ``limit`` of ``None`` or a non-positive value means unlimited: the
        hit is not even recorded, so an unlimited tenant costs nothing.
        """
        if limit is None or limit <= 0:
            return True, 0

        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(self._window - (now - bucket[0])) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        """Drop all counters — used by tests."""
        with self._lock:
            self._hits.clear()
