"""Regression tests for the email_inbound webhook hardening (Phase 1, item 15).

The other 14 gateway webhook handlers were hardened in v2.2.x (Discord,
WhatsApp, generic) and Phase 1 (Telegram, Slack, Matrix, Mattermost,
Twilio SMS, DingTalk, Feishu, WeCom, Weixin, BlueBubbles, HomeAssistant)
by routing every handler through the fail-closed ``_require_secret`` /
``_verify_hmac`` pair. ``email_inbound`` was deferred because inbound-
email parse providers (SendGrid, Postmark, Mailgun) do NOT share a
common HMAC contract -- the trust signal here is the upstream-validated
``From:`` address checked against an operator-controlled allow-list.

Pre-hardening bug (the regression these tests pin):

    whitelist = [...]  # empty when GATEWAY_EMAIL_WHITELIST is unset
    if whitelist and sender not in whitelist:  # short-circuits on []
        raise HTTPException(403)
    # ...falls through to run_acp_workflow_task.delay(attacker_url)

An empty allow-list disabled the membership check entirely, letting any
sender on the public internet enqueue an ACP Celery task with an
attacker-supplied URL. The hardened endpoint refuses with 503 in that
configuration.

Post-hardening contract:
- 503 when ``GATEWAY_EMAIL_WHITELIST`` is empty/unset (endpoint disabled).
- 503 when the env var is whitespace-only (no usable entries).
- 401 when the parsed ``From:`` address is not on the allow-list.
- 200 + ``status: success`` on a valid initiate_acp dispatch.
- 200 + ``status: ignored`` when the body has no command (so spam from
  allow-listed senders doesn't error-loop the upstream provider).
- Display-name / case / format normalization so ``"Alice <a@x.com>"``,
  ``a@x.com``, and ``A@X.COM`` all resolve to the same allow-list entry.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from nexus_api.routers.gateway import _parse_email_address, _require_inbound_allowlist

_PATH = "/api/v1/gateway/gateway/email/inbound"


# ---------------------------------------------------------------------------
# Unit tests — _parse_email_address
# ---------------------------------------------------------------------------


class TestParseEmailAddress:
    """The display-name stripper must be tolerant of every RFC 5322 shape
    that SendGrid/Postmark/Mailgun forward verbatim."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("alice@example.com", "alice@example.com"),
            ("Alice <alice@example.com>", "alice@example.com"),
            ('"Alice, Bob" <alice@example.com>', "alice@example.com"),
            ("ALICE@EXAMPLE.COM", "alice@example.com"),
            ("  alice@example.com  ", "alice@example.com"),
            # Display-name-only -- no usable address. ``parseaddr`` is
            # greedy here (returns ``("", "Just")``) but we reject anything
            # without ``@`` so it cannot collide with a malformed allow-list
            # entry.
            ("Just a Name", ""),
            # Empty / falsy
            ("", ""),
            # Malformed -- no ``@``
            ("not-an-email", ""),
        ],
    )
    def test_parses_to_normalized_bare_address(self, raw: str, expected: str) -> None:
        assert _parse_email_address(raw) == expected


# ---------------------------------------------------------------------------
# Unit tests — _require_inbound_allowlist
# ---------------------------------------------------------------------------


class TestRequireInboundAllowlist:
    """Helper-level fail-closed contract."""

    def test_503_when_env_var_unset(self, caplog: pytest.LogCaptureFixture) -> None:
        from fastapi import HTTPException

        caplog.set_level(logging.ERROR, logger="nexus_api.routers.gateway")

        with pytest.raises(HTTPException) as exc:
            _require_inbound_allowlist("GATEWAY_EMAIL_WHITELIST", "", "alice@example.com")

        assert exc.value.status_code == 503
        assert "not configured" in exc.value.detail.lower()
        assert any(
            "GATEWAY_EMAIL_WHITELIST" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        )

    def test_503_when_csv_is_whitespace_only(self, caplog: pytest.LogCaptureFixture) -> None:
        """A CSV like ``" , , "`` has zero usable entries — treat as misconfigured,
        not as 'allow everyone' or as a silent reject-all."""
        from fastapi import HTTPException

        caplog.set_level(logging.ERROR, logger="nexus_api.routers.gateway")

        with pytest.raises(HTTPException) as exc:
            _require_inbound_allowlist(
                "GATEWAY_EMAIL_WHITELIST", " , , ", "alice@example.com"
            )

        assert exc.value.status_code == 503

    def test_401_when_sender_not_on_list(self, caplog: pytest.LogCaptureFixture) -> None:
        from fastapi import HTTPException

        caplog.set_level(logging.WARNING, logger="nexus_api.routers.gateway")

        with pytest.raises(HTTPException) as exc:
            _require_inbound_allowlist(
                "GATEWAY_EMAIL_WHITELIST",
                "alice@example.com,bob@example.com",
                "mallory@evil.com",
            )

        assert exc.value.status_code == 401
        assert "not authorised" in exc.value.detail.lower()

    def test_passes_for_allow_listed_sender(self) -> None:
        # No exception raised
        _require_inbound_allowlist(
            "GATEWAY_EMAIL_WHITELIST",
            "alice@example.com,bob@example.com",
            "alice@example.com",
        )

    def test_allow_list_match_is_case_insensitive(self) -> None:
        """Operators shouldn't have to worry about casing in either env or sender."""
        _require_inbound_allowlist(
            "GATEWAY_EMAIL_WHITELIST",
            "Alice@Example.COM",
            "ALICE@example.com",
        )


