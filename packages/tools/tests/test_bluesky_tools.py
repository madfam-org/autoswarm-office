"""Tests for Bluesky / AT Protocol posting capability + disclosure +
300-char limit + per-persona rate-limit + audience tag.

Covers:
- ToolNotConfiguredError when env vars missing for the requested persona
  (no placeholder ever shipped).
- Disclosure footer applied to every outbound post.
- Idempotent disclosure (no double-stamp when agent pre-stamped).
- 300-char hard limit enforced INCLUDING the disclosure footer.
- PostTooLongError raised (not silent truncation) when body alone is
  too long.
- PostTooLongError raised when body + footer overflows 300 chars.
- Per-persona Redis rate-limit enforcement.
- PostHog ``outbound_post.created`` event fired with platform=bluesky
  + persona_id + post_uri + disclosure_applied.
- Audience tag (TENANT — tenant swarms can run Bluesky promos).
- Tool registration in ``get_builtin_tools()``.
- bluesky_promo_v1 playbook is registered + has require_approval=True.
- at:// URI → bsky.app URL conversion (happy path + malformed input).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import bluesky_tools
from selva_tools.builtins.bluesky_tools import (
    BLUESKY_MAX_POST_CHARS,
    DISCLOSURE_FOOTER,
    BlueskyPostTool,
    PostTooLongError,
    ToolNotConfiguredError,
    _apply_disclosure_with_limit,
    _uri_to_bsky_app_url,
)


@pytest.fixture()
def bluesky_creds_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provision env vars for the 'default' persona."""
    monkeypatch.setenv("BLUESKY_HANDLE_DEFAULT", "madfam.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD_DEFAULT", "abcd-efgh-ijkl-mnop")


# ---------------------------------------------------------------------------
# Credential gate
# ---------------------------------------------------------------------------


class TestCredentialGate:
    """When per-persona env vars are missing, the tool MUST raise
    ToolNotConfiguredError rather than return placeholder text."""

    @pytest.mark.asyncio
    async def test_missing_both_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "BLUESKY_HANDLE_DEFAULT",
            "BLUESKY_APP_PASSWORD_DEFAULT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = BlueskyPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello world")
        assert "BLUESKY_HANDLE_DEFAULT" in str(exc_info.value)
        assert "BLUESKY_APP_PASSWORD_DEFAULT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_one_cred_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLUESKY_HANDLE_DEFAULT", "madfam.bsky.social")
        monkeypatch.delenv("BLUESKY_APP_PASSWORD_DEFAULT", raising=False)

        tool = BlueskyPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello world")
        assert "BLUESKY_APP_PASSWORD_DEFAULT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_per_persona_creds_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provisioning DEFAULT does not satisfy a request for GROWTH_BOT."""
        monkeypatch.setenv("BLUESKY_HANDLE_DEFAULT", "x.bsky.social")
        monkeypatch.setenv("BLUESKY_APP_PASSWORD_DEFAULT", "x")
        for var in (
            "BLUESKY_HANDLE_GROWTH_BOT",
            "BLUESKY_APP_PASSWORD_GROWTH_BOT",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = BlueskyPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(text="Hello", persona_id="growth-bot")
        assert "BLUESKY_HANDLE_GROWTH_BOT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_whitespace_only_cred_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLUESKY_HANDLE_DEFAULT", "   ")
        monkeypatch.setenv("BLUESKY_APP_PASSWORD_DEFAULT", "x")

        tool = BlueskyPostTool()
        with pytest.raises(ToolNotConfiguredError):
            await tool.execute(text="Hello world")


# ---------------------------------------------------------------------------
# Disclosure + 300-char limit
# ---------------------------------------------------------------------------


