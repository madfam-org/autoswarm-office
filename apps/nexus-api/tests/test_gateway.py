"""Tests for the gateway webhook endpoints.

Tests the GitHub webhook handler including signature verification,
event mapping, and task creation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from nexus_api.routers.gateway import _validate_webhook_url


class TestGitHubWebhookPing:
    """Tests for ping events."""

    async def test_ping_returns_pong(self, client: httpx.AsyncClient) -> None:
        """GitHub ping event returns pong."""
        resp = await client.post(
            "/api/v1/gateway/github",
            content=b"{}",
            headers={"X-GitHub-Event": "ping"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "pong"


class TestGitHubWebhookSignature:
    """Tests for HMAC-SHA256 signature verification."""

    async def test_rejects_invalid_signature(self, client: httpx.AsyncClient) -> None:
        """Invalid signature returns 401 when webhook secret is set."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original_secret = settings.github_webhook_secret
        settings.github_webhook_secret = "test-secret"

        try:
            resp = await client.post(
                "/api/v1/gateway/github",
                content=b'{"action":"opened"}',
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )
            assert resp.status_code == 401
            assert "signature" in resp.json()["detail"].lower()
        finally:
            settings.github_webhook_secret = original_secret

    async def test_accepts_valid_signature(self, client: httpx.AsyncClient) -> None:
        """Valid HMAC-SHA256 signature is accepted."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original_secret = settings.github_webhook_secret
        secret = "test-secret-123"
        settings.github_webhook_secret = secret

        body = json.dumps({"action": "opened"}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        try:
            resp = await client.post(
                "/api/v1/gateway/github",
                content=body,
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Hub-Signature-256": sig,
                },
            )
            assert resp.status_code == 200
        finally:
            settings.github_webhook_secret = original_secret

    async def test_skips_verification_when_no_secret(self, client: httpx.AsyncClient) -> None:
        """When no webhook secret is configured, any payload is accepted."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original_secret = settings.github_webhook_secret
        settings.github_webhook_secret = ""

        try:
            resp = await client.post(
                "/api/v1/gateway/github",
                content=b"{}",
                headers={"X-GitHub-Event": "ping"},
            )
            assert resp.status_code == 200
        finally:
            settings.github_webhook_secret = original_secret


