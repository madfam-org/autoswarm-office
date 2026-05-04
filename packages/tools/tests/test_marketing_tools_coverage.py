"""Phase 2 critical-path coverage for ``selva_tools.builtins.marketing_tools``.

Targets the gaps left after ``test_email_voice_mode_gate.py``:

- ``_sanitize_email_html`` allow-list parser (drops scripts, on-handlers,
  javascript: URLs; preserves allow-listed inline styles).
- ``_inject_utm`` URL helper (no-op on empty, preserves existing query
  string, overrides existing utm_* params).
- ``_build_madfam_email_html`` template wrapper (with/without CTA,
  product line, plain-text → HTML conversion).
- ``SendMarketingEmailTool.execute`` happy path with mocked Resend
  call; verifies UTM injection in href, MADFAM template wrapping,
  List-Unsubscribe header, and the dyad-mode reply_to wiring.
- Negative paths: missing to/subject (400), invalid email format,
  Resend API key missing, Resend HTTP error.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from selva_tools.builtins import marketing_tools
from selva_tools.builtins._spf_check import SpfResult

_TENANT_IDENTITY = {
    "user_email": "ada@example.com",
    "user_name": "Ada",
    "org_name": "MADFAM",
}


# ---------------------------------------------------------------------------
# _sanitize_email_html — bleach-backed allow-list
# ---------------------------------------------------------------------------


class TestSanitizeEmailHtml:
    def test_strips_script_tag(self) -> None:
        out = marketing_tools._sanitize_email_html("<p>hi</p><script>alert(1)</script>")
        # bleach with strip=True removes the <script> tag itself; the text
        # content survives but is no longer executable HTML.
        assert "<script" not in out
        assert "</script" not in out
        assert "<p>hi</p>" in out

    def test_strips_iframe(self) -> None:
        out = marketing_tools._sanitize_email_html("<iframe src='x'></iframe><p>ok</p>")
        assert "<iframe" not in out

    def test_drops_javascript_url_in_anchor(self) -> None:
        out = marketing_tools._sanitize_email_html('<a href="javascript:alert(1)">click</a>')
        # href stripped — text remains
        assert "javascript:" not in out

    def test_drops_onclick_attribute(self) -> None:
        out = marketing_tools._sanitize_email_html('<a href="https://x.io" onclick="evil()">x</a>')
        assert "onclick" not in out
        assert "evil" not in out

    def test_preserves_allowed_tags_and_inline_style(self) -> None:
        out = marketing_tools._sanitize_email_html(
            '<p style="color:#333;font-size:14px">hi</p>'
        )
        assert "<p" in out
        # Style is allowed
        assert "color" in out

    def test_preserves_safe_anchor(self) -> None:
        out = marketing_tools._sanitize_email_html('<a href="https://madfam.io">x</a>')
        assert "https://madfam.io" in out
        assert "<a" in out


# ---------------------------------------------------------------------------
# _inject_utm — URL helper
# ---------------------------------------------------------------------------


class TestInjectUtm:
    def test_empty_url_is_returned_as_is(self) -> None:
        assert marketing_tools._inject_utm("") == ""

    def test_adds_utm_params_to_bare_url(self) -> None:
        out = marketing_tools._inject_utm("https://madfam.io/landing", campaign="launch")
        assert "utm_source=selva" in out
        assert "utm_medium=email" in out
        assert "utm_campaign=launch" in out

    def test_overrides_existing_utm_campaign(self) -> None:
        out = marketing_tools._inject_utm(
            "https://x.io/?utm_campaign=old&keep=1", campaign="new"
        )
        assert "utm_campaign=new" in out
        # Non-utm param preserved
        assert "keep=1" in out

    def test_default_campaign_is_agent_outreach(self) -> None:
        out = marketing_tools._inject_utm("https://x.io")
        assert "utm_campaign=agent_outreach" in out


# ---------------------------------------------------------------------------
# _build_madfam_email_html — template wrapper
# ---------------------------------------------------------------------------


class TestBuildMadfamEmailHtml:
    def test_wraps_plain_text_in_paragraph(self) -> None:
        out = marketing_tools._build_madfam_email_html(
            "First paragraph.\n\nSecond paragraph.", to_email="x@example.com"
        )
        assert "<p" in out
        assert "First paragraph." in out
        assert "Second paragraph." in out
        assert "MADFAM" in out
        assert "Cancelar suscripción" in out

    def test_passes_through_html_body(self) -> None:
        out = marketing_tools._build_madfam_email_html(
            "<div>already HTML</div>", to_email="x@example.com"
        )
        # Body is passed through verbatim because '<' is detected
        assert "<div>already HTML</div>" in out

    def test_includes_cta_block_when_url_provided(self) -> None:
        out = marketing_tools._build_madfam_email_html(
            "body", cta_url="https://madfam.io/x", cta_text="Click", to_email="x@example.com"
        )
        assert 'href="https://madfam.io/x"' in out
        assert "Click" in out

    def test_omits_cta_block_when_no_url(self) -> None:
        out = marketing_tools._build_madfam_email_html("body", to_email="x@example.com")
        # No CTA href present
        assert 'href="https://madfam.io/x"' not in out

    def test_includes_product_line_when_product_name_set(self) -> None:
        out = marketing_tools._build_madfam_email_html(
            "body", product_name="Selva", to_email="x@example.com"
        )
        assert "Selva" in out

    def test_unsubscribe_link_includes_email(self) -> None:
        out = marketing_tools._build_madfam_email_html("body", to_email="user@x.io")
        assert "user@x.io" in out
        assert "unsubscribe" in out


# ---------------------------------------------------------------------------
# SendMarketingEmailTool.execute branches
# ---------------------------------------------------------------------------


class _MockResp:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {"id": "msg-mkt-1"}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "HTTP error", request=None, response=httpx.Response(self.status_code)  # type: ignore[arg-type]
            )


class _MockClient:
    def __init__(self, captured: dict, resp: _MockResp | None = None) -> None:
        self._captured = captured
        self._resp = resp or _MockResp()

    async def __aenter__(self) -> _MockClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _MockResp:
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["payload"] = json
        return self._resp


@pytest.mark.asyncio
class TestSendMarketingEmailTool:
    async def test_missing_to_email_returns_error(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        result = await tool.execute(
            to_email="", subject="hi", body_html="<p>x</p>", org_id="o-1"
        )
        assert result.success is False
        assert "required" in (result.error or "").lower()

    async def test_missing_subject_returns_error(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        result = await tool.execute(
            to_email="user@x.io", subject="", body_html="<p>x</p>", org_id="o-1"
        )
        assert result.success is False
        assert "required" in (result.error or "").lower()

    async def test_invalid_email_format_rejected(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        result = await tool.execute(
            to_email="not-an-email", subject="hi", body_html="<p>x</p>", org_id="o-1"
        )
        assert result.success is False
        assert "invalid email" in (result.error or "").lower()

    async def test_missing_org_id_returns_error(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        result = await tool.execute(
            to_email="user@x.io", subject="hi", body_html="<p>x</p>", org_id=""
        )
        assert result.success is False
        assert "org_id" in (result.error or "").lower()

    async def test_dyad_mode_invalid_user_email_rejected(self) -> None:
        """Identity returns malformed user_email → reject."""
        tool = marketing_tools.SendMarketingEmailTool()
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                marketing_tools,
                "_fetch_tenant_identity",
                AsyncMock(
                    return_value={
                        "user_email": "not-email",
                        "user_name": "X",
                        "org_name": "Y",
                    }
                ),
            ),
        ):
            result = await tool.execute(
                to_email="dest@example.com",
                subject="hi",
                body_html="<p>x</p>",
                org_id="o-1",
            )
        assert result.success is False
        assert "mailbox" in (result.error or "").lower()

    async def test_agent_identified_blocked_on_alignment_fail(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        bad_alignment = SpfResult(
            domain="selva.town", spf_ok=False, dkim_ok=False, dmarc_ok=False,
            status="fail", reason="missing"
        )
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode", AsyncMock(return_value="agent_identified")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
            ),
            patch.object(marketing_tools, "check_alignment", return_value=bad_alignment),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to_email="dest@example.com",
                subject="hi",
                body_html="<p>x</p>",
                org_id="o-1",
                agent_role="sales",
            )
        assert result.success is False
        assert "alignment" in (result.error or "").lower()

    async def test_resend_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode", AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity", AsyncMock(return_value=_TENANT_IDENTITY)
            ),
        ):
            result = await tool.execute(
                to_email="dest@example.com",
                subject="hi",
                body_html="<p>x</p>",
                org_id="o-1",
            )
        assert result.success is False
        assert "RESEND_API_KEY" in (result.error or "")

    async def test_dyad_mode_full_send_with_template_and_utm(self) -> None:
        """Happy path: dyad_selva_plus_user mode, MADFAM template, UTM injection."""
        tool = marketing_tools.SendMarketingEmailTool()
        captured: dict = {}
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode",
                AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity",
                AsyncMock(return_value=_TENANT_IDENTITY)
            ),
            patch.object(
                marketing_tools.httpx, "AsyncClient",
                lambda timeout=15.0: _MockClient(captured)
            ),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to_email="lead@target.io",
                subject="Discover Selva",
                body_html='Body content <a href="https://madfam.io/landing">go</a>',
                org_id="o-1",
                utm_campaign="cold_outreach",
            )
        assert result.success is True, result.error
        payload = captured["payload"]
        # MADFAM template wraps the body
        assert "MADFAM" in payload["html"]
        # UTM was injected into the href
        assert "utm_campaign=cold_outreach" in payload["html"]
        assert "utm_source=selva" in payload["html"]
        # Reply-To wired to the resolved user_email
        assert payload["reply_to"] == "ada@example.com"
        # CAN-SPAM: List-Unsubscribe header always present
        assert "List-Unsubscribe" in payload["headers"]
        # Recipient masked into unsubscribe link
        assert "lead@target.io" in payload["headers"]["List-Unsubscribe"]

    async def test_dyad_mode_template_off_skips_madfam_wrap(self) -> None:
        """template='none' kwarg should suppress the MADFAM wrap."""
        tool = marketing_tools.SendMarketingEmailTool()
        captured: dict = {}
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode",
                AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity",
                AsyncMock(return_value=_TENANT_IDENTITY)
            ),
            patch.object(
                marketing_tools.httpx, "AsyncClient",
                lambda timeout=15.0: _MockClient(captured)
            ),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to_email="lead@target.io",
                subject="x",
                body_html="<p>raw body</p>",
                org_id="o-1",
                template="none",
            )
        assert result.success is True, result.error
        # template='none' bypasses the MADFAM banner wrap entirely.
        assert "Tecnología que potencia tu negocio" not in captured["payload"]["html"]
        assert "<p>raw body</p>" in captured["payload"]["html"]

    async def test_resend_http_error_returns_error(self) -> None:
        tool = marketing_tools.SendMarketingEmailTool()
        captured: dict = {}
        bad_resp = _MockResp(status_code=500, body={"error": "internal"})

        def _client_factory(timeout: float = 15.0) -> _MockClient:
            return _MockClient(captured, bad_resp)

        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode",
                AsyncMock(return_value="dyad_selva_plus_user")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity",
                AsyncMock(return_value=_TENANT_IDENTITY)
            ),
            patch.object(marketing_tools.httpx, "AsyncClient", _client_factory),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to_email="lead@target.io",
                subject="hi",
                body_html="<p>x</p>",
                org_id="o-1",
            )
        assert result.success is False
        assert "send failed" in (result.error or "").lower()

    async def test_agent_identified_no_reply_to_for_agent_mode(self) -> None:
        """agent_identified mode does NOT set reply_to (replies route to agent slug)."""
        tool = marketing_tools.SendMarketingEmailTool()
        good_alignment = SpfResult(
            domain="selva.town", spf_ok=True, dkim_ok=True, dmarc_ok=True,
            status="pass", reason="aligned"
        )
        captured: dict = {}
        with (
            patch.object(
                marketing_tools, "_fetch_voice_mode",
                AsyncMock(return_value="agent_identified")
            ),
            patch.object(
                marketing_tools, "_fetch_tenant_identity",
                AsyncMock(return_value=_TENANT_IDENTITY)
            ),
            patch.object(marketing_tools, "check_alignment", return_value=good_alignment),
            patch.object(
                marketing_tools.httpx, "AsyncClient",
                lambda timeout=15.0: _MockClient(captured)
            ),
            patch.dict("os.environ", {"RESEND_API_KEY": "rk-test"}, clear=False),
        ):
            result = await tool.execute(
                to_email="lead@target.io",
                subject="agent send",
                body_html="<p>x</p>",
                org_id="o-1",
                agent_role="growth",
            )
        assert result.success is True, result.error
        payload = captured["payload"]
        # agent_identified does NOT set reply_to — replies route via agent slug.
        assert "reply_to" not in payload
        assert "growth-agent@selva.town" in payload["from"]
