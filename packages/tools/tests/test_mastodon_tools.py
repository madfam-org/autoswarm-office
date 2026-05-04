"""Tests for Mastodon posting capability + disclosure + rate-limit + audience.

Mirrors the structure of test_reddit_tools.py. Covers:
- ToolNotConfiguredError when env vars missing (no placeholder ever shipped)
- Per-persona env-var sanitisation (persona_id → MASTODON_ACCESS_TOKEN_<sanitised>)
- Disclosure-applied path (default per-instance policy is conservative)
- Disclosure-skipped path (explicit policy opt-out)
- Idempotent disclosure (no double-stamp when agent pre-stamped)
- ConfigMap loading happy path + missing-file fallback
- Default policy when instance unlisted in ConfigMap (conservative)
- Visibility allow-list enforcement (per-instance policy)
- CW gate (per-instance policy)
- Rate-limit enforcement (Redis hit → reject) with per-instance TTL
- Rate-limit miss when Redis unavailable (allows post, doesn't block ops)
- PostHog event emission (fire-and-forget; never raises)
- Audience tag (TENANT — tenant swarms can run Mastodon promos for their org)
- Tool registration in get_builtin_tools()
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import mastodon_tools
from selva_tools.builtins.mastodon_tools import (
    InstancePolicy,
    MastodonPostTool,
    ToolNotConfiguredError,
    _load_policies,
    _maybe_apply_disclosure,
    _persona_env_suffix,
    _resolve_policy,
)


@pytest.fixture(autouse=True)
def _clear_policy_cache() -> None:
    """Ensure each test starts with a fresh policy cache."""
    from selva_tools.builtins import mastodon_tools as mt

    mt._POLICY_CACHE.policies = {}
    mt._POLICY_CACHE.loaded = False
    mt._POLICY_CACHE.source_path = None


@pytest.fixture()
def mastodon_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject test Mastodon creds for the default persona. Mastodon.py
    client is mocked separately."""
    monkeypatch.setenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN_DEFAULT", "test_token_default")


# ---------------------------------------------------------------------------
# Persona env-var suffix
# ---------------------------------------------------------------------------


class TestPersonaEnvSuffix:
    """Persona id sanitisation for env-var lookup must be stable —
    operators bake real env vars on this rule."""

    def test_simple_default(self) -> None:
        assert _persona_env_suffix("default") == "DEFAULT"

    def test_hyphenated_lowercased(self) -> None:
        assert _persona_env_suffix("growth-bot-1") == "GROWTH_BOT_1"

    def test_dotted_and_slashes(self) -> None:
        assert _persona_env_suffix("a.b/c") == "A_B_C"

    def test_empty_falls_back_to_default(self) -> None:
        assert _persona_env_suffix("") == "DEFAULT"

    def test_only_punctuation_falls_back_to_default(self) -> None:
        assert _persona_env_suffix("---") == "DEFAULT"


# ---------------------------------------------------------------------------
# Credential gate
# ---------------------------------------------------------------------------


class TestCredentialGate:
    """When env vars are missing, the tool MUST raise ToolNotConfiguredError
    rather than return placeholder text. v2.1.1 placeholder-abort pattern
    applied to fediverse posting."""

    @pytest.mark.asyncio
    async def test_missing_all_creds_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MASTODON_INSTANCE_URL", raising=False)
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN_DEFAULT", raising=False)

        tool = MastodonPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(instance="mastodon.social", status="Hello world")
        assert "MASTODON_INSTANCE_URL" in str(exc_info.value)
        assert "MASTODON_ACCESS_TOKEN_DEFAULT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_token_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN_DEFAULT", raising=False)

        tool = MastodonPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(instance="mastodon.social", status="Hello world")
        assert "MASTODON_ACCESS_TOKEN_DEFAULT" in str(exc_info.value)
        # Instance URL was provisioned, so it shouldn't be in the missing list.
        assert "MASTODON_INSTANCE_URL" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_per_persona_token_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Persona id maps to a per-persona env var. Default persona's
        token doesn't satisfy a non-default persona."""
        monkeypatch.setenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN_DEFAULT", "default_token")
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN_GROWTH_BOT_1", raising=False)

        tool = MastodonPostTool()
        with pytest.raises(ToolNotConfiguredError) as exc_info:
            await tool.execute(
                instance="mastodon.social",
                status="Hello",
                persona_id="growth-bot-1",
            )
        assert "MASTODON_ACCESS_TOKEN_GROWTH_BOT_1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_whitespace_only_token_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN_DEFAULT", "   ")

        tool = MastodonPostTool()
        with pytest.raises(ToolNotConfiguredError):
            await tool.execute(instance="mastodon.social", status="Hello world")


