"""Marketing tools for the Growth Node — content distribution and email campaigns."""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import httpx

from ..base import BaseTool, ToolResult
from ._email_signatures import build_identity
from ._spf_check import check_alignment
from .email_tools import _fetch_tenant_identity, _fetch_voice_mode, _resolve_agent_identity

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# HTML sanitisation — allow-list parser via bleach.
#
# Rationale: the prior regex-based stripper was bypassable through
# nested tags (``<scr<script>ipt>`` survived the SCRIPT regex with
# fragments leaking through), single-quoted attributes
# (``<a onclick='alert(1)'>`` matched only double-quoted ``on*``),
# entity-encoded payloads (``&#x6A;avascript:``), and SVG containers
# carrying ``href="javascript:..."`` on non-anchor elements. ``bleach``
# uses html5lib to parse the document and emits only allow-listed tags
# / attributes / URL schemes. Anything else is dropped wholesale.
_ALLOWED_TAGS = [
    "a", "b", "br", "div", "em", "i", "img", "li", "ol", "p",
    "span", "strong", "table", "tbody", "td", "th", "thead", "tr",
    "ul", "h1", "h2", "h3", "h4", "blockquote", "hr", "pre", "code",
]
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    # Inline styles + class/id are allow-listed broadly to keep the
    # MADFAM template rendering correctly; bleach scrubs each style
    # declaration through its CSS sanitiser. Without this every
    # ``style="..."`` would be stripped and the email template would
    # lose its layout.
    "*": ["style", "class", "id"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _sanitize_email_html(html: str) -> str:
    """Allow-list HTML sanitiser backed by bleach (html5lib parser).

    Drops every tag, attribute, and URL scheme not in the allow-lists
    above. Closes the regex bypass classes (nested tags, single-quoted
    attributes, SVG-wrapped javascript: URLs, entity-encoded payloads).

    Inline ``style`` attributes are scrubbed via tinycss2's
    ``CSSSanitizer`` (an optional bleach extra) so a tenant's email
    template can keep its inline styles for Outlook/Gmail compatibility
    without letting an LLM-injected
    ``style="background:url(javascript:...)"`` declaration through.

    ``strip=True`` removes disallowed tags entirely rather than escaping
    them — escaped <script> tags would render as visible HTML in the
    recipient's mail client, which is harmless but ugly. We prefer the
    silent drop because marketing email content is generated, not
    user-authored, so an LLM emitting <script> almost always reflects a
    failed prompt rather than legitimate intent.
    """
    import bleach

    css_sanitizer = None
    try:
        # Optional dep — bleach[css] pulls in tinycss2. Without it,
        # ``style`` attributes pass through unscanned (still safer than
        # the prior regex stripper, which dropped them entirely on
        # quoted-mismatch corner cases) but we strongly prefer the
        # scrubbed path.
        from bleach.css_sanitizer import CSSSanitizer

        css_sanitizer = CSSSanitizer(
            allowed_css_properties=[
                "background", "background-color", "border", "border-radius",
                "color", "display", "font-family", "font-size", "font-weight",
                "height", "letter-spacing", "line-height", "margin",
                "margin-top", "margin-bottom", "margin-left", "margin-right",
                "max-width", "min-width", "overflow", "padding",
                "padding-top", "padding-bottom", "padding-left",
                "padding-right", "text-align", "text-decoration",
                "vertical-align", "width",
            ],
        )
    except ImportError:
        logger.warning(
            "bleach.css_sanitizer unavailable — install bleach[css] for "
            "inline-style scrubbing on outbound marketing email."
        )

    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        css_sanitizer=css_sanitizer,
    )



