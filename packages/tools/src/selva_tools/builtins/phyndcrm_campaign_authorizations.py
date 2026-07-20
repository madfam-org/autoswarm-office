"""PhyndCRM campaign-authorization tools — the owner money-gate from Selva.

PhyndCRM's ``campaign_authorizations`` ledger is the single source of truth:
a campaign can only send against an ``authorized`` row whose payload hash
still matches the campaign's current content (copy variants, schedule,
sender, audience definition). The fail-closed gate lives in phynd-crm
(``assertCampaignSendAuthorized`` inside ``attemptTulanaSend``) — Selva
cannot bypass it. These tools only read review state and RELAY the owner's
decision into phynd's audit ledger.

Because Selva authenticates as a service principal, phynd REQUIRES the
``operator`` argument on decisions — the human identity making the call in
conversation — and records it as ``"<operator> (via service:selva)"`` with
``decided_via = 'selva'``. Never invent an operator: ask the human you are
talking to, or use their known identity.

API base: ``PHYND_CRM_URL`` (default
``http://phynd-crm-web.phynd-crm.svc.cluster.local`` in-cluster,
``https://crm.madfam.io`` from outside).
Auth: ``PHYND_CRM_FEDERATION_TOKEN`` — service token opening the
``campaignAuthorizations:read/write`` scopes. Unset → tools fail closed
with a clear error.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

PHYND_CRM_URL = os.environ.get("PHYND_CRM_URL", "http://phynd-crm-web.phynd-crm.svc.cluster.local")
PHYND_CRM_TOKEN = os.environ.get(
    "PHYND_CRM_FEDERATION_TOKEN", os.environ.get("PHYND_CRM_TOKEN", "")
)

_MAX_BODY_CHARS = 1600


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {PHYND_CRM_TOKEN}",
        "Content-Type": "application/json",
    }


def _creds_check() -> str | None:
    if not PHYND_CRM_TOKEN:
        return "PHYND_CRM_FEDERATION_TOKEN must be set."
    return None


async def _trpc_query(procedure: str, input_data: dict[str, Any] | None = None) -> tuple[int, Any]:
    """Invoke a PhyndCRM tRPC query (GET, superjson envelope)."""
    url = f"{PHYND_CRM_URL.rstrip('/')}/api/trpc/{procedure}"
    params = {"input": json.dumps({"json": input_data})} if input_data is not None else None
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text


async def _trpc_mutate(procedure: str, input_data: dict[str, Any]) -> tuple[int, Any]:
    """Invoke a PhyndCRM tRPC mutation (POST, superjson envelope)."""
    url = f"{PHYND_CRM_URL.rstrip('/')}/api/trpc/{procedure}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_headers(), json={"json": input_data})
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text


def _ok(status: int) -> bool:
    return 200 <= status < 300


def _unwrap(body: Any) -> Any:
    if isinstance(body, dict):
        return body.get("result", {}).get("data", {}).get("json")
    return None


def _trpc_err(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            return err.get("json", {}).get("message") or err.get("message") or str(err)
        return str(err)
    return str(body)


def _clip(text: str, limit: int = _MAX_BODY_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [{len(text) - limit} chars truncated]"


def _coverage_lines(coverage: dict[str, Any]) -> list[str]:
    consent = coverage.get("consent") or {}
    return [
        f"  Contacts with email: {coverage.get('contactsWithEmail', '?')}",
        f"  Consent granted: {consent.get('granted', '?')} | "
        f"pending double opt-in: {consent.get('pendingDoubleOptIn', '?')} | "
        f"revoked: {consent.get('revoked', '?')} | suppressed: {coverage.get('suppressed', '?')}",
        f"  SENDABLE TODAY (granted, not suppressed): {coverage.get('grantedNotSuppressed', '?')}",
    ]


class PhyndcrmCampaignAuthorizationsPendingTool(BaseTool):
    """List campaigns waiting for the owner's send authorization."""

    name = "phyndcrm_campaign_authorizations_pending"
    description = (
        "List PhyndCRM campaigns waiting for OWNER authorization before they "
        "can send. Each entry includes the authorization id (needed for "
        "preview/decide), campaign name, SKU, variant count, and honest "
        "consent coverage captured at request time. Sending is impossible "
        "without an authorized record — this queue is the money gate."
    )
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        try:
            status, body = await _trpc_query("campaignAuthorizations.listPending")
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            rows = _unwrap(body) or []

            if not rows:
                return ToolResult(
                    success=True,
                    output="No campaigns are waiting for authorization.",
                    data={"pending": []},
                )

            lines = [f"{len(rows)} campaign(s) awaiting owner authorization:", ""]
            entries: list[dict[str, Any]] = []
            for row in rows:
                auth = row.get("authorization") or {}
                campaign = row.get("campaign") or {}
                snapshot = auth.get("snapshot") or {}
                payload = snapshot.get("payload") or {}
                coverage = (snapshot.get("context") or {}).get("coverage") or {}
                variants = payload.get("variants") or []
                entry = {
                    "authorization_id": auth.get("id"),
                    "campaign_id": campaign.get("id"),
                    "campaign_name": campaign.get("name"),
                    "sku_key": campaign.get("skuKey"),
                    "variant_count": len(variants),
                    "requested_by": auth.get("requestedBy"),
                    "requested_at": auth.get("createdAt"),
                    "sendable_today": coverage.get("grantedNotSuppressed"),
                    "contacts_with_email": coverage.get("contactsWithEmail"),
                }
                entries.append(entry)
                lines.append(
                    f"- {campaign.get('name')} (sku={campaign.get('skuKey')}) — "
                    f"{len(variants)} variant(s), sendable today "
                    f"{coverage.get('grantedNotSuppressed', '?')} of "
                    f"{coverage.get('contactsWithEmail', '?')} contacts"
                )
                lines.append(f"  authorization_id: {auth.get('id')}")

            lines.append("")
            lines.append(
                "Use phyndcrm_campaign_authorization_preview with an "
                "authorization_id for the full review before any decision."
            )
            return ToolResult(success=True, output="\n".join(lines), data={"pending": entries})
        except Exception as e:  # noqa: BLE001
            logger.error("phyndcrm_campaign_authorizations_pending failed: %s", e)
            return ToolResult(success=False, error=str(e))


