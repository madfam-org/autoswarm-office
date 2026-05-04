"""Phase 2 critical-path coverage for ``selva_tools.builtins.email_tools``.

Targets the gaps left by ``test_email_voice_mode_gate.py``:

- ``_fetch_voice_mode`` HTTP success/failure/exception branches.
- ``_fetch_tenant_identity`` HTTP success/failure/exception branches.
- ``_resolve_agent_identity`` allow-list resolver edge cases.
- ``_tenant_lookup_headers`` env var resolution.
- ``SendEmailTool`` validation errors (missing to, invalid to, missing
  org_id, missing RESEND_API_KEY, build_identity ValueError, Resend
  HTTP error).
- ``ReadEmailTool`` placeholder error.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from selva_tools.builtins import email_tools

# ---------------------------------------------------------------------------
# _resolve_agent_identity — allow-list resolver
# ---------------------------------------------------------------------------


class TestResolveAgentIdentity:
    def test_known_role_resolves(self) -> None:
        slug, name = email_tools._resolve_agent_identity("sales")
        assert slug == "sales-agent"
        assert "Sales" in name

    def test_unknown_role_falls_back_to_default(self) -> None:
        slug, name = email_tools._resolve_agent_identity("ceo@target.com")
        assert slug == "support-agent"
        assert "Support" in name

    def test_none_falls_back_to_default(self) -> None:
        slug, name = email_tools._resolve_agent_identity(None)
        assert slug == "support-agent"

    def test_uppercase_role_normalized(self) -> None:
        slug, _ = email_tools._resolve_agent_identity("GROWTH")
        assert slug == "growth-agent"

    def test_whitespace_stripped(self) -> None:
        slug, _ = email_tools._resolve_agent_identity("  ops  ")
        assert slug == "ops-agent"


# ---------------------------------------------------------------------------
# _tenant_lookup_headers — auth header construction
# ---------------------------------------------------------------------------


class TestTenantLookupHeaders:
    def test_includes_bearer_and_org_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKER_API_TOKEN", "secret-token")
        h = email_tools._tenant_lookup_headers("org-42")
        assert h["Authorization"] == "Bearer secret-token"
        assert h["X-Selva-Tenant-Org"] == "org-42"
        assert h["X-Org-Id"] == "org-42"

    def test_falls_back_to_dev_bypass_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
        h = email_tools._tenant_lookup_headers("o")
        assert h["Authorization"] == "Bearer dev-bypass"


# ---------------------------------------------------------------------------
# _fetch_voice_mode — HTTP branches
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _Client:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict) -> _Resp:
        return self._resp


@pytest.mark.asyncio
class TestFetchVoiceMode:
    async def test_returns_voice_mode_on_200(self) -> None:
        with patch.object(
            email_tools.httpx,
            "AsyncClient",
            lambda timeout=5.0: _Client(_Resp(200, {"voice_mode": "agent_identified"})),
        ):
            mode = await email_tools._fetch_voice_mode("o-1")
        assert mode == "agent_identified"

    async def test_returns_none_on_200_with_no_voice_mode_field(self) -> None:
        with patch.object(
            email_tools.httpx,
            "AsyncClient",
            lambda timeout=5.0: _Client(_Resp(200, {})),
        ):
            mode = await email_tools._fetch_voice_mode("o-1")
        assert mode is None

    async def test_returns_none_on_non_200(self) -> None:
        with patch.object(
            email_tools.httpx,
            "AsyncClient",
            lambda timeout=5.0: _Client(_Resp(404)),
        ):
            mode = await email_tools._fetch_voice_mode("o-1")
        assert mode is None

    async def test_returns_none_on_exception(self) -> None:
        class _BoomClient:
            async def __aenter__(self) -> _BoomClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def get(self, *args: object, **kwargs: object) -> None:
                raise httpx.ConnectError("dns fail")

        with patch.object(email_tools.httpx, "AsyncClient", lambda timeout=5.0: _BoomClient()):
            mode = await email_tools._fetch_voice_mode("o-1")
        assert mode is None


# ---------------------------------------------------------------------------
# _fetch_tenant_identity — HTTP branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchTenantIdentity:
    async def test_returns_dict_on_200(self) -> None:
        identity = {"user_email": "x@y.io", "user_name": "X", "org_name": "Y"}
        with patch.object(
            email_tools.httpx,
            "AsyncClient",
            lambda timeout=5.0: _Client(_Resp(200, identity)),
        ):
            out = await email_tools._fetch_tenant_identity("o-1")
        assert out == identity

    async def test_returns_none_on_403(self) -> None:
        with patch.object(
            email_tools.httpx,
            "AsyncClient",
            lambda timeout=5.0: _Client(_Resp(403)),
        ):
            assert await email_tools._fetch_tenant_identity("o-1") is None

    async def test_returns_none_on_exception(self) -> None:
        class _BoomClient:
            async def __aenter__(self) -> _BoomClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def get(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("boom")

        with patch.object(email_tools.httpx, "AsyncClient", lambda timeout=5.0: _BoomClient()):
            assert await email_tools._fetch_tenant_identity("o-1") is None


# ---------------------------------------------------------------------------
# SendEmailTool validation branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSendEmailValidation:
    async def test_missing_to_returns_error(self) -> None:
        tool = email_tools.SendEmailTool()
        result = await tool.execute(to="", subject="x", html="x", org_id="o")
        assert result.success is False
        assert "Recipient" in (result.error or "")

    async def test_invalid_email_format(self) -> None:
        tool = email_tools.SendEmailTool()
        result = await tool.execute(to="not-an-email", subject="x", html="x", org_id="o")
        assert result.success is False
        assert "Invalid email" in (result.error or "")

    async def test_missing_org_id(self) -> None:
        tool = email_tools.SendEmailTool()
        result = await tool.execute(to="x@y.io", subject="x", html="x", org_id="")
        assert result.success is False
        assert "org_id" in (result.error or "")

    async def test_missing_resend_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tool = email_tools.SendEmailTool()
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        with (
            patch.object(
                email_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                email_tools,
                "_fetch_tenant_identity",
                AsyncMock(
                    return_value={
                        "user_email": "ada@x.io",
                        "user_name": "Ada",
                        "org_name": "MADFAM",
                    }
                ),
            ),
        ):
            result = await tool.execute(
                to="dest@x.io", subject="hi", html="<p>x</p>", org_id="o"
            )
        assert result.success is False
        assert "RESEND_API_KEY" in (result.error or "")

    async def test_resend_http_error_propagates_as_failure(self) -> None:
        tool = email_tools.SendEmailTool()

        class _BadResp:
            status_code = 500
            text = "internal error body that is fairly long and should be truncated"

            def json(self) -> dict:
                return {}

        class _BadClient:
            async def __aenter__(self) -> _BadClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> _BadResp:
                return _BadResp()

        with (
            patch.object(
                email_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                email_tools,
                "_fetch_tenant_identity",
                AsyncMock(
                    return_value={
                        "user_email": "ada@x.io",
                        "user_name": "Ada",
                        "org_name": "MADFAM",
                    }
                ),
            ),
            patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _BadClient()),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to="dest@x.io", subject="hi", html="<p>x</p>", org_id="o"
            )
        assert result.success is False
        assert "Resend API error" in (result.error or "")
        assert "500" in (result.error or "")

    async def test_post_exception_returns_error(self) -> None:
        tool = email_tools.SendEmailTool()

        class _BoomClient:
            async def __aenter__(self) -> _BoomClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> None:
                raise httpx.ConnectError("dns fail")

        with (
            patch.object(
                email_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                email_tools,
                "_fetch_tenant_identity",
                AsyncMock(
                    return_value={
                        "user_email": "ada@x.io",
                        "user_name": "Ada",
                        "org_name": "MADFAM",
                    }
                ),
            ),
            patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _BoomClient()),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to="dest@x.io", subject="hi", html="<p>x</p>", org_id="o"
            )
        assert result.success is False
        assert "dns fail" in (result.error or "")


# ---------------------------------------------------------------------------
# SendEmailTool — parameters_schema shape
# ---------------------------------------------------------------------------


class TestSendEmailToolSchema:
    def test_schema_omits_sender_identity_kwargs(self) -> None:
        """The LLM must not be able to specify From-header inputs."""
        tool = email_tools.SendEmailTool()
        schema = tool.parameters_schema()
        properties = schema["properties"]
        assert "user_email" not in properties
        assert "user_name" not in properties
        assert "agent_slug" not in properties
        # Required fields are the safe inputs
        assert set(schema["required"]) == {"to", "subject", "html", "org_id"}
        # agent_role is constrained by enum allow-list
        assert "agent_role" in properties
        enum = properties["agent_role"]["enum"]
        assert {"sales", "support", "growth", "ops", "research"} == set(enum)


# ---------------------------------------------------------------------------
# ReadEmailTool — placeholder behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadEmailTool:
    async def test_returns_imap_not_configured_error(self) -> None:
        tool = email_tools.ReadEmailTool()
        result = await tool.execute()
        assert result.success is False
        assert "IMAP" in (result.error or "")

    def test_schema_has_mailbox_and_count_defaults(self) -> None:
        tool = email_tools.ReadEmailTool()
        schema = tool.parameters_schema()
        assert schema["properties"]["mailbox"]["default"] == "INBOX"
        assert schema["properties"]["count"]["default"] == 10