def _inject_utm(url: str, campaign: str = "", source: str = "selva", medium: str = "email") -> str:
    """Inject UTM tracking parameters into a URL for attribution."""
    if not url:
        return url
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.update(
        {
            "utm_source": [source],
            "utm_medium": [medium],
            "utm_campaign": [campaign or "agent_outreach"],
        }
    )
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def _build_madfam_email_html(
    body_text: str,
    cta_url: str = "",
    cta_text: str = "Comienza ahora",
    product_name: str = "",
    to_email: str = "",
) -> str:
    """Wrap email content in a MADFAM-branded HTML template.

    Uses table-based layout for Outlook/Gmail/Apple Mail compatibility.
    All styles are inline (no <style> block).
    """
    cta_block = ""
    if cta_url:
        cta_block = f'''
        <tr>
          <td style="padding:24px;text-align:center">
            <a href="{cta_url}" style="display:inline-block;background-color:#f6d55c;color:#1a1a2e;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:bold;font-family:Arial,sans-serif;font-size:16px">{cta_text}</a>
          </td>
        </tr>'''

    product_line = f" — {product_name}" if product_name else ""

    # Convert plain text paragraphs to HTML if not already HTML
    if "<" not in body_text:
        body_html = "".join(
            f'<p style="margin:0 0 16px">{p.strip()}</p>'
            for p in body_text.split("\n\n")
            if p.strip()
        )
    else:
        body_html = body_text

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f0f0f5;font-family:Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0f0f5">
  <tr><td align="center" style="padding:24px 16px">
    <!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0"><tr><td><![endif]-->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background-color:#ffffff;border-radius:8px;overflow:hidden">
      <tr>
        <td style="padding:28px 24px;background-color:#1a1a2e;text-align:center">
          <h1 style="color:#f6d55c;font-family:Arial,sans-serif;font-size:22px;margin:0;letter-spacing:1px">MADFAM{product_line}</h1>
          <p style="color:#a0a0b0;font-size:12px;margin:8px 0 0;font-family:Arial,sans-serif">Tecnología que potencia tu negocio</p>
        </td>
      </tr>
      <tr>
        <td style="padding:32px 24px;font-family:Arial,sans-serif;font-size:16px;line-height:1.6;color:#333333">
          {body_html}
        </td>
      </tr>
      {cta_block}
      <tr>
        <td style="padding:20px 24px;background-color:#f5f5f5;text-align:center;font-family:Arial,sans-serif">
          <p style="font-size:12px;color:#888888;margin:0">By Innovaciones MADFAM S.A.S. de C.V. · Cuernavaca, Morelos, Mexico · <a href="https://madfam.io" style="color:#888888">madfam.io</a></p>
          <p style="font-size:11px;color:#aaaaaa;margin:8px 0 0"><a href="https://madfam.io/unsubscribe?email={quote(to_email, safe="@")}" style="color:#aaaaaa">Cancelar suscripción</a></p>
        </td>
      </tr>
    </table>
    <!--[if mso]></td></tr></table><![endif]-->
  </td></tr>
