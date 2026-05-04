"""Tests for Reddit posting capability + disclosure + rate-limit + audience.

Covers:
- ToolNotConfiguredError when env vars missing (no placeholder ever shipped)
- Disclosure-applied path (default per-subreddit policy is conservative)
- Disclosure-skipped path (explicit policy opt-out)
- Idempotent disclosure (no double-stamp when agent pre-stamped)
- ConfigMap loading happy path + missing-file fallback
- Rate-limit enforcement (Redis hit → reject)
- Rate-limit miss when Redis unavailable (allows post, doesn't block ops)
- PostHog event emission (fire-and-forget; never raises)
- Audience tag (TENANT — tenant swarms can run Reddit promos for their org)
- Tool registration in get_builtin_tools()
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import reddit_tools
from selva_tools.builtins.reddit_tools import (
    RedditPostTool,
    SubredditPolicy,
    ToolNotConfiguredError,
    _load_policies,
    _maybe_apply_disclosure,
    _resolve_policy,
)


@pytest.fixture(autouse=True)
def _clear_policy_cache() -> None:
    """Ensure each test starts with a fresh policy cache."""
    from selva_tools.builtins import reddit_tools as rt

    rt._POLICY_CACHE.policies = {}
    rt._POLICY_CACHE.loaded = False
    rt._POLICY_CACHE.source_path = None


@pytest.fixture()
def reddit_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject test Reddit creds. PRAW client itself is mocked separately."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test_client")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "selva-test/1.0")
    monkeypatch.setenv("REDDIT_REFRESH_TOKEN", "test_refresh")


# ---------------------------------------------------------------------------
# Credential gate
# ---------------------------------------------------------------------------


class TestCredentialGate:
    """When env vars are missing, the tool MUST raise ToolNotConfiguredError
    rather than return placeholder text. This is the v2.1.1 placeholder-
    abort pattern applied to public-social posting."""

    @pytest.mark.asyncio
    async def test_missing_all_creds_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_USER_AGENT",
            "REDDIT_REFRESH_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)

        tool = RedditPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(subreddit="SaaS", title="Hello", body="World")
        assert "REDDIT_CLIENT_ID" in str(exc_info.value)
        assert "REDDIT_CLIENT_SECRET" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_one_cred_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDDIT_CLIENT_ID", "x")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "x")
        monkeypatch.setenv("REDDIT_USER_AGENT", "x")
        monkeypatch.delenv("REDDIT_REFRESH_TOKEN", raising=False)

        tool = RedditPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(subreddit="SaaS", title="Hello", body="World")
        assert "REDDIT_REFRESH_TOKEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_whitespace_only_cred_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDDIT_CLIENT_ID", "   ")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "x")
        monkeypatch.setenv("REDDIT_USER_AGENT", "x")
        monkeypatch.setenv("REDDIT_REFRESH_TOKEN", "x")

        tool = RedditPostTool()
        with pytest.raises(ToolNotConfiguredError):
            await tool.execute(subreddit="SaaS", title="Hello", body="World")


# ---------------------------------------------------------------------------
# ConfigMap loading
# ---------------------------------------------------------------------------


class TestPolicyLoading:
    def test_load_policies_from_configmap(self, tmp_path: Path) -> None:
        config = tmp_path / "subreddit_policies.yaml"
        config.write_text(
            """
policies:
  - subreddit: SaaS
    disclosure_required: true
    min_karma: 100
  - subreddit: r/Entrepreneur
    disclosure_required: false
    flair: AMA