class TestDisclosureAndLimit:
    def test_disclosure_appended_to_short_text(self) -> None:
        out, applied = _apply_disclosure_with_limit("Hello world")
        assert applied is True
        assert out.startswith("Hello world")
        assert out.endswith(DISCLOSURE_FOOTER)
        assert "AI agent" in out
        assert "MADFAM" in out

    def test_disclosure_idempotent_when_pre_stamped(self) -> None:
        body = "Drop 1 — built with help from an AI agent on behalf of MADFAM."
        out, applied = _apply_disclosure_with_limit(body)
        assert applied is True
        # No double-stamp.
        assert out.count("AI agent on behalf of MADFAM") == 1

    def test_total_post_within_300_chars(self) -> None:
        # Body with budget = 300 - len(footer), trimmed by 1 to stay
        # comfortably under.
        budget = BLUESKY_MAX_POST_CHARS - len(DISCLOSURE_FOOTER) - 1
        body = "x" * budget
        out, applied = _apply_disclosure_with_limit(body)
        assert applied is True
        assert len(out) <= BLUESKY_MAX_POST_CHARS

    def test_body_alone_overflows_raises(self) -> None:
        """User text alone past 300 chars → hard error (no silent
        truncation)."""
        body = "x" * (BLUESKY_MAX_POST_CHARS + 5)
        with pytest.raises(PostTooLongError) as exc_info:
            _apply_disclosure_with_limit(body)
        assert "300" in str(exc_info.value)

    def test_body_plus_footer_overflow_raises(self) -> None:
        """Body fits but body + footer exceeds 300 → hard error.

        Forces the agent to leave room for the mandatory footer.
        """
        # Body fits within 300 but only barely — adding the footer
        # pushes past.
        body = "x" * (BLUESKY_MAX_POST_CHARS - 5)
        assert len(body) <= BLUESKY_MAX_POST_CHARS  # body alone is fine
        with pytest.raises(PostTooLongError) as exc_info:
            _apply_disclosure_with_limit(body)
        msg = str(exc_info.value)
        assert "300" in msg
        # Error message must mention the footer cost so agent can
        # rewrite within budget.
        assert str(len(DISCLOSURE_FOOTER)) in msg

    def test_pre_stamped_body_over_300_raises(self) -> None:
        body = "x" * 250 + " AI agent on behalf of MADFAM " + "y" * 60
        assert len(body) > BLUESKY_MAX_POST_CHARS
        with pytest.raises(PostTooLongError):
            _apply_disclosure_with_limit(body)

    @pytest.mark.asyncio
    async def test_execute_returns_error_on_overflow(
        self, bluesky_creds_default: None
    ) -> None:
        """Execute must NOT raise — it returns a failed ToolResult so
        the agent can see the policy violation in the audit trail."""
        tool = BlueskyPostTool()
        body = "x" * (BLUESKY_MAX_POST_CHARS + 10)
        result = await tool.execute(text=body, persona_id="default")
        assert result.success is False
        assert "300" in (result.error or "")


# ---------------------------------------------------------------------------
# at:// URI → bsky.app URL
# ---------------------------------------------------------------------------


