"""Tests for the X (Twitter) posting capability scaffold.

Focus areas (mirrors ``test_bluesky_tools.py``), with the extra emphasis
this tool ships DARK:

- Feature flag OFF by default → failed ToolResult (never a crash, never a
  fake success) even with credentials absent.
- Flag ON but credentials missing → ToolNotConfiguredError (no placeholder).
- Disclosure footer applied; 280-char limit enforced (PostTooLongError, no
  silent truncation).
- Per-persona credential isolation.
- Registration in ``get_builtin_tools()`` + audience tag (TENANT).
- ``x_promo_v1`` playbook registered with require_approval=True.
- Happy path (mocked client) only reachable when flag ON + creds present.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import x_tools
from selva_tools.builtins.x_tools import (
    DISCLOSURE_FOOTER,
    X_MAX_POST_CHARS,
    X_POST_ENABLED_ENV,
    PostTooLongError,
    ToolNotConfiguredError,
    XPostTool,
    _apply_disclosure_with_limit,
    _is_enabled,
)


@pytest.fixture()
def x_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(X_POST_ENABLED_ENV, "true")


@pytest.fixture()
def x_creds_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provision the full X credential set for the 'default' persona."""
    monkeypatch.setenv("X_API_KEY", "app-key")
    monkeypatch.setenv("X_API_SECRET", "app-secret")
    monkeypatch.setenv("X_ACCESS_TOKEN_DEFAULT", "user-token")
    monkeypatch.setenv("X_ACCESS_TOKEN_SECRET_DEFAULT", "user-token-secret")


