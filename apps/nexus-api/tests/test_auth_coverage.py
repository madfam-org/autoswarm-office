"""Phase 2 critical-path coverage for ``nexus_api.auth``.

These tests fill gaps in the JWT-verify, JWKS-fetch, role-checker, and
production-rejection branches of ``auth.py``. They complement the
existing ``test_auth_worker_token_scoping.py`` (worker token branch) by
exercising the user-facing JWT branches plus the small
``require_role`` / ``require_roles`` / ``require_non_guest`` /
``require_non_demo`` factories.

Strategy: bypass the heavy ``Settings`` constructor with a
``MagicMock(spec=Settings)`` and stub out the JWKS HTTP fetch so we
don't hit the network. JWT-verify branches are tested by patching
``jose.jwt.decode`` / ``get_unverified_header`` (the third-party
library is treated as a black box; we verify our routing only).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError

from nexus_api import auth as _auth_mod
from nexus_api.config import Settings


def _make_request(headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    return req


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _settings(
    *,
    environment: str = "staging",
    dev_auth_bypass: bool = False,
    worker_api_token: str = "wt-secret",
    janua_issuer_url: str = "https://janua.example.com",
    janua_client_id: str = "client-xyz",
) -> MagicMock:
    s = MagicMock(spec=Settings)
    s.environment = environment
    s.dev_auth_bypass = dev_auth_bypass
    s.worker_api_token = worker_api_token
    s.janua_issuer_url = janua_issuer_url
    s.janua_client_id = janua_client_id
    return s


# ---------------------------------------------------------------------------
# Module-level cache: clear before each test to keep them hermetic.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_jwks_cache() -> None:
    _auth_mod._jwks_cache = None
    _auth_mod._jwks_cache_time = None


# ---------------------------------------------------------------------------
# _get_signing_key
# ---------------------------------------------------------------------------


class TestGetSigningKey:
    def test_returns_matching_key_by_kid(self) -> None:
        jwks = {
            "keys": [
                {"kid": "key-1", "n": "..."},
                {"kid": "key-2", "n": "..."},
            ]
        }
        with patch.object(_auth_mod.jwt, "get_unverified_header", return_value={"kid": "key-2"}):
            result = _auth_mod._get_signing_key(jwks, "any-token")
        assert result["kid"] == "key-2"

    def test_raises_when_kid_missing(self) -> None:
        with (
            patch.object(_auth_mod.jwt, "get_unverified_header", return_value={}),
            pytest.raises(JWTError, match="missing 'kid'"),
        ):
            _auth_mod._get_signing_key({"keys": []}, "tok")

    def test_raises_when_kid_not_found(self) -> None:
        jwks = {"keys": [{"kid": "other"}]}
        with (
            patch.object(_auth_mod.jwt, "get_unverified_header", return_value={"kid": "missing"}),
            pytest.raises(JWTError, match="not found"),
        ):
            _auth_mod._get_signing_key(jwks, "tok")


# ---------------------------------------------------------------------------
# _fetch_jwks (cache + TTL)
# ---------------------------------------------------------------------------


class TestFetchJwks:
    @pytest.mark.asyncio
    async def test_caches_first_fetch(self) -> None:
        """Second call within TTL must reuse the cached value (no extra GET)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"keys": [{"kid": "k1"}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_auth_mod.httpx, "AsyncClient", return_value=mock_client):
            first = await _auth_mod._fetch_jwks("https://issuer.example.com")
            second = await _auth_mod._fetch_jwks("https://issuer.example.com")

        assert first == {"keys": [{"kid": "k1"}]}
        assert second is first  # cached identity reused
        mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# verify_jwt: success + JWTError + httpx.HTTPError branches
# ---------------------------------------------------------------------------


