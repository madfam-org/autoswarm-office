"""Regression tests for the worker-token org-scoping refactor (cfea6a6).

Pre-fix behaviour: every worker-token call to nexus-api resolved to the
hardcoded ``org_id="madfam-default"`` (auth.py:144). This defeated:
  - the voice-mode/consent gate (always read MADFAM's voice mode)
  - per-tenant RLS scoping (all worker writes attributed to one tenant)
  - the audience filter (all callers looked the same)

Post-fix behaviour:
  - Worker tokens MUST send ``X-Selva-Tenant-Org: <tenant>`` to
    declare their tenant scope.
  - Calls without the header resolve to ``org_id="platform"`` so
    cross-tenant maintenance ops can still be served behind a
    ``service`` role check.
  - The literal string ``madfam-default`` is no longer returned.
  - The dev-bypass token is rejected outright in production.

These tests pin the new behaviour so the regression cannot silently
return.

We bypass the heavy ``Settings`` constructor (which enforces
production-config invariants) by passing a ``MagicMock(spec=Settings)``
to ``get_current_user``. This isolates the auth-branch logic from
configuration validation noise.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from nexus_api import auth as _auth_mod
from nexus_api.config import Settings


def _make_request(headers: dict[str, str] | None = None) -> MagicMock:
    """Build a minimal Request stub exposing only ``headers``."""
    req = MagicMock()
    req.headers = headers or {}
    return req


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _settings(
    *,
    environment: str = "staging",
    dev_auth_bypass: bool = False,
    worker_api_token: str = "test-secret",
) -> MagicMock:
    """Build a Settings stub with only the attributes auth.py reads."""
    s = MagicMock(spec=Settings)
    s.environment = environment
    s.dev_auth_bypass = dev_auth_bypass
    s.worker_api_token = worker_api_token
    return s


@pytest.mark.asyncio
class TestWorkerTokenOrgScoping:
    """Worker token MUST honour X-Selva-Tenant-Org and never return madfam-default."""

    async def test_worker_token_with_tenant_header_returns_correct_org(self) -> None:
        """Header value populates user['org_id']."""
        request = _make_request({"X-Selva-Tenant-Org": "org-abc-123"})

        user = await _auth_mod.get_current_user(
            request=request,
            credentials=_creds("test-secret"),
            settings=_settings(),
        )

        assert user["org_id"] == "org-abc-123"
        assert "service" in user["roles"]
        assert "worker" in user["roles"]

    async def test_worker_token_without_tenant_header_returns_platform_org(self) -> None:
        """Missing header falls back to ``platform`` (not madfam-default)."""
        request = _make_request({})

        user = await _auth_mod.get_current_user(
            request=request,
            credentials=_creds("test-secret"),
            settings=_settings(),
        )

        assert user["org_id"] == "platform"

    async def test_worker_token_does_not_resolve_to_madfam_default(self) -> None:
        """Regression sentinel: the legacy hardcoded value MUST never be returned.

        This is the original bug — every worker call was attributed to
        ``madfam-default``. If anyone re-introduces the literal we want
        a loud failure.
        """
        # Test both code paths: header present and absent.
        for headers in ({}, {"X-Selva-Tenant-Org": "some-real-org"}):
            request = _make_request(headers)
            user = await _auth_mod.get_current_user(
                request=request,
                credentials=_creds("test-secret"),
                settings=_settings(),
            )
            assert user["org_id"] != "madfam-default", (
                f"Worker token resolved to legacy madfam-default "
                f"with headers={headers}; the org-scoping fix has regressed."
            )

    async def test_worker_token_strips_whitespace_in_header(self) -> None:
        """Whitespace-only header value collapses to platform fallback."""
        request = _make_request({"X-Selva-Tenant-Org": "   "})

        user = await _auth_mod.get_current_user(
            request=request,
            credentials=_creds("test-secret"),
            settings=_settings(),
        )

        assert user["org_id"] == "platform"


@pytest.mark.asyncio
class TestDevBypassProductionRejection:
    """The dev-bypass token MUST be rejected in production environments."""

    async def test_dev_bypass_token_rejected_in_production(self) -> None:
        """``Authorization: Bearer dev-bypass`` returns 401 when env=production.

        Pre-fix this would have been silently accepted because the dev
        bypass branch only checked ``dev_auth_bypass`` flag.
        Post-fix: an explicit production check rejects the literal token.
        """
        request = _make_request({})

        with pytest.raises(HTTPException) as exc_info:
            await _auth_mod.get_current_user(
                request=request,
                credentials=_creds("dev-bypass"),
                settings=_settings(
                    environment="production",
                    worker_api_token="real-production-token",
                ),
            )

        assert exc_info.value.status_code == 401
        assert "production" in exc_info.value.detail.lower()


@pytest.mark.asyncio
class TestWorkerTokenAlsoSetsRLSContext:
    """Secondary fix: the worker branch now calls org_id_var.set().

    Pre-fix the worker code path silently never set the context var,
    so RLS-aware downstream code saw the previous request's org or
    raised. The fix calls ``org_id_var.set(tenant_org)`` on the worker
    branch as well.
    """

    async def test_worker_branch_sets_org_id_var(self) -> None:
        from nexus_api.middleware.security import org_id_var

        # Reset the context var to a sentinel so we can detect the assignment.
        token = org_id_var.set("__sentinel__")
        try:
            request = _make_request({"X-Selva-Tenant-Org": "org-xyz"})
            await _auth_mod.get_current_user(
                request=request,
                credentials=_creds("test-secret"),
                settings=_settings(),
            )
            assert org_id_var.get() == "org-xyz", (
                "Worker branch must set org_id_var for downstream RLS middleware"
            )
        finally:
            org_id_var.reset(token)
