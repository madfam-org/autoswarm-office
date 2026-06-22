"""Tests for POST /api/v1/health/sentry-probe (Phase 0 Sentry wiring proof)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


class TestSentryProbe:
    async def test_sentry_probe_requires_auth(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/api/v1/health/sentry-probe")
        assert resp.status_code == 401

    async def test_sentry_probe_503_when_dsn_unset(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        resp = await client.post(
            "/api/v1/health/sentry-probe",
            headers={"Authorization": "Bearer dev-bypass"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "sentry_not_configured"

    async def test_sentry_probe_captures_when_configured(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.io/1")

        mock_capture = MagicMock(return_value="abc123event")
        with patch("sentry_sdk.capture_exception", mock_capture):
            resp = await client.post(
                "/api/v1/health/sentry-probe",
                headers={"Authorization": "Bearer dev-bypass"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["captured"] is True
        assert body["event_id"] == "abc123event"
        mock_capture.assert_called_once()