class TestVerifyJwt:
    @pytest.mark.asyncio
    async def test_success_returns_payload(self) -> None:
        with (
            patch.object(
                _auth_mod, "_fetch_jwks", AsyncMock(return_value={"keys": [{"kid": "k"}]})
            ),
            patch.object(_auth_mod, "_get_signing_key", return_value={"kid": "k"}),
            patch.object(
                _auth_mod.jwt,
                "decode",
                return_value={"sub": "u-1", "org_id": "o-1", "roles": ["admin"]},
            ),
        ):
            payload = await _auth_mod.verify_jwt("tok", _settings())
        assert payload["sub"] == "u-1"

    @pytest.mark.asyncio
    async def test_jwt_error_returns_401(self) -> None:
        with (
            patch.object(
                _auth_mod, "_fetch_jwks", AsyncMock(return_value={"keys": [{"kid": "k"}]})
            ),
            patch.object(_auth_mod, "_get_signing_key", return_value={"kid": "k"}),
            patch.object(_auth_mod.jwt, "decode", side_effect=JWTError("expired")),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _auth_mod.verify_jwt("tok", _settings())
        assert exc_info.value.status_code == 401
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.asyncio
    async def test_jwks_fetch_failure_returns_503(self) -> None:
        with (
            patch.object(
                _auth_mod, "_fetch_jwks", AsyncMock(side_effect=httpx.ConnectError("dns fail"))
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _auth_mod.verify_jwt("tok", _settings())
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_settings_default_via_get_settings(self) -> None:
        """When ``settings=None`` the function should resolve via ``get_settings()``.

        This covers the early ``if settings is None`` branch in ``verify_jwt``.
        """
        stub = _settings()
        with (
            patch.object(_auth_mod, "get_settings", return_value=stub),
            patch.object(
                _auth_mod, "_fetch_jwks", AsyncMock(return_value={"keys": [{"kid": "k"}]})
            ),
            patch.object(_auth_mod, "_get_signing_key", return_value={"kid": "k"}),
            patch.object(_auth_mod.jwt, "decode", return_value={"sub": "u"}),
        ):
            payload = await _auth_mod.verify_jwt("tok")
        assert payload["sub"] == "u"


# ---------------------------------------------------------------------------
# get_current_user: dev bypass + JWT branch + worker token branch (covered
# elsewhere). The dev bypass + JWT path complete the coverage.
# ---------------------------------------------------------------------------


class TestGetCurrentUserBranches:
    @pytest.mark.asyncio
    async def test_dev_bypass_returns_synthetic_user(self) -> None:
        request = _make_request({})
        user = await _auth_mod.get_current_user(
            request=request,
            credentials=_creds("anything"),
            settings=_settings(environment="development", dev_auth_bypass=True),
        )
        assert user["sub"] == "dev-user-00000000"
        assert user["org_id"] == "dev-org"
        assert "admin" in user["roles"]

    @pytest.mark.asyncio
    async def test_jwt_branch_sets_org_id_var_from_payload(self) -> None:
        from nexus_api.middleware.security import org_id_var

        request = _make_request({})
        with (
            patch.object(
                _auth_mod,
                "verify_jwt",
                AsyncMock(
                    return_value={
                        "sub": "user-1",
                        "roles": ["tactician"],
                        "org_id": "tenant-42",
                        "email": "user@example.com",
                    }
                ),
            ),
        ):
            token = org_id_var.set("__sentinel__")
            try:
                user = await _auth_mod.get_current_user(
                    request=request,
                    credentials=_creds("real-jwt"),
                    settings=_settings(),
                )
                assert user["org_id"] == "tenant-42"
                assert user["sub"] == "user-1"
                assert org_id_var.get() == "tenant-42"
            finally:
                org_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_jwt_branch_default_org_id_when_missing(self) -> None:
        """JWT without org_id claim defaults to 'default' (covers the .get(..., 'default'))."""
        from nexus_api.middleware.security import org_id_var

        request = _make_request({})
        with patch.object(
            _auth_mod,
            "verify_jwt",
            AsyncMock(return_value={"sub": "u", "email": "x@y.com"}),
        ):
            token = org_id_var.set("__sentinel__")
            try:
                user = await _auth_mod.get_current_user(
                    request=request,
                    credentials=_creds("jwt"),
                    settings=_settings(),
                )
                assert user["org_id"] is None  # payload had no org_id
                assert org_id_var.get() == "default"
            finally:
                org_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_unset_worker_api_token_falls_through_to_jwt(self) -> None:
        """Empty/dev-bypass worker token must NOT match the worker branch."""
        request = _make_request({})
        with patch.object(
            _auth_mod,
            "verify_jwt",
            AsyncMock(return_value={"sub": "u", "org_id": "o", "roles": []}),
        ):
            user = await _auth_mod.get_current_user(
                request=request,
                credentials=_creds("dev-bypass"),
                settings=_settings(worker_api_token=""),
            )
        # If the worker branch had matched we'd see "service" in roles.
        assert "service" not in user["roles"]


# ---------------------------------------------------------------------------
# require_role / require_roles / require_non_guest / require_non_demo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRoleCheckers:
    async def test_require_role_passes(self) -> None:
        checker = _auth_mod.require_role("admin")
        user = {"sub": "u", "roles": ["admin", "tactician"]}
        assert await checker(user=user) is user

    async def test_require_role_rejects_missing_role(self) -> None:
        checker = _auth_mod.require_role("admin")
        with pytest.raises(HTTPException) as exc:
            await checker(user={"sub": "u", "roles": ["tactician"]})
        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail

    async def test_require_role_rejects_missing_roles_list(self) -> None:
        """user dict with no ``roles`` key still rejected."""
        checker = _auth_mod.require_role("admin")
        with pytest.raises(HTTPException):
            await checker(user={"sub": "u"})

    async def test_require_roles_passes_on_any_match(self) -> None:
        checker = _auth_mod.require_roles(["admin", "enterprise-cleanroom"])
        user = {"sub": "u", "roles": ["enterprise-cleanroom"]}
        assert await checker(user=user) is user

    async def test_require_roles_rejects_when_none_match(self) -> None:
        checker = _auth_mod.require_roles(["admin", "enterprise-cleanroom"])
        with pytest.raises(HTTPException) as exc:
            await checker(user={"sub": "u", "roles": ["tactician"]})
        assert exc.value.status_code == 403

    async def test_require_non_guest_rejects_guest(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await _auth_mod.require_non_guest(user={"sub": "u", "roles": ["guest"]})
        assert exc.value.status_code == 403
        assert "guest" in exc.value.detail.lower()

    async def test_require_non_guest_passes_for_non_guest(self) -> None:
        out = await _auth_mod.require_non_guest(user={"sub": "u", "roles": ["tactician"]})
        assert out["sub"] == "u"

    async def test_require_non_demo_rejects_demo(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await _auth_mod.require_non_demo(user={"sub": "u", "roles": ["demo"]})
        assert exc.value.status_code == 403
        assert "demo" in exc.value.detail.lower()

    async def test_require_non_demo_passes_for_real_user(self) -> None:
        out = await _auth_mod.require_non_demo(user={"sub": "u", "roles": ["tactician"]})
        assert out["sub"] == "u"
