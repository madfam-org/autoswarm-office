"""Gate tests for SendEmailTool / SendMarketingEmailTool voice-mode enforcement.

These tests run without a real nexus-api by monkeypatching the
``_fetch_voice_mode`` and ``_fetch_tenant_identity`` helpers. They
verify:

- When voice_mode is None the tool refuses to send.
- When the tenant identity is None the tool refuses to send (defense
  against an attacker calling without server-side identity configured).
- When agent_identified, SPF/DKIM/DMARC failure blocks the send.
- When the mode is set and alignment passes, the send proceeds.
- The From header matches the selected mode's identity builder and is
  resolved EXCLUSIVELY from the server identity dict — LLM-supplied
  user_email / user_name / agent_slug kwargs are ignored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from selva_tools.builtins import email_tools, marketing_tools
from selva_tools.builtins._spf_check import SpfResult

# Stable server-resolved identity used across the success-path tests.
# These values are what the LLM CANNOT override — every send uses them.
_TENANT_IDENTITY = {
    "user_email": "ada@example.com",
    "user_name": "Ada",
    "org_name": "MADFAM",
}


@pytest.mark.asyncio
async def test_send_email_blocked_when_voice_mode_not_set() -> None:
    tool = email_tools.SendEmailTool()
    with patch.object(email_tools, "_fetch_voice_mode", AsyncMock(return_value=None)):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>x</p>",
            org_id="org-1",
        )
    assert result.success is False
    assert "voice mode" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_send_email_blocked_when_tenant_identity_unconfigured() -> None:
    """Voice mode set but identity lookup returns None → refuse."""
    tool = email_tools.SendEmailTool()
    with (
        patch.object(
            email_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
        ),
        patch.object(email_tools, "_fetch_tenant_identity", AsyncMock(return_value=None)),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>x</p>",
            org_id="org-1",
        )
    assert result.success is False
    assert "identity" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_send_email_agent_identified_blocked_on_spf_fail() -> None:
    tool = email_tools.SendEmailTool()
    bad_alignment = SpfResult(
        domain="selva.town",
        spf_ok=False,
        dkim_ok=False,
        dmarc_ok=False,
        status="fail",
        reason="Missing SPF",
    )
    with (
        patch.object(email_tools, "_fetch_voice_mode", AsyncMock(return_value="agent_identified")),
        patch.object(
            email_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
        ),
        patch.object(email_tools, "check_alignment", return_value=bad_alignment),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>x</p>",
            org_id="org-1",
            agent_role="sales",
        )
    assert result.success is False
    assert "alignment" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_send_email_dyad_mode_sends_with_co_branded_from() -> None:
    tool = email_tools.SendEmailTool()
    captured: dict = {}

    class _MockResp:
        status_code = 201

        def json(self) -> dict:
            return {"id": "msg-123"}

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _MockResp:
            captured["payload"] = json
            return _MockResp()

    with (
        patch.object(
            email_tools,
            "_fetch_voice_mode",
            AsyncMock(return_value="dyad_selva_plus_user"),
        ),
        patch.object(
            email_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
        ),
        patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _MockClient()),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>Hello</p>",
            org_id="org-1",
        )
    assert result.success is True, result.error
    payload = captured["payload"]
    assert "Selva on behalf of Ada" in payload["from"]
    assert payload["reply_to"] == "ada@example.com"


@pytest.mark.asyncio
async def test_send_email_ignores_llm_supplied_identity_kwargs() -> None:
    """An LLM-supplied user_email/user_name MUST NOT influence the From: header.

    This is the spoofing fix — even if a prompt-injected LLM passes
    ``user_email="ceo@target.com"``, the tool reads identity from the
    server-side dict only.
    """
    tool = email_tools.SendEmailTool()
    captured: dict = {}

    class _MockResp:
        status_code = 201

        def json(self) -> dict:
            return {"id": "msg-spoof-test"}

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _MockResp:
            captured["payload"] = json
            return _MockResp()

    with (
        patch.object(
            email_tools,
            "_fetch_voice_mode",
            AsyncMock(return_value="dyad_selva_plus_user"),
        ),
        patch.object(
            email_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
        ),
        patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _MockClient()),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>Hello</p>",
            org_id="org-1",
            # Hostile inputs the LLM might try to inject:
            user_email="ceo@target-corp.com",
            user_name="Target CEO",
            agent_slug="ceo",
            agent_display_name="Target CEO",
            org_name="Target Corp",
        )
    assert result.success is True, result.error
    payload = captured["payload"]
    # From: header MUST reflect the server-resolved Ada identity, NOT
    # the LLM-supplied "ceo@target-corp.com". In dyad mode the address
    # part is selva_from; the LLM-supplied user_email must NOT leak
    # into From or Reply-To.
    assert "Selva on behalf of Ada" in payload["from"]
    assert "ceo@target-corp.com" not in payload["from"]
    assert "Target CEO" not in payload["from"]
    # Reply-To MUST be the server-resolved user_email, not the LLM input.
    assert payload["reply_to"] == "ada@example.com"
    assert payload["reply_to"] != "ceo@target-corp.com"


@pytest.mark.asyncio
async def test_send_email_agent_identified_passes_when_aligned() -> None:
    tool = email_tools.SendEmailTool()
    good_alignment = SpfResult(
        domain="selva.town",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        status="pass",
        reason="aligned",
    )
    captured: dict = {}

    class _MockResp:
        status_code = 201

        def json(self) -> dict:
            return {"id": "msg-aid-123"}

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _MockResp:
            captured["payload"] = json
            return _MockResp()

    with (
        patch.object(
            email_tools,
            "_fetch_voice_mode",
            AsyncMock(return_value="agent_identified"),
        ),
        patch.object(
            email_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
        ),
        patch.object(email_tools, "check_alignment", return_value=good_alignment),
        patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _MockClient()),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>x</p>",
            org_id="org-1",
            agent_role="growth",  # maps to growth-agent slug
        )
    assert result.success is True, result.error
    payload = captured["payload"]
    # Slug came from the server-side allow-list, not from any LLM input.
    assert "growth-agent@selva.town" in payload["from"]
    # agent_identified does NOT inject Reply-To (no user mailbox).
    assert "reply_to" not in payload


@pytest.mark.asyncio
async def test_send_email_unknown_agent_role_falls_back_to_default() -> None:
    """Hostile / unknown agent_role MUST fall back to the default slug, never raw text."""
    tool = email_tools.SendEmailTool()
    good_alignment = SpfResult(
        domain="selva.town",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        status="pass",
        reason="aligned",
    )
    captured: dict = {}

    class _MockResp:
        status_code = 201

        def json(self) -> dict:
            return {"id": "msg-fallback"}

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _MockResp:
            captured["payload"] = json
            return _MockResp()

    with (
        patch.object(
            email_tools, "_fetch_voice_mode", AsyncMock(return_value="agent_identified")
        ),
        patch.object(
            email_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
        ),
        patch.object(email_tools, "check_alignment", return_value=good_alignment),
        patch.object(email_tools.httpx, "AsyncClient", lambda timeout=10: _MockClient()),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to="dest@example.com",
            subject="Hi",
            html="<p>x</p>",
            org_id="org-1",
            agent_role="ceo@target.com",  # blatantly hostile
        )
    assert result.success is True, result.error
    payload = captured["payload"]
    # Falls back to the default 'support' slug — never the LLM string.
    assert "support-agent@selva.town" in payload["from"]
    assert "ceo" not in payload["from"]
    assert "target.com" not in payload["from"]


@pytest.mark.asyncio
async def test_marketing_email_refuses_without_voice_mode() -> None:
    tool = marketing_tools.SendMarketingEmailTool()
    with (
        patch.object(marketing_tools, "_fetch_voice_mode", AsyncMock(return_value=None)),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to_email="dest@example.com",
            subject="Hi",
            body_html="<p>body</p>",
            org_id="org-1",
        )
    assert result.success is False
    assert "voice mode" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_marketing_email_refuses_without_tenant_identity() -> None:
    tool = marketing_tools.SendMarketingEmailTool()
    with (
        patch.object(
            marketing_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
        ),
        patch.object(
            marketing_tools, "_fetch_tenant_identity", AsyncMock(return_value=None)
        ),
        patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
    ):
        result = await tool.execute(
            to_email="dest@example.com",
            subject="Hi",
            body_html="<p>body</p>",
            org_id="org-1",
        )
    assert result.success is False
    assert "identity" in (result.error or "").lower()