def _make_mock_pool(
    execute_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a mock RedisPool for gateway tests."""
    mock_pool = MagicMock()
    if execute_side_effect:
        mock_pool.execute_with_retry = AsyncMock(side_effect=execute_side_effect)
    else:
        mock_pool.execute_with_retry = AsyncMock(return_value=None)
    return mock_pool


class TestGitHubWebhookEvents:
    """Tests for event type handling and task creation."""

    async def test_ignored_event_returns_ignored(self, client: httpx.AsyncClient) -> None:
        """Unknown event type returns ignored status."""
        body = json.dumps({"action": "completed"}).encode()
        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "deployment"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @patch("nexus_api.routers.gateway.get_redis_pool")
    @patch("nexus_api.routers.gateway.manager")
    async def test_pull_request_opened_creates_task(
        self,
        mock_manager: AsyncMock,
        mock_get_pool: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """PR opened event creates a coding task."""
        mock_pool = _make_mock_pool()
        mock_get_pool.return_value = mock_pool
        mock_manager.broadcast = AsyncMock()

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Fix auth bug",
                "user": {"login": "dev-user"},
                "html_url": "https://github.com/org/repo/pull/42",
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "pull_request"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["tasks_created"] == 1

        # Verify Redis enqueue was attempted (xadd to stream)
        assert mock_pool.execute_with_retry.call_count >= 1
        first_call = mock_pool.execute_with_retry.call_args_list[0]
        assert first_call[0][0] == "xadd"
        assert first_call[0][1] == "selva:task-stream"
        enqueued = json.loads(first_call[0][2]["data"])
        assert enqueued["graph_type"] == "coding"
        assert "PR #42" in enqueued["description"]

        # Verify WebSocket broadcast
        mock_manager.broadcast.assert_called_once()

    @patch("nexus_api.routers.gateway.get_redis_pool")
    @patch("nexus_api.routers.gateway.manager")
    async def test_issue_opened_creates_research_task(
        self,
        mock_manager: AsyncMock,
        mock_get_pool: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """Issue opened event creates a research task."""
        mock_pool = _make_mock_pool()
        mock_get_pool.return_value = mock_pool
        mock_manager.broadcast = AsyncMock()

        payload = {
            "action": "opened",
            "issue": {
                "number": 99,
                "title": "Investigate memory leak",
                "user": {"login": "reporter"},
                "html_url": "https://github.com/org/repo/issues/99",
                "labels": [{"name": "bug"}, {"name": "priority-high"}],
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "issues"},
        )

        assert resp.status_code == 200
        assert resp.json()["tasks_created"] == 1

        # Verify the first enqueue call has research graph type
        first_call = mock_pool.execute_with_retry.call_args_list[0]
        enqueued = json.loads(first_call[0][2]["data"])
        assert enqueued["graph_type"] == "research"
        assert "Issue #99" in enqueued["description"]

    @patch("nexus_api.routers.gateway.get_redis_pool")
    @patch("nexus_api.routers.gateway.manager")
    async def test_check_suite_failure_creates_task(
        self,
        mock_manager: AsyncMock,
        mock_get_pool: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """CI failure event creates a coding task."""
        mock_pool = _make_mock_pool()
        mock_get_pool.return_value = mock_pool
        mock_manager.broadcast = AsyncMock()

        payload = {
            "action": "completed",
            "check_suite": {
                "conclusion": "failure",
                "head_branch": "feat/new-feature",
                "head_sha": "abc123",
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "check_suite"},
        )

        assert resp.status_code == 200
        assert resp.json()["tasks_created"] == 1

    @patch("nexus_api.routers.gateway.get_redis_pool")
    @patch("nexus_api.routers.gateway.manager")
    async def test_check_suite_success_no_task(
        self,
        mock_manager: AsyncMock,
        mock_get_pool: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """Successful CI check does not create a task."""
        mock_pool = _make_mock_pool()
        mock_get_pool.return_value = mock_pool
        mock_manager.broadcast = AsyncMock()

        payload = {
            "action": "completed",
            "check_suite": {
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": "def456",
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "check_suite"},
        )

        assert resp.status_code == 200
        assert resp.json()["tasks_created"] == 0

    @patch("nexus_api.routers.gateway.get_redis_pool")
    @patch("nexus_api.routers.gateway.manager")
    async def test_redis_failure_still_returns_ok(
        self,
        mock_manager: AsyncMock,
        mock_get_pool: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """Task is created even when Redis is unavailable."""
        mock_pool = _make_mock_pool(execute_side_effect=Exception("Connection refused"))
        mock_get_pool.return_value = mock_pool
        mock_manager.broadcast = AsyncMock()

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "title": "Test PR",
                "user": {"login": "dev"},
                "html_url": "https://github.com/org/repo/pull/1",
            },
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/api/v1/gateway/github",
            content=body,
            headers={"X-GitHub-Event": "pull_request"},
        )

        assert resp.status_code == 200
        assert resp.json()["tasks_created"] == 1


def _fake_getaddrinfo_for(ip: str):
    """Return a mock getaddrinfo result list resolving to the given IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


class TestWebhookURLValidation:
    """Tests for the _validate_webhook_url SSRF protection function."""

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_accepts_valid_public_url(self, mock_getaddrinfo: MagicMock) -> None:
        """A valid HTTPS URL resolving to a public IP is returned unchanged."""
        mock_getaddrinfo.return_value = _fake_getaddrinfo_for("93.184.216.34")

        result = _validate_webhook_url("https://example.com/path")

        assert result == "https://example.com/path"
        mock_getaddrinfo.assert_called_once_with("example.com", None)

    def test_rejects_url_exceeding_max_length(self) -> None:
        """URLs longer than 2048 characters are rejected."""
        long_url = "https://example.com/" + "a" * 2040

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url(long_url)

        assert exc_info.value.status_code == 400
        assert "exceeds maximum length" in exc_info.value.detail

    def test_rejects_ftp_scheme(self) -> None:
        """FTP scheme is not allowed."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("ftp://example.com")

        assert exc_info.value.status_code == 400
        assert "scheme must be http or https" in exc_info.value.detail

    def test_rejects_file_scheme(self) -> None:
        """File scheme is not allowed."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("file:///etc/passwd")

        assert exc_info.value.status_code == 400
        assert "scheme must be http or https" in exc_info.value.detail

    def test_rejects_missing_hostname(self) -> None:
        """URLs without a hostname are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("https://")

        assert exc_info.value.status_code == 400
        assert "missing hostname" in exc_info.value.detail

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_rejects_localhost(self, mock_getaddrinfo: MagicMock) -> None:
        """Localhost (127.0.0.1) is blocked as a private/reserved address."""
        mock_getaddrinfo.return_value = _fake_getaddrinfo_for("127.0.0.1")

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("http://localhost:8080")

        assert exc_info.value.status_code == 400
        assert "private/reserved IP" in exc_info.value.detail

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_rejects_private_10_range(self, mock_getaddrinfo: MagicMock) -> None:
        """10.0.0.0/8 private range is blocked."""
        mock_getaddrinfo.return_value = _fake_getaddrinfo_for("10.0.0.1")

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("https://internal.corp.example.com/api")

        assert exc_info.value.status_code == 400
        assert "private/reserved IP" in exc_info.value.detail

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_rejects_private_172_range(self, mock_getaddrinfo: MagicMock) -> None:
        """172.16.0.0/12 private range is blocked."""
        mock_getaddrinfo.return_value = _fake_getaddrinfo_for("172.16.0.1")

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("https://staging.example.com/hook")

        assert exc_info.value.status_code == 400
        assert "private/reserved IP" in exc_info.value.detail

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_rejects_private_192_range(self, mock_getaddrinfo: MagicMock) -> None:
        """192.168.0.0/16 private range is blocked."""
        mock_getaddrinfo.return_value = _fake_getaddrinfo_for("192.168.1.1")

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("https://router.local/callback")

        assert exc_info.value.status_code == 400
        assert "private/reserved IP" in exc_info.value.detail

    @patch("nexus_api.routers.gateway.socket.getaddrinfo")
    def test_rejects_unresolvable_hostname(self, mock_getaddrinfo: MagicMock) -> None:
        """Hostnames that fail DNS resolution are rejected."""
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_url("https://does-not-exist.invalid/path")

        assert exc_info.value.status_code == 400
        assert "could not be resolved" in exc_info.value.detail