# ---------------------------------------------------------------------------
# Integration tests — POST /api/v1/gateway/email/inbound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmailInboundFailClosed:
    """End-to-end contract via the FastAPI test client."""

    async def test_returns_503_when_allowlist_unset(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The pre-hardening regression: empty allow-list MUST NOT fail open
        and dispatch the attacker's URL into Celery."""
        from nexus_api.config import get_settings

        caplog.set_level(logging.ERROR, logger="nexus_api.routers.gateway")
        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = ""

        try:
            resp = await client.post(
                _PATH,
                json={
                    "from": "attacker@evil.com",
                    "text": "initiate_acp: https://attacker.example.com",
                },
            )
            assert resp.status_code == 503, resp.text
            assert "not configured" in resp.json()["detail"].lower()
            assert any(
                "GATEWAY_EMAIL_WHITELIST" in r.getMessage()
                for r in caplog.records
                if r.levelno == logging.ERROR
            )
        finally:
            settings.gateway_email_whitelist = original

    async def test_returns_401_for_unauthorised_sender(
        self, client: httpx.AsyncClient
    ) -> None:
        """Sender not on the configured allow-list → 401, not 200, not 403."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = "alice@example.com,bob@example.com"

        try:
            resp = await client.post(
                _PATH,
                json={
                    "from": "mallory@evil.com",
                    "text": "initiate_acp: https://attacker.example.com",
                },
            )
            assert resp.status_code == 401, resp.text
            assert "not authorised" in resp.json()["detail"].lower()
        finally:
            settings.gateway_email_whitelist = original

    async def test_dispatches_acp_for_allow_listed_sender(
        self, client: httpx.AsyncClient
    ) -> None:
        """Happy path: allow-listed sender + valid initiate_acp command →
        200 + Celery task dispatched."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = "alice@example.com"

        fake_task = MagicMock()
        fake_task.id = "test-task-id-1234"

        try:
            with (
                patch(
                    "nexus_api.routers.gateway.run_acp_workflow_task.delay",
                    return_value=fake_task,
                ) as mock_delay,
                patch(
                    "nexus_api.routers.gateway.memory_store.insert_transcript"
                ) as mock_insert,
                # _validate_webhook_url calls socket.getaddrinfo; stub it to
                # a public IP so the test doesn't require external DNS.
                patch(
                    "nexus_api.routers.gateway.socket.getaddrinfo",
                    return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
                ),
            ):
                resp = await client.post(
                    _PATH,
                    json={
                        "from": "alice@example.com",
                        "text": "initiate_acp: https://example.com/agent",
                    },
                )

                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["status"] == "success"
                assert body["action"] == "acp_triggered"
                assert body["task_id"] == "test-task-id-1234"
                mock_delay.assert_called_once()
                mock_insert.assert_called_once()
        finally:
            settings.gateway_email_whitelist = original

    async def test_strips_display_name_before_allowlist_check(
        self, client: httpx.AsyncClient
    ) -> None:
        """``"Alice <alice@example.com>"`` MUST match the bare allow-list entry.
        Display names are attacker-controllable and must NOT participate in
        the trust decision -- but they also must not cause false rejects of
        legitimate mail from allow-listed senders."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = "alice@example.com"

        fake_task = MagicMock()
        fake_task.id = "test-task-id-display-name"

        try:
            with (
                patch(
                    "nexus_api.routers.gateway.run_acp_workflow_task.delay",
                    return_value=fake_task,
                ),
                patch("nexus_api.routers.gateway.memory_store.insert_transcript"),
                patch(
                    "nexus_api.routers.gateway.socket.getaddrinfo",
                    return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
                ),
            ):
                resp = await client.post(
                    _PATH,
                    json={
                        "From": "Alice Example <Alice@Example.COM>",
                        "TextBody": "initiate_acp: https://example.com/agent",
                    },
                )

                assert resp.status_code == 200, resp.text
                assert resp.json()["status"] == "success"
        finally:
            settings.gateway_email_whitelist = original

    async def test_returns_ignored_when_no_command_in_body(
        self, client: httpx.AsyncClient
    ) -> None:
        """Allow-listed sender + body without initiate_acp → 200 ``ignored``,
        not an error. Otherwise the upstream provider would error-loop on
        every out-of-band reply / vacation auto-responder."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = "alice@example.com"

        try:
            resp = await client.post(
                _PATH,
                json={
                    "from": "alice@example.com",
                    "text": "Just saying hi, no command here.",
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "ignored"
        finally:
            settings.gateway_email_whitelist = original

    async def test_spoofed_display_name_does_not_grant_access(
        self, client: httpx.AsyncClient
    ) -> None:
        """``"alice@example.com" <mallory@evil.com>`` MUST be rejected. The
        bare address (mallory@evil.com) is what counts; the display-name
        portion is attacker-controllable."""
        from nexus_api.config import get_settings

        settings = get_settings()
        original = settings.gateway_email_whitelist
        settings.gateway_email_whitelist = "alice@example.com"

        try:
            resp = await client.post(
                _PATH,
                json={
                    "from": '"alice@example.com" <mallory@evil.com>',
                    "text": "initiate_acp: https://attacker.example.com",
                },
            )
            assert resp.status_code == 401, resp.text
        finally:
            settings.gateway_email_whitelist = original