</table>
</body>
</html>"""


class SendMarketingEmailTool(BaseTool):
    """Send a marketing email with UTM tracking via Resend.

    Used by Growth Node agents (Heraldo, Nexo) for lead outreach,
    content distribution, and retention campaigns. All links in the
    email body are auto-tagged with UTM parameters for attribution.

    Category: MARKETING_SEND (requires playbook approval or HITL).
    """

    name = "send_marketing_email"
    description = (
        "Send a marketing email with UTM tracking for attribution. "
        "Use for lead outreach, content distribution, or retention campaigns. "
        "Links are auto-tagged with utm_source=selva for PostHog attribution."
    )

    def parameters_schema(self) -> dict[str, Any]:
        # NOTE: ``user_email``, ``user_name``, ``agent_slug``,
        # ``agent_display_name``, ``org_name`` are intentionally NOT in
        # the schema. They are server-resolved per call from the
        # tenant's outbound-identity record so a prompt-injected LLM
        # cannot spoof the From: header within the tenant's verified
        # Resend domain. ``reply_to`` is also dropped — replies always
        # route back to the resolved user_email (Wave 3B-A consent
        # ledger ties the legal voice mode to that mailbox).
        return {
            "type": "object",
            "properties": {
                "to_email": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body_html": {
                    "type": "string",
                    "description": "Email body in HTML. Links will have UTM parameters injected.",
                },
                "utm_campaign": {
                    "type": "string",
                    "description": "UTM campaign name for attribution tracking",
                    "default": "agent_outreach",
                },
                "org_id": {
                    "type": "string",
                    "description": "Tenant org_id for voice-mode + identity lookup",
                },
                "agent_role": {
                    "type": "string",
                    "description": (
                        "Constrained role label for agent_identified mode "
                        "only. Allowed values: sales, support, growth, "
                        "ops, research. Ignored in user_direct + dyad "
                        "modes. Unknown values fall back to 'support'."
                    ),
                    "enum": ["sales", "support", "growth", "ops", "research"],
                },
                "lead_id": {
                    "type": "string",
                    "description": (
                        "Opaque lead identifier threaded through the T3.2 "
                        "attribution funnel. Used as PostHog distinct_id "
                        "when set. See docs/attribution-contract.md."
                    ),
                },
            },
            "required": ["to_email", "subject", "body_html", "org_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        to_email = kwargs.get("to_email", "")
        subject = kwargs.get("subject", "")
        body_html = kwargs.get("body_html", "")
        utm_campaign = kwargs.get("utm_campaign", "agent_outreach")
        org_id = kwargs.get("org_id", "")
        agent_role = kwargs.get("agent_role")

        if not to_email or not subject:
            return ToolResult(success=False, error="to_email and subject are required")
        if not _EMAIL_RE.match(to_email):
            return ToolResult(success=False, error=f"Invalid email format: {to_email[:20]}...")
        if not org_id:
            return ToolResult(success=False, error="org_id is required for voice-mode gate")

        # -- Voice-mode gate -------------------------------------------------
        voice_mode = await _fetch_voice_mode(org_id)
        if voice_mode is None:
            return ToolResult(
                success=False,
                error=(
                    "Outbound voice mode not configured. Complete onboarding "
                    "before sending marketing email."
                ),
            )

        # -- Identity gate: server-resolve From-header inputs. Refuse
        # the send if the tenant has no configured identity rather
        # than substituting LLM-supplied defaults — that substitution
        # is the spoofing vector this lockdown closes.
        identity_data = await _fetch_tenant_identity(org_id)
        if identity_data is None:
            return ToolResult(
                success=False,
                error=(
                    "Tenant outbound identity not configured. "
                    "Cannot resolve From: header — refusing send."
                ),
            )
        user_email = (identity_data.get("user_email") or "").strip()
        user_name = (identity_data.get("user_name") or "").strip()
        org_name = (identity_data.get("org_name") or "").strip()

        if voice_mode in ("user_direct", "dyad_selva_plus_user") and (
            not user_email or not _EMAIL_RE.match(user_email)
        ):
            return ToolResult(
                success=False,
                error=(
                    "Tenant outbound mailbox missing or malformed. "
                    "Configure tenant_identities.primary_contact_email."
                ),
            )

        if voice_mode == "agent_identified":
            alignment = check_alignment("selva.town")
            if not alignment.aligned:
                return ToolResult(
                    success=False,
                    error=(
                        f"agent_identified send blocked: selva.town "
                        f"alignment {alignment.status} — {alignment.reason}"
                    ),
                )

        # Resolve agent slug + display from the server-side allow-list.
        agent_slug, agent_display_name = _resolve_agent_identity(agent_role)

        selva_from = os.environ.get("EMAIL_FROM_SELVA", "hola@selva.town")
        try:
            identity = build_identity(
                voice_mode=voice_mode,
                user_name=user_name,
                user_email=user_email,
                selva_from=selva_from,
                agent_slug=agent_slug,
                agent_display_name=agent_display_name,
                org_name=org_name,
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))
        from_addr = identity.from_address
        # Reply-To is server-controlled: always route back to the
        # tenant's resolved user_email when the voice mode involves
        # the user identity. agent_identified replies stay on the
        # agent slug (Resend will route via the selva.town domain).
        reply_to = user_email if voice_mode in ("user_direct", "dyad_selva_plus_user") else ""

        api_key = os.environ.get("RESEND_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                error="RESEND_API_KEY not configured. Cannot send marketing email.",
            )

        # Sanitize HTML content before template injection
        body_html = _sanitize_email_html(body_html)
        # Attach the voice-mode signature so the body reflects the chosen
        # attribution (user_direct / dyad / agent_identified) before the
        # MADFAM template wraps it.
        body_html = f"{body_html}\n{identity.html_signature}"

        # Wrap in MADFAM branded template (unless raw HTML with full <html> tag)
        template = kwargs.get("template", "madfam")
        cta_url = kwargs.get("cta_url", "")
        cta_text = kwargs.get("cta_text", "Comienza ahora")
        product_name = kwargs.get("product_name", "")
        if template == "madfam" and "<!DOCTYPE" not in body_html and "<html" not in body_html:
            body_html = _build_madfam_email_html(
                body_html, cta_url, cta_text, product_name, to_email=to_email
            )

        # Inject UTM into any links in the HTML body
        # Simple approach: find href="..." and append UTM params
        import re

        def _add_utm_to_link(match: re.Match) -> str:
            url = match.group(1)
            if url.startswith("mailto:") or url.startswith("#"):
                return match.group(0)
            tracked_url = _inject_utm(url, campaign=utm_campaign)
            return f'href="{tracked_url}"'

        tracked_body = re.sub(r'href="([^"]*)"', _add_utm_to_link, body_html)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                payload: dict[str, Any] = {
                    "from": from_addr,
                    "to": [to_email],
                    "subject": subject,
                    "html": tracked_body,
                }
                if reply_to:
                    payload["reply_to"] = reply_to
                # CAN-SPAM / LFPDPPP: List-Unsubscribe header
                payload["headers"] = {
                    "List-Unsubscribe": f"<https://madfam.io/unsubscribe?email={quote(to_email, safe='@')}>",  # noqa: E501
                }

                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Track in PostHog if available. When a lead_id is threaded
            # through from the CRM graph, use it as distinct_id so the
            # T3.2 attribution funnel stays single-sourced (do NOT use
            # the recipient email — it would fork the funnel once the
            # user authenticates via Janua/Dhanam).
            try:
                from nexus_api.analytics import track

                lead_id = kwargs.get("lead_id") or ""
                distinct_id = lead_id or to_email
                track(
                    distinct_id,
                    "marketing_email_sent",
                    {
                        "subject": subject,
                        "utm_campaign": utm_campaign,
                        "agent_tool": "send_marketing_email",
                        "lead_id": lead_id,
                    },
                )
            except Exception:
                pass

            email_id = data.get("id", "unknown")
            logger.info("Marketing email sent: to=%s subject=%s id=%s", to_email, subject, email_id)
            try:
                from ..service_tracking import emit_service_usage

                emit_service_usage(
                    "resend",
                    "marketing_email_sent",
                    1,
                    {
                        "to": to_email,
                        "subject": subject,
                        "email_id": email_id,
                        "utm_campaign": utm_campaign,
                    },
                )
            except Exception:
                pass

            return ToolResult(
                success=True,
                output=f"Marketing email sent to {to_email}: '{subject}' (id: {email_id})",
                data={"email_id": email_id, "to": to_email, "utm_campaign": utm_campaign},
            )
        except httpx.HTTPError as exc:
            logger.error("Marketing email failed: %s", exc)
            return ToolResult(success=False, error=f"Email send failed: {exc}")
