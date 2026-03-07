"""Multi-tenancy support via org_id extracted from JWT claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends

from .auth import get_current_user


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context resolved from the authenticated user."""

    org_id: str


async def get_tenant(
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> TenantContext:
    """FastAPI dependency that extracts org_id from the authenticated user.

    Falls back to ``"default"`` when the JWT does not contain an ``org_id``
    claim (e.g. legacy tokens or local development).
    """
    return TenantContext(org_id=user.get("org_id") or "default")