class PhyndcrmCampaignAuthorizationPreviewTool(BaseTool):
    """Full review payload for one pending authorization."""

    name = "phyndcrm_campaign_authorization_preview"
    description = (
        "Fetch the FULL review for a campaign authorization: every copy "
        "variant (subject/preheader/body/CTA + claim keys) exactly as the "
        "production email pipeline renders it, sender identity, schedule, "
        "audience definition, do-not-claim guardrails, and consent coverage. "
        "Present this faithfully to the owner — never summarize away the "
        "guardrails or the coverage numbers. Also reports whether the "
        "snapshot went STALE (campaign edited after the request), in which "
        "case it cannot be authorized."
    )
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "authorization_id": {
                    "type": "string",
                    "description": "Authorization id from the pending queue.",
                }
            },
            "required": ["authorization_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        auth_id = kwargs["authorization_id"]
        try:
            status, body = await _trpc_query(
                "campaignAuthorizations.getPreview", {"id": auth_id}
            )
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            preview = _unwrap(body) or {}

            authorization = preview.get("authorization") or {}
            snapshot = preview.get("snapshot") or {}
            payload = snapshot.get("payload") or {}
            context = snapshot.get("context") or {}
            coverage = context.get("coverage") or {}
            stale = bool(preview.get("stale"))

            lines: list[str] = [
                f"CAMPAIGN AUTHORIZATION REVIEW — {payload.get('name')}",
                f"status: {authorization.get('status')}"
                + (" | SNAPSHOT STALE — cannot be authorized as-is" if stale else ""),
                "",
                f"Sender: {payload.get('sender')}",
                f"Channel: {payload.get('channel')} | SKU: {payload.get('skuKey')}",
                f"Schedule: {payload.get('schedule', {}).get('startDate') or 'not scheduled'}"
                f" → {payload.get('schedule', {}).get('endDate') or 'open'}",
                f"Audience: {payload.get('audienceDefinition') or 'not defined on the import'}",
                f"Aviso de Privacidad: {payload.get('privacyUrl') or 'corporate default'}",
                f"Snapshot captured: {context.get('capturedAt')}",
                "",
                "Consent coverage at snapshot (real ledger counts; every contact is "
                "re-checked at send time, suppression always wins):",
                *_coverage_lines(coverage),
            ]

            guardrails = payload.get("guardrailsDoNotClaim") or []
            if guardrails:
                lines += ["", "GUARDRAILS — never claim:"]
                lines += [f"  - {claim}" for claim in guardrails]

            proof_points = context.get("proofPoints") or []
            if proof_points:
                lines += ["", "Proof points grounding the copy:"]
                lines += [
                    f"  - {p.get('label')}: {p.get('value')}"
                    for p in proof_points
                    if isinstance(p, dict)
                ]

            variants = payload.get("variants") or []
            lines += ["", f"COPY VARIANTS ({len(variants)}):"]
            for i, variant in enumerate(variants, start=1):
                lines += [
                    "",
                    f"--- Variant {i}: {variant.get('variantId') or '(unnamed)'} "
                    f"[{variant.get('language') or '?'}] ---",
                    f"Subject: {variant.get('subject')}",
                    f"Preheader: {variant.get('preheader')}",
                    f"CTA: {variant.get('cta')} → {variant.get('ctaUrl')}",
                    f"Claim keys: {', '.join(variant.get('claimKeysUsed') or []) or '(none)'}",
                    "Body:",
                    _clip(str(variant.get("body") or "")),
                ]

            if stale:
                lines += [
                    "",
                    "STALE: the campaign changed after this snapshot was taken. "
                    "Use phyndcrm_campaign_authorization_request to create a "
                    "fresh review of the current content.",
                ]
            else:
                lines += [
                    "",
                    "To record the owner's decision use "
                    "phyndcrm_campaign_authorization_decide (operator identity "
                    "required; a written reason is required to reject).",
                ]

            # Rendered per-variant HTML (production pipeline) rides in data for
            # any surface that can display it; the text above is the review.
            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={
                    "authorization_id": auth_id,
                    "campaign_id": authorization.get("campaignId"),
                    "status": authorization.get("status"),
                    "stale": stale,
                    "snapshot": snapshot,
                    "rendered": preview.get("rendered") or [],
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("phyndcrm_campaign_authorization_preview failed: %s", e)
            return ToolResult(success=False, error=str(e))


class PhyndcrmCampaignAuthorizationDecideTool(BaseTool):
    """Relay the OWNER's authorize/reject decision into phynd's audit ledger."""

    name = "phyndcrm_campaign_authorization_decide"
    description = (
        "Record the OWNER's decision on a pending campaign authorization in "
        "PhyndCRM's immutable ledger. ONLY call this after the human owner "
        "has explicitly stated their decision in conversation — never decide "
        "autonomously. `operator` is the human's identity (e.g. their email) "
        "and is recorded as '<operator> (via service:selva)'. Rejection "
        "requires a written reason and parks the campaign. Authorizing makes "
        "the campaign sendable ONLY while its content stays exactly as "
        "reviewed — any edit voids the authorization (phynd's hard gate)."
    )
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "authorization_id": {
                    "type": "string",
                    "description": "Authorization id from the pending queue.",
                },
                "decision": {
                    "type": "string",
                    "enum": ["authorize", "reject"],
                    "description": "The owner's explicit decision.",
                },
                "operator": {
                    "type": "string",
                    "description": "Human identity making this decision (email "
                    "or name) — REQUIRED, recorded in the audit ledger.",
                },
                "note": {
                    "type": "string",
                    "description": "Written reason — REQUIRED when rejecting; "
                    "optional context when authorizing.",
                    "default": "",
                },
            },
            "required": ["authorization_id", "decision", "operator"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        decision = kwargs["decision"]
        operator = str(kwargs.get("operator") or "").strip()
        note = str(kwargs.get("note") or "").strip()
        if not operator:
            return ToolResult(
                success=False,
                error="`operator` (the human making this decision) is required.",
            )
        if decision == "reject" and not note:
            return ToolResult(
                success=False,
                error="A written reason (`note`) is required to reject.",
            )

        payload: dict[str, Any] = {
            "id": kwargs["authorization_id"],
            "decision": "authorized" if decision == "authorize" else "rejected",
            "actor": operator,
        }
        if note:
            payload["note"] = note

        try:
            status, body = await _trpc_mutate("campaignAuthorizations.decide", payload)
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            record = _unwrap(body) or {}
            verdict = record.get("status")
            output = (
                f"Decision recorded in phynd's ledger: {verdict} by "
                f"{record.get('decidedBy')} at {record.get('decidedAt')}."
            )
            if verdict == "authorized":
                output += (
                    " The campaign is sendable ONLY while its content matches "
                    "the reviewed snapshot — any edit voids this authorization."
                )
            else:
                output += " The campaign is parked and stays unsendable."
            return ToolResult(
                success=True,
                output=output,
                data={
                    "authorization_id": record.get("id"),
                    "status": verdict,
                    "decided_by": record.get("decidedBy"),
                    "decided_via": record.get("decidedVia"),
                    "decided_at": record.get("decidedAt"),
                    "note": record.get("decisionNote"),
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("phyndcrm_campaign_authorization_decide failed: %s", e)
            return ToolResult(success=False, error=str(e))


class PhyndcrmCampaignAuthorizationRequestTool(BaseTool):
    """Create/refresh a pending authorization request for a campaign."""

    name = "phyndcrm_campaign_authorization_request"
    description = (
        "Create a fresh authorization request for a PhyndCRM campaign — used "
        "when a prior snapshot went stale (campaign edited after review) or "
        "when an import predates the authorization gate. Supersedes any "
        "existing pending request and freezes a new snapshot of the current "
        "content for the owner to review."
    )
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "PhyndCRM campaign id (NOT the authorization id).",
                }
            },
            "required": ["campaign_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _creds_check()
        if err:
            return ToolResult(success=False, error=err)
        try:
            status, body = await _trpc_mutate(
                "campaignAuthorizations.request", {"campaignId": kwargs["campaign_id"]}
            )
            if not _ok(status):
                return ToolResult(success=False, error=_trpc_err(body))
            record = _unwrap(body) or {}
            return ToolResult(
                success=True,
                output=(
                    f"Fresh authorization request created: {record.get('id')} "
                    "(pending owner review). Use "
                    "phyndcrm_campaign_authorization_preview to review it."
                ),
                data={
                    "authorization_id": record.get("id"),
                    "campaign_id": record.get("campaignId"),
                    "status": record.get("status"),
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("phyndcrm_campaign_authorization_request failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_phyndcrm_campaign_authorization_tools() -> list[BaseTool]:
    return [
        PhyndcrmCampaignAuthorizationsPendingTool(),
        PhyndcrmCampaignAuthorizationPreviewTool(),
        PhyndcrmCampaignAuthorizationDecideTool(),
        PhyndcrmCampaignAuthorizationRequestTool(),
    ]