""".strip()
        )
        policies = _load_policies(config)
        assert "saas" in policies
        assert policies["saas"].min_karma == 100
        assert policies["saas"].disclosure_required is True
        # 'r/' prefix stripped
        assert "entrepreneur" in policies
        assert policies["entrepreneur"].disclosure_required is False
        assert policies["entrepreneur"].flair == "AMA"

    def test_missing_configmap_returns_empty_dict(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.yaml"
        assert _load_policies(missing) == {}

    def test_unlisted_subreddit_defaults_to_disclosure_required(
        self, tmp_path: Path
    ) -> None:
        """A subreddit with no entry in the ConfigMap gets the conservative
        default — disclosure required, no minimum karma."""
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        with patch.object(reddit_tools, "CONFIGMAP_PATH", empty):
            policy = _resolve_policy("UnknownSubreddit")
        assert policy.disclosure_required is True

    def test_malformed_yaml_falls_back_safely(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("policies: { this: is: not: valid")
        # Should not raise — fall back to safe defaults.
        result = _load_policies(bad)
        assert result == {}


# ---------------------------------------------------------------------------
# Disclosure footer
# ---------------------------------------------------------------------------


class TestDisclosure:
    def test_disclosure_appended_when_required(self) -> None:
        policy = SubredditPolicy(subreddit="x", disclosure_required=True)
        out, applied = _maybe_apply_disclosure("Hello world", policy)
        assert applied is True
        assert "AI agent" in out
        assert "madfam.io/ai-disclosure" in out
        assert out.startswith("Hello world")

    def test_disclosure_not_appended_when_not_required(self) -> None:
        policy = SubredditPolicy(subreddit="x", disclosure_required=False)
        out, applied = _maybe_apply_disclosure("Hello world", policy)
        assert applied is False
        assert out == "Hello world"

    def test_disclosure_idempotent_when_pre_stamped(self) -> None:
        """Defends against an agent that hand-crafts the disclosure footer
        before sending — we don't double-stamp."""
        policy = SubredditPolicy(subreddit="x", disclosure_required=True)
        body = "Hello world\n\nI'm an AI — see https://madfam.io/ai-disclosure"
        out, applied = _maybe_apply_disclosure(body, policy)
        assert applied is True
        assert out.count("madfam.io/ai-disclosure") == 1


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
        await reddit_tools._check_and_set_rate_limit("SaaS")

    @pytest.mark.asyncio
    async def test_rate_limit_hit_rejects_post(
        self,
        monkeypatch: pytest.MonkeyPatch,
        reddit_creds: None,
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Mock redis.asyncio: existing key found.
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1")
        mock_redis.ttl = AsyncMock(return_value=300)
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            tool = RedditPostTool()
            result = await tool.execute(
                subreddit="SaaS", title="Hello", body="World"
            )

        assert result.success is False
        assert "rate-limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_miss_proceeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        reddit_creds: None,
    ) -> None:
        """No existing key → rate-limit allows post, sets the key."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)  # no existing key
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await reddit_tools._check_and_set_rate_limit("SaaS")

        # SETEX-style claim happened.
        mock_redis.set.assert_awaited_once()
        args, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 30 * 60  # 30 min TTL
        assert kwargs.get("nx") is True


# ---------------------------------------------------------------------------
# End-to-end (mocked PRAW + Redis)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_post_flow_emits_event_and_applies_disclosure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        reddit_creds: None,
    ) -> None:
        """Happy path: creds present, rate-limit clear, PRAW returns success
        → ToolResult.success=True, disclosure applied, PostHog event fired."""
        # Skip Redis path entirely.
        monkeypatch.delenv("REDIS_URL", raising=False)

        # Empty ConfigMap path — falls through to default disclosure_required=True.
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        monkeypatch.setattr(reddit_tools, "CONFIGMAP_PATH", empty)

        # Mock PRAW.
        fake_submission = MagicMock()
        fake_submission.permalink = "/r/SaaS/comments/abc123/test_post/"
        fake_submission.id = "abc123"
        fake_subreddit = MagicMock()
        fake_subreddit.submit = MagicMock(return_value=fake_submission)
        fake_client = MagicMock()
        fake_client.subreddit = MagicMock(return_value=fake_subreddit)

        # PostHog spy.
        emitted: list[tuple[str, str, str, bool]] = []

        def _spy_emit(
            subreddit: str,
            persona_id: str,
            post_id: str,
            disclosure_applied: bool,
        ) -> None:
            emitted.append((subreddit, persona_id, post_id, disclosure_applied))

        with (
            patch.object(reddit_tools, "_build_reddit_client", return_value=fake_client),
            patch.object(reddit_tools, "_emit_outbound_post_event", side_effect=_spy_emit),
        ):
            tool = RedditPostTool()
            result = await tool.execute(
                subreddit="SaaS",
                title="Test post",
                body="Hello world",
                persona_id="growth-bot-1",
            )

        assert result.success is True
        assert result.data["post_id"] == "abc123"
        assert result.data["post_url"] == "https://reddit.com/r/SaaS/comments/abc123/test_post/"
        assert result.data["disclosure_applied"] is True

        # Disclosure footer was actually included in the submitted body.
        submitted_body = fake_subreddit.submit.call_args.kwargs["selftext"]
        assert "madfam.io/ai-disclosure" in submitted_body

        # PostHog event fired exactly once with all the right fields.
        assert len(emitted) == 1
        assert emitted[0] == ("SaaS", "growth-bot-1", "abc123", True)

    @pytest.mark.asyncio
    async def test_subreddit_with_disclosure_off_skips_footer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        reddit_creds: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        config = tmp_path / "policy.yaml"
        config.write_text(
            "policies:\n  - subreddit: AMA\n    disclosure_required: false"
        )
        monkeypatch.setattr(reddit_tools, "CONFIGMAP_PATH", config)

        fake_submission = MagicMock(permalink="/r/AMA/x", id="xx")
        fake_subreddit = MagicMock(submit=MagicMock(return_value=fake_submission))
        fake_client = MagicMock(subreddit=MagicMock(return_value=fake_subreddit))

        with (
            patch.object(reddit_tools, "_build_reddit_client", return_value=fake_client),
            patch.object(reddit_tools, "_emit_outbound_post_event"),
        ):
            tool = RedditPostTool()
            result = await tool.execute(subreddit="AMA", title="t", body="Hello world")

        assert result.success is True
        assert result.data["disclosure_applied"] is False
        submitted_body = fake_subreddit.submit.call_args.kwargs["selftext"]
        assert "madfam.io/ai-disclosure" not in submitted_body


# ---------------------------------------------------------------------------
# Audience tag + registration
# ---------------------------------------------------------------------------


class TestAudienceAndRegistration:
    def test_reddit_tool_is_tenant_audience(self) -> None:
        """Tenant swarms must be able to use Reddit (per their own creds);
        platform-only Reddit ops would be a separate tool."""
        tool = RedditPostTool()
        assert tool.audience == Audience.TENANT

    def test_reddit_tool_registered_in_get_builtin_tools(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        tools = get_builtin_tools()
        names = {t.name for t in tools}
        assert "reddit_post" in names


# ---------------------------------------------------------------------------
# OpenAI spec shape
# ---------------------------------------------------------------------------


class TestSchema:
    def test_parameters_schema_shape(self) -> None:
        tool = RedditPostTool()
        schema = tool.parameters_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"subreddit", "title", "body"}
        assert "persona_id" in schema["properties"]
        # Reddit's hard limit — title <= 300 chars
        assert schema["properties"]["title"]["maxLength"] == 300

    def test_to_openai_spec_includes_function(self) -> None:
        tool = RedditPostTool()
        spec = tool.to_openai_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "reddit_post"
