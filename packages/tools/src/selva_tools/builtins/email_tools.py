"""Email tools: send via Resend API, read via IMAP (placeholder).

Every outbound send is gated on the tenant's ``voice_mode``. When the
mode is ``None`` (tenant hasn't completed onboarding) the tool refuses
the call. When the mode is ``agent_identified`` the tool also verifies
SPF/DKIM/DMARC alignment on ``selva.town`` before handing off to Resend.

**Sender identity is server-controlled.** ``user_email`` / ``user_name``
/ ``agent_slug`` are NOT accepted as LLM-controllable kwargs — they are
fetched from nexus-api ``/onboarding/tenant-identity`` per-call so a
prompt-injected LLM cannot spoof the From: header within the tenant's
verified Resend domain. ``agent_role`` is a constrained LLM input that
maps to a server-side allow-list of slugs (so the LLM can pick "send
as the sales bot vs the support bot" but cannot invent a slug).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from ..base import BaseTool, ToolResult
from ._email_signatures import build_identity
from ._spf_check import check_alignment

logger = logging.getLogger("selva.email")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Allow-list for the ``agent_role`` LLM kwarg in agent_identified mode.
# Each entry maps a role label the LLM may choose to a server-controlled
# (slug, display_name) pair. Adding a new role requires a code change —
# the LLM cannot mint slugs of its own.
#
# Slugs are constrained to ``[a-z0-9-]+`` so they remain valid local
# parts when concatenated with ``@selva.town``. Display names are kept
# generic; tenants who want personalised disclosures can override via
# the future ``tenant_configs.outbound_agent_roles`` JSON column (out
# of scope for this lockdown — see TODO at bottom).
_AGENT_ROLE_ALLOWLIST: dict[str, tuple[str, str]] = {
    "sales": ("sales-agent", "Selva Sales Agent"),
    "support": ("support-agent", "Selva Support Agent"),
    "growth": ("growth-agent", "Selva Growth Agent"),
    "ops": ("ops-agent", "Selva Operations Agent"),
    "research": ("research-agent", "Selva Research Agent"),
}
_DEFAULT_AGENT_ROLE = "support"


def _resolve_agent_identity(agent_role: str | None) -> tuple[str, str]:
    """Resolve a constrained LLM-supplied role label to (slug, display_name).

    Unknown roles fall back to the default — never to LLM-supplied raw
    text. Returning the default rather than refusing keeps email
    delivery resilient when the LLM is loose with the role name; the
    role is non-security-critical (the slug is from the allow-list
    either way) so the soft-fail is acceptable.
    """
    role = (agent_role or _DEFAULT_AGENT_ROLE).strip().lower()
    if role not in _AGENT_ROLE_ALLOWLIST:
        logger.info("unknown agent_role=%r, falling back to %s", agent_role, _DEFAULT_AGENT_ROLE)
        role = _DEFAULT_AGENT_ROLE
    return _AGENT_ROLE_ALLOWLIST[role]


def _tenant_lookup_headers(org_id: str) -> dict[str, str]:
    """Auth headers for tenant-scoped lookups against nexus-api.

    Sends both ``X-Selva-Tenant-Org`` (the canonical Wave 3B-A header
    documented in CLAUDE.md) and ``X-Org-Id`` (the legacy alias still
    accepted by some auth code paths). Sending both is defensive — the
    receiving server picks whichever it understands.
    """
    token = os.environ.get("WORKER_API_TOKEN", "dev-bypass")
    return {
        "Authorization": f"Bearer {token}",
        "X-Selva-Tenant-Org": org_id,
        "X-Org-Id": org_id,
    }


async def _fetch_voice_mode(org_id: str) -> str | None:
    """Fetch the tenant's outbound voice mode from nexus-api.

    Workers authenticate with ``WORKER_API_TOKEN`` and declare the target
    tenant via the ``X-Selva-Tenant-Org`` header so nexus-api ``auth.py``
    populates ``user["org_id"]`` correctly. Returns ``None`` on any
    error so the caller fails closed (refuses the send rather than
    silently defaulting).
    """
    base_url = os.environ.get("NEXUS_API_URL", "http://localhost:4300")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/v1/onboarding/status",
                headers=_tenant_lookup_headers(org_id),
            )
            if resp.status_code == 200:
                return resp.json().get("voice_mode")
            logger.warning(
                "voice_mode lookup returned %d org_id=%s",
                resp.status_code,
                org_id,
            )
            return None
    except Exception:
        logger.warning("voice_mode lookup failed org_id=%s", org_id, exc_info=True)
        return None


async def _fetch_tenant_identity(org_id: str) -> dict[str, Any] | None:
    """Fetch server-controlled outbound identity for the tenant.

    Returns the dict from ``GET /api/v1/onboarding/tenant-identity`` or
    ``None`` on any error / missing config. The dict shape is
    ``{user_email, user_name, org_name, agent_slug}`` (any field may be
    None when the tenant has partial config). Callers MUST fail-closed
    on a None return rather than substituting LLM-supplied defaults.

    **Resolution chain (server-side, since migration 0026)**:

    - ``user_email``: ``tenant_configs.outbound_user_email`` (first-class,
      tenant-set via the office UI) → ``tenant_identities.primary_contact_email``
      (legacy MADFAM-ops-set fallback).
    - ``user_name``: ``tenant_configs.outbound_user_name`` →
      ``tenant_configs.brand_name`` → ``tenant_identities.legal_name`` →
      ``tenant_configs.razon_social``.
    - ``org_name``: legacy chain (legal_name → razon_social → brand_name).
    - ``agent_slug``: ``tenant_configs.outbound_agent_slug`` if the tenant
      has pinned a specific agent, else None (caller falls back to its
      own per-call role → slug resolver, never to LLM-supplied text).

    Same auth shape as ``_fetch_voice_mode``: worker token + the
    ``X-Selva-Tenant-Org`` header so nexus-api resolves the requesting
    tenant correctly even though the bearer is a service token.
    """
    base_url = os.environ.get("NEXUS_API_URL", "http://localhost:4300")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/v1/onboarding/tenant-identity",
                headers=_tenant_lookup_headers(org_id),
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "tenant_identity lookup returned %d org_id=%s",
                resp.status_code,
                org_id,
            )
            return None
    except Exception:
        logger.warning("tenant_identity lookup failed org_id=%s", org_id, exc_info=True)
        return None


class SendEmailTool(BaseTool):
    name = "send_email"
    description = (
        "Send an email via the Resend API. "
        "Requires RESEND_API_KEY env var. "
        "Supports HTML body content. The From: header is resolved "
        "server-side from the tenant's outbound identity — the caller "
        "cannot specify sender identity."
    )

    def parameters_schema(self) -> dict[str, Any]:
        # NOTE: ``user_email``, ``user_name``, ``agent_slug``,
        # ``agent_display_name``, ``org_name`` are intentionally NOT in
        # the schema. They are server-resolved per call to prevent
        # prompt-injection-driven sender spoofing inside the tenant's
        # verified Resend domain. The LLM has zero control over the
        # From: header.
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "html": {
                    "type": "string",
                    "description": "HTML body content",
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
                    "enum": list(_AGENT_ROLE_ALLOWLIST.keys()),
                },
            },
            "required": ["to", "subject", "html", "org_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        to = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        html = kwargs.get("html", "")
        org_id = kwargs.get("org_id", "")
        agent_role = kwargs.get("agent_role")

        if not to:
            return ToolResult(success=False, error="Recipient 'to' is required")
        if not _EMAIL_RE.match(to):
            return ToolResult(success=False, error=f"Invalid email format: {to[:20]}...")
        if not org_id:
            return ToolResult(success=False, error="org_id is required for voice-mode gate")

        # -- Voice-mode gate: check BEFORE Resend key so the failure mode
        # is consistent regardless of upstream provider configuration.
        voice_mode = await _fetch_voice_mode(org_id)
        if voice_mode is None:
            return ToolResult(
                success=False,
                error=(
                    "Outbound voice mode not configured. Complete onboarding before sending mail."
                ),
            )

        # -- Identity gate: server-resolve From-header inputs. Refuse
        # the send if the tenant has no configured identity rather
        # than substituting LLM-supplied defaults (which would be the
        # whole spoofing vector this lockdown closes).
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

        # user_direct + dyad modes need user_email (it goes into the
        # From: header / Reply-To). agent_identified mode does not
        # require it but still uses org_name in the signature block.
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

        api_key = os.environ.get("RESEND_API_KEY")
        if not api_key:
            logger.warning("RESEND_API_KEY not configured")
            return ToolResult(
                success=False,
                error="RESEND_API_KEY not configured",
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
        # The LLM can pick the role label, but never the slug itself.
        agent_slug, agent_display_name = _resolve_agent_identity(agent_role)

        selva_from = os.environ.get("EMAIL_FROM_SELVA", "noreply@selva.town")
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

        from_address = identity.from_address
        html_body = f"{html}\n{identity.html_signature}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload: dict[str, Any] = {
                    "from": from_address,
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                }
                # user_direct: user's mailbox authors the message. Add
                # Reply-To matching the user so replies route back to them.
                if voice_mode in ("dyad_selva_plus_user", "user_direct") and user_email:
                    payload["reply_to"] = user_email
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )

            if resp.status_code in (200, 201):
                message_id = resp.json().get("id", "unknown")
                logger.info("Email sent to=%s id=%s", to, message_id)
                try:
                    from ..service_tracking import emit_service_usage

                    emit_service_usage(
                        "resend",
                        "transactional_email_sent",
                        1,
                        {
                            "to": to,
                            "subject": subject,
                            "message_id": message_id,
                        },
                    )
                except Exception:
                    pass
                return ToolResult(
                    output=f"Email sent to {to} (id={message_id})",
                    data={"message_id": message_id, "to": to, "subject": subject},
                )

            logger.error("Email send failed: %s %s", resp.status_code, resp.text[:200])
            return ToolResult(
                success=False,
                error=f"Resend API error: {resp.status_code} {resp.text[:200]}",
            )
        except Exception as exc:
            logger.error("send_email failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class ReadEmailTool(BaseTool):
    name = "read_email"
    description = (
        "Read emails from a mailbox via IMAP. "
        "Currently a placeholder -- returns an error indicating "
        "IMAP is not configured. Production would use imaplib."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mailbox": {
                    "type": "string",
                    "description": "Mailbox folder to read (e.g. INBOX)",
                    "default": "INBOX",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of recent emails to retrieve",
                    "default": 10,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=False,
            error="IMAP not configured. Set IMAP_HOST, IMAP_USER, IMAP_PASSWORD env vars.",
        )