class TestUriToWebUrl:
    def test_happy_path(self) -> None:
        uri = "at://did:plc:abc123/app.bsky.feed.post/3kxyz"
        url = _uri_to_bsky_app_url(uri)
        assert url == "https://bsky.app/profile/did:plc:abc123/post/3kxyz"

    def test_malformed_uri_returns_empty(self) -> None:
        assert _uri_to_bsky_app_url("") == ""
        assert _uri_to_bsky_app_url("https://example.com") == ""
        assert _uri_to_bsky_app_url("at://did:plc:abc/wrong.collection/x") == ""


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_no_redis_url_skips_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REDIS_URL unset → rate-limit silently skipped (HITL still gates)."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        # Should not raise.
        await bluesky_tools._check_and_set_rate_limit("default")

    @pytest.mark.asyncio
    async def test_rate_limit_hit_rejects_post(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bluesky_creds_default: None,
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Mock redis.asyncio: existing key found.
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1")
        mock_redis.ttl = AsyncMock(return_value=300)
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            tool = BlueskyPostTool()
            result = await tool.execute(text="Hello world", persona_id="default")

        assert result.success is False
        assert "rate-limit" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_rate_limit_miss_proceeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bluesky_creds_default: None,
    ) -> None:
        """No existing key → rate-limit allows post, sets the key."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)  # no existing key
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await bluesky_tools._check_and_set_rate_limit("default")

        # SETEX-style claim happened.
        mock_redis.set.assert_awaited_once()
        _args, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 30 * 60  # 30 min TTL
        assert kwargs.get("nx") is True


# ---------------------------------------------------------------------------
# End-to-end (mocked atproto + Redis)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_post_flow_emits_event_and_applies_disclosure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bluesky_creds_default: None,
    ) -> None:
        """Happy path: creds present, rate-limit clear, atproto returns
        success → ToolResult.success=True, disclosure applied, PostHog
        event fired with platform=bluesky."""
        # Skip Redis path entirely.
        monkeypatch.delenv("REDIS_URL", raising=False)

        # Mock atproto client.send_post response.
        fake_response = MagicMock()
        fake_response.uri = (
            "at://did:plc:fakedid/app.bsky.feed.post/3krpost"
        )
        fake_response.cid = "bafyfakecid"
        fake_client = MagicMock()
        fake_client.send_post = MagicMock(return_value=fake_response)

        # PostHog spy.
        emitted: list[dict] = []

        def _spy_emit(
            persona_id: str,
            post_uri: str,
            post_cid: str,
            disclosure_applied: bool,
        ) -> None:
            emitted.append(
                {
                    "persona_id": persona_id,
                    "post_uri": post_uri,
                    "post_cid": post_cid,
                    "disclosure_applied": disclosure_applied,
                }
            )

        with (
            patch.object(
                bluesky_tools, "_build_bluesky_client", return_value=fake_client
            ),
            patch.object(
                bluesky_tools, "_emit_outbound_post_event", side_effect=_spy_emit
            ),
        ):
            tool = BlueskyPostTool()
            result = await tool.execute(
                text="Drop 1 of MADFAM Selva.",
                persona_id="default",
            )

        assert result.success is True
        assert (
            result.data["post_uri"]
            == "at://did:plc:fakedid/app.bsky.feed.post/3krpost"
        )
        assert (
            result.data["post_url"]
            == "https://bsky.app/profile/did:plc:fakedid/post/3krpost"
        )
        assert result.data["post_cid"] == "bafyfakecid"
        assert result.data["disclosure_applied"] is True
        assert result.data["langs"] == ["en"]

        # Disclosure footer was actually included in the submitted text.
        submitted_text = fake_client.send_post.call_args.kwargs["text"]
        assert "AI agent on behalf of MADFAM" in submitted_text
        assert len(submitted_text) <= BLUESKY_MAX_POST_CHARS

        # PostHog event fired with platform=bluesky semantics.
        assert len(emitted) == 1
        assert emitted[0]["persona_id"] == "default"
        assert emitted[0]["disclosure_applied"] is True
        assert emitted[0]["post_uri"].startswith("at://")

    @pytest.mark.asyncio
    async def test_langs_passed_through_to_atproto(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bluesky_creds_default: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)

        fake_response = MagicMock(
            uri="at://did:plc:abc/app.bsky.feed.post/x", cid="cid"
        )
        fake_client = MagicMock(send_post=MagicMock(return_value=fake_response))

        with (
            patch.object(
                bluesky_tools, "_build_bluesky_client", return_value=fake_client
            ),
            patch.object(bluesky_tools, "_emit_outbound_post_event"),
        ):
            tool = BlueskyPostTool()
            result = await tool.execute(
                text="Hola", persona_id="default", langs=["es"]
            )

        assert result.success is True
        assert fake_client.send_post.call_args.kwargs["langs"] == ["es"]

    @pytest.mark.asyncio
    async def test_reply_to_passed_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bluesky_creds_default: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)

        fake_response = MagicMock(
            uri="at://did:plc:abc/app.bsky.feed.post/y", cid="cid2"
        )
        fake_client = MagicMock(send_post=MagicMock(return_value=fake_response))

        reply_ref = {
            "root": {"uri": "at://x/app.bsky.feed.post/r1", "cid": "c1"},
            "parent": {"uri": "at://x/app.bsky.feed.post/p1", "cid": "c2"},
        }
        with (
            patch.object(
                bluesky_tools, "_build_bluesky_client", return_value=fake_client
            ),
            patch.object(bluesky_tools, "_emit_outbound_post_event"),
        ):
            tool = BlueskyPostTool()
            result = await tool.execute(
                text="Reply",
                persona_id="default",
                reply_to=reply_ref,
            )

        assert result.success is True
        assert fake_client.send_post.call_args.kwargs["reply_to"] == reply_ref


# ---------------------------------------------------------------------------
# Audience tag + registration
# ---------------------------------------------------------------------------


class TestAudienceAndRegistration:
    def test_bluesky_tool_is_tenant_audience(self) -> None:
        """Tenant swarms must be able to use Bluesky (per their own
        creds); platform-only Bluesky ops would be a separate tool."""
        tool = BlueskyPostTool()
        assert tool.audience == Audience.TENANT

    def test_bluesky_tool_registered_in_get_builtin_tools(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        tools = get_builtin_tools()
        names = {t.name for t in tools}
        assert "bluesky_post" in names


# ---------------------------------------------------------------------------
# Playbook registration
# ---------------------------------------------------------------------------


class TestPlaybookRegistration:
    def test_bluesky_promo_v1_playbook_registered(self) -> None:
        from selva_permissions.playbook import get_builtin_playbook

        pb = get_builtin_playbook("bluesky_promo_v1")
        assert pb is not None
        assert pb.require_approval is True  # HITL gate by default
        assert pb.financial_cap_cents == 0
        assert "social_post" in pb.allowed_actions


# ---------------------------------------------------------------------------
# OpenAI spec shape
# ---------------------------------------------------------------------------


class TestSchema:
    def test_parameters_schema_shape(self) -> None:
        tool = BlueskyPostTool()
        schema = tool.parameters_schema()
        assert schema["type"] == "object"
        assert "text" in schema["required"]
        assert "persona_id" in schema["properties"]
        assert "langs" in schema["properties"]
        assert "reply_to" in schema["properties"]
        # Bluesky's hard limit — text <= 300 chars
        assert schema["properties"]["text"]["maxLength"] == BLUESKY_MAX_POST_CHARS

    def test_to_openai_spec_includes_function(self) -> None:
        tool = BlueskyPostTool()
        spec = tool.to_openai_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "bluesky_post"
