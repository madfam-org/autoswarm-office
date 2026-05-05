"""Budget scope identifiers.

A :class:`BudgetScope` is the unit of cap enforcement.  Scopes form a
small hierarchy:

  - ``BudgetScope()`` (no fields set) → the **global** scope.  Caps here
    apply to every request that does not match a more specific scope.
  - ``BudgetScope(org_id="acme")`` → org-level scope.  Caps cover all
    spend by all agents inside ``acme``.
  - ``BudgetScope(org_id="acme", agent_id="reddit_promo_v1")`` →
    agent-level scope.  Caps apply to one agent inside ``acme``.

Every check enforces the caps of the supplied scope **and** every
parent scope.  An agent-level call therefore consumes against the
agent's daily/monthly caps, the org's daily/monthly caps, and the
global daily/monthly caps simultaneously.  If any of them is exhausted
the call is denied — the most restrictive cap wins.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class BudgetScope:
    """A target for budget enforcement.

    Both fields are optional.  An empty scope (``BudgetScope()``)
    represents the global / catch-all bucket; any field set narrows the
    scope.  The dataclass is frozen + slotted because it doubles as a
    dict key and is allocated on every gate check.
    """

    org_id: str | None = None
    agent_id: str | None = None
    # Free-form tag for niche use-cases (campaign id, tenant tier, etc.)
    # Kept tiny on purpose — anything richer should live in metadata
    # outside the gate so the cap-resolution logic stays predictable.
    tag: str | None = None

    def hash_key(self) -> str:
        """Return a short, stable identifier suitable for Redis keys.

        Uses SHA-1 of the canonical ``org|agent|tag`` triple — short
        enough not to bloat Redis keys, collision-resistant in
        practice for this use-case (worst case = two scopes share a
        cap budget, which fails safely).
        """
        canonical = f"{self.org_id or ''}|{self.agent_id or ''}|{self.tag or ''}"
        if canonical == "||":
            return "global"
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324
        return digest[:16]

    @property
    def is_global(self) -> bool:
        return self.org_id is None and self.agent_id is None and self.tag is None

    def parents(self) -> list[BudgetScope]:
        """Return the chain of less-specific scopes that also apply.

        Order: most specific → least specific (excluding ``self``).
        ``BudgetScope(org_id="acme", agent_id="x").parents()`` returns
        ``[BudgetScope(org_id="acme"), BudgetScope()]``.

        Example::

            >>> BudgetScope(org_id="acme", agent_id="x").parents()
            [BudgetScope(org_id='acme', agent_id=None, tag=None),
             BudgetScope(org_id=None, agent_id=None, tag=None)]
        """
        result: list[BudgetScope] = []
        if self.agent_id is not None and self.org_id is not None:
            result.append(BudgetScope(org_id=self.org_id))
        if not self.is_global and self.org_id is None:
            # Agent-only or tag-only scope — no org parent, jump to global.
            pass
        elif self.agent_id is not None and self.org_id is None:
            pass
        result.append(BudgetScope())
        return result

    def chain(self) -> list[BudgetScope]:
        """Return ``[self, *self.parents()]`` — the full enforcement chain."""
        return [self, *self.parents()]


@dataclass(frozen=True, slots=True)
class CapConfig:
    """Per-scope cap configuration.

    Fields are optional; ``None`` means "fall through to a less
    specific scope (or the env default)".  This lets ops set, e.g., a
    global default daily USD cap and override it only for a specific
    org without re-stating every field.
    """

    daily_usd: float | None = None
    monthly_usd: float | None = None
    daily_tokens: int | None = None
    monthly_tokens: int | None = None
    # Soft-warn fires at this fraction of any cap; default 0.8.
    soft_warn_threshold: float = 0.8


@dataclass(frozen=True, slots=True)
class ResolvedCaps:
    """A fully resolved set of caps for a check.

    Always populated (no ``None`` values) — every field falls through
    to env defaults when no explicit override applies.
    """

    daily_usd: float
    monthly_usd: float
    daily_tokens: int
    monthly_tokens: int
    soft_warn_threshold: float


def _first_non_null(values: Iterable[float | int | None]) -> float | int | None:
    for v in values:
        if v is not None:
            return v
    return None


def resolve_caps(
    scope: BudgetScope,
    *,
    overrides: dict[BudgetScope, CapConfig],
    env_defaults: ResolvedCaps,
) -> ResolvedCaps:
    """Resolve effective caps for ``scope`` walking the parent chain.

    Resolution order: ``scope`` → org parent → global → env defaults.
    The first explicit value wins per field.
    """
    chain_configs: list[CapConfig] = [
        overrides[s] for s in scope.chain() if s in overrides
    ]

    daily_usd = _first_non_null(c.daily_usd for c in chain_configs)
    monthly_usd = _first_non_null(c.monthly_usd for c in chain_configs)
    daily_tokens = _first_non_null(c.daily_tokens for c in chain_configs)
    monthly_tokens = _first_non_null(c.monthly_tokens for c in chain_configs)
    # soft_warn_threshold: take the most-specific override; env default if none.
    threshold = next(
        (c.soft_warn_threshold for c in chain_configs if c is not None),
        env_defaults.soft_warn_threshold,
    )

    return ResolvedCaps(
        daily_usd=float(daily_usd) if daily_usd is not None else env_defaults.daily_usd,
        monthly_usd=float(monthly_usd)
        if monthly_usd is not None
        else env_defaults.monthly_usd,
        daily_tokens=int(daily_tokens)
        if daily_tokens is not None
        else env_defaults.daily_tokens,
        monthly_tokens=int(monthly_tokens)
        if monthly_tokens is not None
        else env_defaults.monthly_tokens,
        soft_warn_threshold=threshold,
    )


# unused import guard for type-checkers
_ = field
