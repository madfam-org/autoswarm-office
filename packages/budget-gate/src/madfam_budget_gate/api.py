"""Tiny FastAPI router for ops introspection.

Provides three read-only endpoints:

  - ``GET /budget-gate/health``
  - ``GET /budget-gate/status?org_id=&agent_id=&tag=``
  - ``GET /budget-gate/cap?org_id=&agent_id=&tag=``

The router is **read-only on purpose** — cap mutation should go
through ops tooling that emits an audit trail, not through a casual
HTTP handler.

Usage::

    from fastapi import FastAPI
    from madfam_budget_gate import BudgetGate, build_router

    app = FastAPI()
    gate = BudgetGate.from_env()
    app.include_router(build_router(gate))

The ``fastapi`` extra must be installed for this module
(``pip install madfam-budget-gate[fastapi]``).
"""

from __future__ import annotations

from typing import Any

from .gate import BudgetGate
from .scope import BudgetScope

_FASTAPI_AVAILABLE: bool
try:
    from fastapi import APIRouter, HTTPException, Query

    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — only triggered when extra is missing
    _FASTAPI_AVAILABLE = False


def build_router(gate: BudgetGate, *, prefix: str = "/budget-gate") -> Any:
    """Return a FastAPI ``APIRouter`` exposing the gate's introspection API.

    Raises ``RuntimeError`` if FastAPI isn't installed.
    """
    if not _FASTAPI_AVAILABLE:
        raise RuntimeError(
            "FastAPI is not installed; add the 'fastapi' extra "
            "(pip install madfam-budget-gate[fastapi])."
        )

    router = APIRouter(prefix=prefix, tags=["budget-gate"])

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return await gate.health()

    @router.get("/status")
    async def status(
        org_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        tag: str | None = Query(default=None),
    ) -> dict[str, Any]:
        scope = BudgetScope(org_id=org_id, agent_id=agent_id, tag=tag)
        return await gate.status(scope)

    @router.get("/cap")
    async def cap(
        org_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        tag: str | None = Query(default=None),
    ) -> dict[str, Any]:
        scope = BudgetScope(org_id=org_id, agent_id=agent_id, tag=tag)
        cfg = await gate._store.read_cap(scope)  # noqa: SLF001 — intentional ops read
        if cfg is None:
            raise HTTPException(status_code=404, detail="no override for this scope")
        return {
            "scope": {"org_id": scope.org_id, "agent_id": scope.agent_id, "tag": scope.tag},
            "daily_usd": cfg.daily_usd,
            "monthly_usd": cfg.monthly_usd,
            "daily_tokens": cfg.daily_tokens,
            "monthly_tokens": cfg.monthly_tokens,
            "soft_warn_threshold": cfg.soft_warn_threshold,
        }

    return router
