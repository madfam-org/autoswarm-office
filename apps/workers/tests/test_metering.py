"""Tests for inference metering."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMeterInferenceCall:
    """meter_inference_call sends usage data to the billing API."""

    @pytest.mark.asyncio
    async def test_posts_usage_to_billing_endpoint(self) -> None:
        mock_response = MagicMock(status_code=201)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "selva_workers.metering.get_settings",
                return_value=MagicMock(nexus_api_url="http://test:4300"),
            ),
            patch("selva_workers.metering.httpx.AsyncClient", return_value=mock_client),
        ):
            from selva_workers.metering import meter_inference_call

            await meter_inference_call(
                usage={"input_tokens": 100, "output_tokens": 50},
                provider="anthropic",
                model="claude-sonnet-4-6",
                agent_id="agent-1",
                task_id="task-1",
                org_id="test-org",
            )

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "http://test:4300/api/v1/billing/record"
            payload = call_args[1]["json"]
            assert payload["amount"] == 150
            assert payload["provider"] == "anthropic"
            assert payload["model"] == "claude-sonnet-4-6"
            assert payload["org_id"] == "test-org"

    @pytest.mark.asyncio
    async def test_sends_worker_auth_headers(self) -> None:
        """The billing endpoint is authenticated (RFC 0034 P0): an unauthenticated
        POST is silently 401-dropped, so metering must send worker auth headers
        with the tenant org declared."""
        mock_response = MagicMock(status_code=201)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "selva_workers.metering.get_settings",
                return_value=MagicMock(nexus_api_url="http://test:4300"),
            ),
            patch("selva_workers.metering.httpx.AsyncClient", return_value=mock_client),
            patch(
                "selva_workers.metering.get_worker_auth_headers",
                return_value={
                    "Authorization": "Bearer worker-token",
                    "X-Selva-Tenant-Org": "test-org",
                },
            ) as mock_headers,
        ):
            from selva_workers.metering import meter_inference_call

            await meter_inference_call(
                usage={"input_tokens": 1, "output_tokens": 1},
                provider="anthropic",
                model="claude-sonnet-4-6",
                org_id="test-org",
            )

            mock_headers.assert_called_once_with(org_id="test-org")
            headers = mock_client.post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer worker-token"
            assert headers["X-Selva-Tenant-Org"] == "test-org"

    @pytest.mark.asyncio
    async def test_skips_when_zero_tokens(self) -> None:
        with patch("selva_workers.metering.httpx.AsyncClient") as mock_cls:
            from selva_workers.metering import meter_inference_call

            await meter_inference_call(
                usage={"input_tokens": 0, "output_tokens": 0},
                provider="anthropic",
                model="test",
            )
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_empty_usage(self) -> None:
        with patch("selva_workers.metering.httpx.AsyncClient") as mock_cls:
            from selva_workers.metering import meter_inference_call

            await meter_inference_call(
                usage={},
                provider="anthropic",
                model="test",
            )
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_raise_on_http_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "selva_workers.metering.get_settings",
                return_value=MagicMock(nexus_api_url="http://test:4300"),
            ),
            patch("selva_workers.metering.httpx.AsyncClient", return_value=mock_client),
        ):
            from selva_workers.metering import meter_inference_call

            # Should not raise
            await meter_inference_call(
                usage={"input_tokens": 10, "output_tokens": 5},
                provider="anthropic",
                model="test",
            )

    @pytest.mark.asyncio
    async def test_logs_warning_on_non_201_status(self) -> None:
        mock_response = MagicMock(status_code=400, text="Bad request")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "selva_workers.metering.get_settings",
                return_value=MagicMock(nexus_api_url="http://test:4300"),
            ),
            patch("selva_workers.metering.httpx.AsyncClient", return_value=mock_client),
            patch("selva_workers.metering.logger") as mock_logger,
        ):
            from selva_workers.metering import meter_inference_call

            await meter_inference_call(
                usage={"input_tokens": 10, "output_tokens": 5},
                provider="anthropic",
                model="test",
            )
            mock_logger.warning.assert_called()


class TestCallLlmMetering:
    """call_llm meters usage after successful inference."""

    @pytest.mark.asyncio
    async def test_meters_usage_after_successful_call(self) -> None:
        mock_response = MagicMock(
            content="Hello",
            provider="anthropic",
            model="claude-sonnet-4-6",
            usage={"input_tokens": 50, "output_tokens": 25},
        )
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=mock_response)

        with patch(
            "selva_workers.metering.meter_inference_call",
            new_callable=AsyncMock,
        ) as mock_meter:
            from selva_workers.inference import call_llm

            result = await call_llm(
                mock_router,
                [{"role": "user", "content": "hi"}],
                agent_id="agent-1",
                task_id="task-1",
                org_id="test-org",
            )
            assert result == "Hello"
            mock_meter.assert_called_once_with(
                usage={"input_tokens": 50, "output_tokens": 25},
                provider="anthropic",
                model="claude-sonnet-4-6",
                agent_id="agent-1",
                task_id="task-1",
                org_id="test-org",
            )

    @pytest.mark.asyncio
    async def test_skips_metering_when_no_usage(self) -> None:
        mock_response = MagicMock(
            content="Hello",
            provider="anthropic",
            model="test",
            usage={},
        )
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=mock_response)

        with patch(
            "selva_workers.metering.meter_inference_call",
            new_callable=AsyncMock,
        ) as mock_meter:
            from selva_workers.inference import call_llm

            result = await call_llm(mock_router, [{"role": "user", "content": "hi"}])
            assert result == "Hello"
            mock_meter.assert_not_called()
