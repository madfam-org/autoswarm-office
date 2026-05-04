"""Tests for the provider balance probe cron.

Covers:
- DeepInfra API path (200 with balance field → source='api')
- DeepInfra API failure (404, JSON shape miss, network) → fallback to estimation
- Estimation path with operator-set MAX_KNOWN_BALANCE → source='estimated'
- Estimation path without max-known → source='unknown'
- Threshold classification (critical fires PostHog event)
- Redis writeback success + failure
- Aggregate run() returns full payload
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selva_workers.jobs import provider_balance_probe as probe


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip provider env vars so each test starts from a known state."""
    for var in (
        "DEEPINFRA_API_KEY",
        "ANTHROPIC_MAX_KNOWN_BALANCE_USD",
        "OPENAI_MAX_KNOWN_BALANCE_USD",
        "DEEPINFRA_MAX_KNOWN_BALANCE_USD",
        "REDIS_URL",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# classify_alert (mirrors route logic)
# ---------------------------------------------------------------------------


class TestClassifyAlert:
    def test_unknown_source_critical(self) -> None:
        assert probe.classify_alert(100.0, "unknown") == "critical"

    def test_negative_balance_critical(self) -> None:
        assert probe.classify_alert(-1.0, "api") == "critical"

    def test_at_critical_threshold(self) -> None:
        assert probe.classify_alert(5.0, "api") == "critical"

    def test_low_band(self) -> None:
        assert probe.classify_alert(25.0, "api") == "low"

    def test_ok_band(self) -> None:
        assert probe.classify_alert(500.0, "api") == "ok"


# ---------------------------------------------------------------------------
# DeepInfra API probe
# ---------------------------------------------------------------------------


class TestDeepInfraProbe:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self) -> None:
        result = await probe._probe_deepinfra_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_balance_field_present_returns_api_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"credit_balance": 42.50})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe._probe_deepinfra_api()

        assert result is not None
        assert result["source"] == "api"
        assert result["balance_usd"] == 42.50

    @pytest.mark.asyncio
    async def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test_key")

        mock_resp = MagicMock(status_code=404)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe._probe_deepinfra_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_unrecognised_response_shape_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """200 OK but no balance field — defensive bail to None."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test_key")

        mock_resp = MagicMock(status_code=200)
        mock_resp.json = MagicMock(return_value={"some_other_field": "x"})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe._probe_deepinfra_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_network_failure_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Request raises → degrade to None, never propagates."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test_key")

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("net down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe._probe_deepinfra_api()
        assert result is None


# ---------------------------------------------------------------------------
# Estimation path
# ---------------------------------------------------------------------------


class TestEstimationPath:
    @pytest.mark.asyncio
    async def test_no_max_known_returns_none(self) -> None:
        """Operator hasn't configured the max — bail to None so the
        aggregate routes mark it 'unknown'."""
        # No env var, no posthog client → None.
        result = await probe._estimate_via_posthog_usage("anthropic")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_max_known_balance_returns_estimated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_MAX_KNOWN_BALANCE_USD", "300")

        # Fake a configured PostHog client so the function progresses past
        # the early-return guard.
        fake_module = MagicMock(_client=MagicMock())
        with patch.dict(
            "sys.modules",
            {"nexus_api": MagicMock(analytics=fake_module)},
        ):
            with patch.object(probe, "_max_known_balance", return_value=300.0):
                result = await probe._estimate_via_posthog_usage("anthropic")

        assert result is not None
        assert result["source"] == "estimated"
        assert result["balance_usd"] == 300.0

    def test_max_known_balance_reads_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_MAX_KNOWN_BALANCE_USD", "150.50")
        assert probe._max_known_balance("anthropic") == 150.50

    def test_max_known_balance_bad_value_falls_back_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_MAX_KNOWN_BALANCE_USD", "not-a-number")
        assert probe._max_known_balance("anthropic") == 0.0


# ---------------------------------------------------------------------------
# probe_provider — aggregate per-provider entrypoint
# ---------------------------------------------------------------------------


class TestProbeProvider:
    @pytest.mark.asyncio
    async def test_no_signal_returns_unknown(self) -> None:
        """No env, no API → unknown / -1.0."""
        result = await probe.probe_provider("anthropic")
        assert result["source"] == "unknown"
        assert result["balance_usd"] == -1.0
        assert result["currency"] == "USD"
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_uses_deepinfra_api_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPINFRA_API_KEY", "x")
        with patch.object(
            probe,
            "_probe_deepinfra_api",
            AsyncMock(return_value={"balance_usd": 75.0, "source": "api"}),
        ):
            result = await probe.probe_provider("deepinfra")
        assert result["source"] == "api"
        assert result["balance_usd"] == 75.0


# ---------------------------------------------------------------------------
# Redis writeback
# ---------------------------------------------------------------------------


class TestRedisWriteback:
    @pytest.mark.asyncio
    async def test_no_redis_url_returns_false(self) -> None:
        ok = await probe._write_to_redis({"anthropic": {"x": "y"}})
        assert ok is False

    @pytest.mark.asyncio
    async def test_writes_with_30min_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        mock_redis = MagicMock()
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        payload = {"anthropic": {"balance_usd": 50.0}}
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            ok = await probe._write_to_redis(payload)

        assert ok is True
        mock_redis.set.assert_awaited_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0] == probe.REDIS_BALANCE_KEY
        assert json.loads(args[1])["anthropic"]["balance_usd"] == 50.0
        assert kwargs["ex"] == 30 * 60


# ---------------------------------------------------------------------------
# Full run() flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRun:
    async def test_run_returns_summary_for_each_provider(self) -> None:
        """The aggregate run() probes all KNOWN_PROVIDERS and returns
        a payload keyed by provider name."""
        # No creds + no max-known → all unknown.
        result = await probe.run()
        assert "providers" in result
        assert set(result["providers"].keys()) == set(probe.KNOWN_PROVIDERS)
        for entry in result["providers"].values():
            assert entry["source"] == "unknown"
            assert entry["alert"] == "critical"

    async def test_run_fires_critical_event_when_balance_low(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When a provider classifies as critical, the PostHog
        ``provider_balance.critical`` event fires."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "x")

        emitted: list[Any] = []

        def _spy_emit(provider: str, entry: dict[str, Any]) -> None:
            emitted.append((provider, entry))

        with (
            patch.object(
                probe,
                "_probe_deepinfra_api",
                AsyncMock(return_value={"balance_usd": 2.0, "source": "api"}),
            ),
            patch.object(probe, "_emit_critical_event", side_effect=_spy_emit),
            patch.object(probe, "_write_to_redis", AsyncMock(return_value=True)),
        ):
            result = await probe.run()

        # DeepInfra entry classified critical and emitted.
        assert result["providers"]["deepinfra"]["alert"] == "critical"
        assert any(p == "deepinfra" for p, _ in emitted)