# ---------------------------------------------------------------------------
# ConfigMap loading
# ---------------------------------------------------------------------------


class TestPolicyLoading:
    def test_load_policies_from_configmap(self, tmp_path: Path) -> None:
        config = tmp_path / "mastodon_policies.yaml"
        config.write_text(
            """
policies:
  - instance: mastodon.social
    disclosure_required: true
    allowed_visibilities: ["unlisted"]
    rate_limit_minutes: 30
  - instance: https://fosstodon.org/
    disclosure_required: true
    allowed_visibilities: ["unlisted"]
    rate_limit_minutes: 60
    cw_required: true
""".strip()
        )
        policies = _load_policies(config)
        assert "mastodon.social" in policies
        # Scheme + trailing slash stripped on normalisation.
        assert "fosstodon.org" in policies
        assert policies["fosstodon.org"].rate_limit_minutes == 60
        assert policies["fosstodon.org"].cw_required is True
        assert policies["mastodon.social"].allowed_visibilities == ("unlisted",)

    def test_missing_configmap_returns_empty_dict(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.yaml"
        assert _load_policies(missing) == {}

    def test_unlisted_instance_defaults_to_conservative(
        self, tmp_path: Path
    ) -> None:
        """An instance with no entry in the ConfigMap gets the conservative
        default — disclosure required, only 'unlisted' visibility allowed,
        30-min rate limit. This is the 'missing per-instance policy' case
        called out in the requirements."""
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        with patch.object(mastodon_tools, "CONFIGMAP_PATH", empty):
            policy = _resolve_policy("UnknownInstance.example.org")
        assert policy.disclosure_required is True
        assert policy.allowed_visibilities == ("unlisted",)
        assert policy.rate_limit_minutes == 30
        assert policy.cw_required is False

    def test_invalid_visibility_in_configmap_filtered_out(
        self, tmp_path: Path
    ) -> None:
        """Bogus visibility values from a hand-edited ConfigMap don't
        sneak into the allow-list — they're filtered to the empty set
        which then falls back to the conservative default."""
        config = tmp_path / "policy.yaml"
        config.write_text(
            "policies:\n"
            "  - instance: example.com\n"
            "    allowed_visibilities: ['public', 'galaxy']  # 'galaxy' is bogus"
        )
        policies = _load_policies(config)
        # 'galaxy' filtered out, 'public' kept.
        assert policies["example.com"].allowed_visibilities == ("public",)

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
        policy = InstancePolicy(instance="x", disclosure_required=True)
        out, applied = _maybe_apply_disclosure("Hello world", policy)
        assert applied is True
        assert "AI agent" in out
        assert "madfam.io/ai-disclosure" in out
        assert out.startswith("Hello world")

    def test_disclosure_not_appended_when_not_required(self) -> None:
        policy = InstancePolicy(instance="x", disclosure_required=False)
        out, applied = _maybe_apply_disclosure("Hello world", policy)
        assert applied is False
        assert out == "Hello world"

    def test_disclosure_idempotent_when_pre_stamped(self) -> None:
        """Defends against an agent that hand-crafts the disclosure footer
        before sending — we don't double-stamp."""
        policy = InstancePolicy(instance="x", disclosure_required=True)
        body = (
            "Hello world\n\n"
            "I'm an AI — see https://madfam.io/ai-disclosure for details"
        )
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
        await mastodon_tools._check_and_set_rate_limit(
            "mastodon.social", ttl_seconds=1800
        )

    @pytest.mark.asyncio
    async def test_rate_limit_hit_rejects_post(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mastodon_creds: None,
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        # Empty ConfigMap → conservative defaults (allows 'unlisted').
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        monkeypatch.setattr(mastodon_tools, "CONFIGMAP_PATH", empty)

        # Mock redis.asyncio: existing key found.
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1")
        mock_redis.ttl = AsyncMock(return_value=300)
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            tool = MastodonPostTool()
            result = await tool.execute(
                instance="mastodon.social", status="Hello world"
            )

        assert result.success is False
        assert "rate-limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_miss_proceeds_with_per_instance_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No existing key → rate-limit allows post, sets the key with
        the per-instance TTL passed in (not a hardcoded 30 min)."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)  # no existing key
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            # 60-min TTL (e.g. fosstodon.org).
            await mastodon_tools._check_and_set_rate_limit(
                "fosstodon.org", ttl_seconds=60 * 60
            )

        mock_redis.set.assert_awaited_once()
        args, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 60 * 60  # honours per-instance TTL
        assert kwargs.get("nx") is True


# ---------------------------------------------------------------------------
# Visibility + CW gates
# ---------------------------------------------------------------------------


class TestVisibilityAndCWGates:
    @pytest.mark.asyncio
    async def test_public_visibility_blocked_by_unlisted_only_policy(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mastodon_creds: None,
    ) -> None:
        """Default per-instance policy allows only 'unlisted'. Asking for
        'public' must fail with a clear error."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        monkeypatch.setattr(mastodon_tools, "CONFIGMAP_PATH", empty)

        tool = MastodonPostTool()
        result = await tool.execute(
            instance="mastodon.social",
            status="Hello world",
            visibility="public",
        )
        assert result.success is False
        assert "forbids visibility" in result.error
        assert "'public'" in result.error

    @pytest.mark.asyncio
    async def test_cw_required_policy_blocks_post_without_cw(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mastodon_creds: None,
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        config = tmp_path / "policy.yaml"
        config.write_text(
            "policies:\n"
            "  - instance: fosstodon.org\n"
            "    disclosure_required: true\n"
            "    allowed_visibilities: ['unlisted']\n"
            "    cw_required: true"
        )
        monkeypatch.setattr(mastodon_tools, "CONFIGMAP_PATH", config)

        tool = MastodonPostTool()
        result = await tool.execute(
            instance="fosstodon.org",
            status="Hello world",
        )
        assert result.success is False
        assert "content warning" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_visibility_value_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mastodon_creds: None,
    ) -> None:
        tool = MastodonPostTool()
        result = await tool.execute(
            instance="mastodon.social",
            status="Hello",
            visibility="galaxy",
        )
        assert result.success is False
        assert "invalid visibility" in result.error.lower()


# ---------------------------------------------------------------------------
# End-to-end (mocked Mastodon.py + Redis)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_post_flow_emits_event_and_applies_disclosure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mastodon_creds: None,
    ) -> None:
        """Happy path: creds present, rate-limit clear, Mastodon.py returns
        success → ToolResult.success=True, disclosure applied, PostHog
        event fired with platform='mastodon' + visibility."""
        # Skip Redis path entirely.
        monkeypatch.delenv("REDIS_URL", raising=False)

        # Empty ConfigMap path — falls through to default
        # disclosure_required=True, allowed_visibilities=('unlisted',).
        empty = tmp_path / "empty.yaml"
        empty.write_text("policies: []")
        monkeypatch.setattr(mastodon_tools, "CONFIGMAP_PATH", empty)

        # Mock Mastodon.py.
        fake_status = {
            "id": "111222333",
            "url": "https://mastodon.social/@selvabot/111222333",
        }
        fake_client = MagicMock()
        fake_client.status_post = MagicMock(return_value=fake_status)

        # PostHog spy.
        emitted: list[
            tuple[str, str, str, bool, str]
        ] = []

        def _spy_emit(
            instance: str,
            persona_id: str,
            post_id: str,
            disclosure_applied: bool,
            visibility: str,
        ) -> None:
            emitted.append(
                (instance, persona_id, post_id, disclosure_applied, visibility)
            )

        with (
            patch.object(
                mastodon_tools, "_build_mastodon_client", return_value=fake_client
            ),
            patch.object(
                mastodon_tools, "_emit_outbound_post_event", side_effect=_spy_emit
            ),
        ):
            tool = MastodonPostTool()
            result = await tool.execute(
                instance="mastodon.social",
                status="Hello world",
                visibility="unlisted",
                persona_id="default",
            )

        assert result.success is True
        assert result.data["post_id"] == "111222333"
        assert (
            result.data["post_url"] == "https://mastodon.social/@selvabot/111222333"
        )
        assert result.data["disclosure_applied"] is True
        assert result.data["visibility"] == "unlisted"

        # Disclosure footer was actually included in the submitted body.
        submitted_status = fake_client.status_post.call_args.kwargs["status"]
        assert "madfam.io/ai-disclosure" in submitted_status
        # Visibility passed through to Mastodon.py.
        assert fake_client.status_post.call_args.kwargs["visibility"] == "unlisted"

        # PostHog event fired exactly once with all the right fields.
        assert len(emitted) == 1
        assert emitted[0] == ("mastodon.social", "default", "111222333", True, "unlisted")

    @pytest.mark.asyncio
    async def test_instance_with_disclosure_off_skips_footer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mastodon_creds: None,
    ) -> None:
        """disclosure_required=false on a per-instance entry → footer
        skipped. (Never the default; only when ops explicitly opts out
        because the instance moderators have approved bot accounts.)"""
        monkeypatch.delenv("REDIS_URL", raising=False)
        config = tmp_path / "policy.yaml"
        config.write_text(
            "policies:\n"
            "  - instance: example.com\n"
            "    disclosure_required: false\n"
            "    allowed_visibilities: ['unlisted']"
        )
        monkeypatch.setattr(mastodon_tools, "CONFIGMAP_PATH", config)

        fake_status = {"id": "abc", "url": "https://example.com/@bot/abc"}
        fake_client = MagicMock()
        fake_client.status_post = MagicMock(return_value=fake_status)

        with (
            patch.object(
                mastodon_tools, "_build_mastodon_client", return_value=fake_client
            ),
            patch.object(mastodon_tools, "_emit_outbound_post_event"),
        ):
            tool = MastodonPostTool()
            result = await tool.execute(
                instance="example.com",
                status="Hello world",
            )

        assert result.success is True
        assert result.data["disclosure_applied"] is False
        submitted_status = fake_client.status_post.call_args.kwargs["status"]
        assert "madfam.io/ai-disclosure" not in submitted_status


# ---------------------------------------------------------------------------
# Audience tag + registration
# ---------------------------------------------------------------------------


class TestAudienceAndRegistration:
    def test_mastodon_tool_is_tenant_audience(self) -> None:
        """Tenant swarms must be able to use Mastodon (per their own
        access tokens); platform-only Mastodon ops would be a separate
        tool."""
        tool = MastodonPostTool()
        assert tool.audience == Audience.TENANT

    def test_mastodon_tool_registered_in_get_builtin_tools(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        tools = get_builtin_tools()
        names = {t.name for t in tools}
        assert "mastodon_post" in names


# ---------------------------------------------------------------------------
# OpenAI spec shape
# ---------------------------------------------------------------------------


class TestSchema:
    def test_parameters_schema_shape(self) -> None:
        tool = MastodonPostTool()
        schema = tool.parameters_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"instance", "status"}
        assert "persona_id" in schema["properties"]
        assert "visibility" in schema["properties"]
        assert "content_warning" in schema["properties"]
        assert "sensitive" in schema["properties"]
        # Visibility enum matches Mastodon API.
        assert set(schema["properties"]["visibility"]["enum"]) == {
            "public",
            "unlisted",
            "private",
            "direct",
        }
        # Default visibility is the safe pick.
        assert schema["properties"]["visibility"]["default"] == "unlisted"

    def test_to_openai_spec_includes_function(self) -> None:
        tool = MastodonPostTool()
        spec = tool.to_openai_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "mastodon_post"
