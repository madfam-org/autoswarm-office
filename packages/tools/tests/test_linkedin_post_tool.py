"""Tests for the LinkedIn DIRECT-POST capability scaffold (ships dark).

Mirrors ``test_x_tools.py``. Emphasis:

- Feature flag OFF by default → failed ToolResult that points the caller at
  the draft path (never a crash, never a fake success).
- Flag ON but credentials missing → ToolNotConfiguredError.
- Mandatory disclosure footer (automated posts must disclose — unlike the
  manual draft tool) + 3000-char limit enforced.
- Registration + audience tag + linkedin_promo_v1 playbook.
- The manual draft tool (linkedin_draft_create) is unaffected and still
  registered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import linkedin_post_tool
from selva_tools.builtins.linkedin_post_tool import (
    DISCLOSURE_FOOTER,
    LINKEDIN_MAX_POST_CHARS,
    LINKEDIN_POST_ENABLED_ENV,
    LinkedInPostTool,
    PostTooLongError,
    ToolNotConfiguredError,
    _apply_disclosure_with_limit,
    _is_enabled,
)


@pytest.fixture()
def li_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LINKEDIN_POST_ENABLED_ENV, "true")


@pytest.fixture()
def li_creds_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN_DEFAULT", "oauth-token")
    monkeypatch.setenv("LINKEDIN_AUTHOR_URN_DEFAULT", "urn:li:person:abc123")


# ---------------------------------------------------------------------------
# Ships-dark feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlagShipsDark:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(LINKEDIN_POST_ENABLED_ENV, raising=False)
        assert _is_enabled() is False

    @pytest.mark.asyncio
    async def test_disabled_returns_failed_result_pointing_at_draft(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(LINKEDIN_POST_ENABLED_ENV, raising=False)
        for var in ("LINKEDIN_ACCESS_TOKEN_DEFAULT", "LINKEDIN_AUTHOR_URN_DEFAULT"):
            monkeypatch.delenv(var, raising=False)

        tool = LinkedInPostTool()
        result = await tool.execute(text="Hello LinkedIn")
        assert result.success is False
        assert LINKEDIN_POST_ENABLED_ENV in (result.error or "")
        # Points the operator/agent at the default draft path.
        assert "linkedin_draft_create" in (result.error or "")

    @pytest.mark.asyncio
    async def test_disabled_even_with_creds_present(
        self, monkeypatch: pytest.MonkeyPatch, li_creds_default: None
    ) -> None:
        monkeypatch.delenv(LINKEDIN_POST_ENABLED_ENV, raising=False)
        tool = LinkedInPostTool()
        result = await tool.execute(text="Hello LinkedIn")
        assert result.success is False
        assert "disabled" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Credential gate (flag ON)
# ---------------------------------------------------------------------------


class TestCredentialGate:
    @pytest.mark.asyncio
    async def test_enabled_but_no_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch, li_enabled: None
    ) -> None:
        for var in ("LINKEDIN_ACCESS_TOKEN_DEFAULT", "LINKEDIN_AUTHOR_URN_DEFAULT"):
            monkeypatch.delenv(var, raising=False)

        tool = LinkedInPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello LinkedIn")
        msg = str(exc_info.value)
        assert "LINKEDIN_ACCESS_TOKEN_DEFAULT" in msg
        assert "LINKEDIN_AUTHOR_URN_DEFAULT" in msg

    @pytest.mark.asyncio
    async def test_enabled_partial_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch, li_enabled: None
    ) -> None:
        monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN_DEFAULT", "oauth-token")
        monkeypatch.delenv("LINKEDIN_AUTHOR_URN_DEFAULT", raising=False)

        tool = LinkedInPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello LinkedIn")
        assert "LINKEDIN_AUTHOR_URN_DEFAULT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_per_persona_creds_isolated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        li_enabled: None,
        li_creds_default: None,
    ) -> None:
        for var in (
            "LINKEDIN_ACCESS_TOKEN_GROWTH_BOT",
            "LINKEDIN_AUTHOR_URN_GROWTH_BOT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = LinkedInPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hi", persona_id="growth-bot")
        assert "LINKEDIN_ACCESS_TOKEN_GROWTH_BOT" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Disclosure + 3000-char limit (automated posts MUST disclose)
# ---------------------------------------------------------------------------


class TestDisclosureAndLimit:
    def test_disclosure_appended(self) -> None:
        out, applied = _apply_disclosure_with_limit("Hello world")
        assert applied is True
        assert out.endswith(DISCLOSURE_FOOTER)
        assert "AI agent on behalf of MADFAM" in out

    def test_disclosure_idempotent(self) -> None:
        body = "Note: made by an AI agent on behalf of MADFAM."
        out, applied = _apply_disclosure_with_limit(body)
        assert out.count("AI agent on behalf of MADFAM") == 1

    def test_body_overflow_raises(self) -> None:
        with pytest.raises(PostTooLongError):
            _apply_disclosure_with_limit("x" * (LINKEDIN_MAX_POST_CHARS + 5))

    @pytest.mark.asyncio
    async def test_execute_returns_error_on_overflow(
        self, li_enabled: None, li_creds_default: None
    ) -> None:
        tool = LinkedInPostTool()
        result = await tool.execute(text="x" * (LINKEDIN_MAX_POST_CHARS + 10))
        assert result.success is False
        assert "3000" in (result.error or "")


# ---------------------------------------------------------------------------
# End-to-end (flag ON, mocked httpx client)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_happy_path_only_with_flag_and_creds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        li_enabled: None,
        li_creds_default: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)

        fake_client = MagicMock()
        with (
            patch.object(linkedin_post_tool, "_build_linkedin_client", return_value=fake_client),
            patch.object(
                linkedin_post_tool,
                "_post_via_linkedin",
                return_value={
                    "post_id": "urn:li:share:999",
                    "post_url": "https://www.linkedin.com/feed/update/urn:li:share:999",
                },
            ),
            patch.object(linkedin_post_tool, "_emit_outbound_post_event"),
        ):
            tool = LinkedInPostTool()
            result = await tool.execute(text="MADFAM ships.", persona_id="default")

        assert result.success is True
        assert result.data["post_id"] == "urn:li:share:999"
        assert result.data["disclosure_applied"] is True


# ---------------------------------------------------------------------------
# Audience + registration + playbook + draft-tool coexistence
# ---------------------------------------------------------------------------


class TestAudienceAndRegistration:
    def test_linkedin_post_tool_is_tenant_audience(self) -> None:
        assert LinkedInPostTool().audience == Audience.TENANT

    def test_both_post_and_draft_tools_registered(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        names = {t.name for t in get_builtin_tools()}
        assert "linkedin_post" in names
        # The manual draft path is preserved, not replaced.
        assert "linkedin_draft_create" in names


class TestPlaybookRegistration:
    def test_linkedin_promo_v1_playbook_registered(self) -> None:
        from selva_permissions.playbook import get_builtin_playbook

        pb = get_builtin_playbook("linkedin_promo_v1")
        assert pb is not None
        assert pb.require_approval is True
        assert pb.financial_cap_cents == 0
        assert "social_post" in pb.allowed_actions


class TestSchema:
    def test_parameters_schema_shape(self) -> None:
        schema = LinkedInPostTool().parameters_schema()
        assert "text" in schema["required"]
        assert schema["properties"]["text"]["maxLength"] == LINKEDIN_MAX_POST_CHARS

    def test_to_openai_spec(self) -> None:
        spec = LinkedInPostTool().to_openai_spec()
        assert spec["function"]["name"] == "linkedin_post"