# ---------------------------------------------------------------------------
# Ships-dark feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlagShipsDark:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(X_POST_ENABLED_ENV, raising=False)
        assert _is_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(X_POST_ENABLED_ENV, val)
        assert _is_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "maybe"])
    def test_falsy_values_stay_disabled(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(X_POST_ENABLED_ENV, val)
        assert _is_enabled() is False

    @pytest.mark.asyncio
    async def test_disabled_returns_failed_result_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default state: flag off, no creds. Must fail CLOSED with a clear
        message — not raise, not a fake success."""
        monkeypatch.delenv(X_POST_ENABLED_ENV, raising=False)
        for var in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN_DEFAULT",
            "X_ACCESS_TOKEN_SECRET_DEFAULT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = XPostTool()
        result = await tool.execute(text="Hello X")
        assert result.success is False
        assert X_POST_ENABLED_ENV in (result.error or "")
        assert "disabled" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_disabled_even_with_creds_present(
        self, monkeypatch: pytest.MonkeyPatch, x_creds_default: None
    ) -> None:
        """Credentials present but flag off → still fails closed. The flag is
        the ships-dark gate; creds alone do not arm the channel."""
        monkeypatch.delenv(X_POST_ENABLED_ENV, raising=False)
        tool = XPostTool()
        result = await tool.execute(text="Hello X")
        assert result.success is False
        assert "disabled" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Credential gate (flag ON) — fail closed with ToolNotConfiguredError
# ---------------------------------------------------------------------------


class TestCredentialGate:
    @pytest.mark.asyncio
    async def test_enabled_but_no_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch, x_enabled: None
    ) -> None:
        for var in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN_DEFAULT",
            "X_ACCESS_TOKEN_SECRET_DEFAULT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = XPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello X")
        msg = str(exc_info.value)
        assert "X_API_KEY" in msg
        assert "X_ACCESS_TOKEN_DEFAULT" in msg

    @pytest.mark.asyncio
    async def test_enabled_partial_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch, x_enabled: None
    ) -> None:
        monkeypatch.setenv("X_API_KEY", "app-key")
        monkeypatch.setenv("X_API_SECRET", "app-secret")
        monkeypatch.setenv("X_ACCESS_TOKEN_DEFAULT", "user-token")
        monkeypatch.delenv("X_ACCESS_TOKEN_SECRET_DEFAULT", raising=False)

        tool = XPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello X")
        assert "X_ACCESS_TOKEN_SECRET_DEFAULT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_per_persona_creds_isolated(
        self, monkeypatch: pytest.MonkeyPatch, x_enabled: None, x_creds_default: None
    ) -> None:
        """Provisioning DEFAULT does not satisfy a request for GROWTH_BOT."""
        for var in (
            "X_ACCESS_TOKEN_GROWTH_BOT",
            "X_ACCESS_TOKEN_SECRET_GROWTH_BOT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = XPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello", persona_id="growth-bot")
        assert "X_ACCESS_TOKEN_GROWTH_BOT" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Disclosure + 280-char limit
# ---------------------------------------------------------------------------


class TestDisclosureAndLimit:
    def test_disclosure_appended(self) -> None:
        out, applied = _apply_disclosure_with_limit("Hello world")
        assert applied is True
        assert out.endswith(DISCLOSURE_FOOTER)
        assert "AI agent" in out and "MADFAM" in out

    def test_disclosure_idempotent(self) -> None:
        body = "Built with an AI agent on behalf of MADFAM."
        out, applied = _apply_disclosure_with_limit(body)
        assert applied is True
        assert out.count("AI agent on behalf of MADFAM") == 1

    def test_body_overflow_raises(self) -> None:
        with pytest.raises(PostTooLongError) as exc_info:
            _apply_disclosure_with_limit("x" * (X_MAX_POST_CHARS + 5))
        assert "280" in str(exc_info.value)

    def test_body_plus_footer_overflow_raises(self) -> None:
        body = "x" * (X_MAX_POST_CHARS - 5)
        with pytest.raises(PostTooLongError) as exc_info:
            _apply_disclosure_with_limit(body)
        assert str(len(DISCLOSURE_FOOTER)) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_returns_error_on_overflow(
        self, x_enabled: None, x_creds_default: None
    ) -> None:
        tool = XPostTool()
        result = await tool.execute(text="x" * (X_MAX_POST_CHARS + 10))
        assert result.success is False
        assert "280" in (result.error or "")


# ---------------------------------------------------------------------------
# End-to-end (flag ON, mocked client) — proves no fake success path exists
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_happy_path_only_with_flag_and_creds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        x_enabled: None,
        x_creds_default: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)

        fake_client = MagicMock()
        emitted: list[dict] = []

        with (
            patch.object(x_tools, "_build_x_client", return_value=fake_client),
            patch.object(
                x_tools,
                "_post_via_x",
                return_value={
                    "post_id": "1789",
                    "post_url": "https://x.com/i/web/status/1789",
                },
            ),
            patch.object(
                x_tools,
                "_emit_outbound_post_event",
                side_effect=lambda **kw: emitted.append(kw),
            ),
        ):
            tool = XPostTool()
            result = await tool.execute(text="Drop 1 of MADFAM.", persona_id="default")

        assert result.success is True
        assert result.data["post_id"] == "1789"
        assert result.data["disclosure_applied"] is True
        assert len(emitted) == 1


# ---------------------------------------------------------------------------
# Audience + registration + playbook
# ---------------------------------------------------------------------------


class TestAudienceAndRegistration:
    def test_x_tool_is_tenant_audience(self) -> None:
        assert XPostTool().audience == Audience.TENANT

    def test_x_tool_absent_from_registry_while_dark(self) -> None:
        """Ships-dark contract: un-armed means NOT registered at all."""
        from selva_tools.builtins import get_builtin_tools

        names = {t.name for t in get_builtin_tools()}
        assert "x_post" not in names

    def test_x_tool_registered_when_operator_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from selva_tools.builtins import get_builtin_tools

        monkeypatch.setenv("SELVA_X_POST_ENABLED", "true")
        names = {t.name for t in get_builtin_tools()}
        assert "x_post" in names


class TestPlaybookRegistration:
    def test_x_promo_v1_playbook_registered(self) -> None:
        from selva_permissions.playbook import get_builtin_playbook

        pb = get_builtin_playbook("x_promo_v1")
        assert pb is not None
        assert pb.require_approval is True
        assert pb.financial_cap_cents == 0
        assert "social_post" in pb.allowed_actions


class TestSchema:
    def test_parameters_schema_shape(self) -> None:
        schema = XPostTool().parameters_schema()
        assert schema["type"] == "object"
        assert "text" in schema["required"]
        assert schema["properties"]["text"]["maxLength"] == X_MAX_POST_CHARS

    def test_to_openai_spec(self) -> None:
        spec = XPostTool().to_openai_spec()
        assert spec["function"]["name"] == "x_post"
