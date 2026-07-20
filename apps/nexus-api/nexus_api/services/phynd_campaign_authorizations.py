"""Selva → PhyndCRM campaign-authorization bridge (owner money-gate).

PhyndCRM owns the ``campaign_authorizations`` ledger and the fail-closed
send gate (``assertCampaignSendAuthorized``): a campaign can only send
against an ``authorized`` row whose payload hash still matches the
campaign's current content. This bridge lets Selva's office UI and agents
READ the pending queue / full preview and RELAY the owner's decision —
Selva never bypasses the ledger, and phynd records the asserted operator
as ``"<operator> (via service:selva)"`` with ``decided_via='selva'``.

Configuration (graceful absence): ``phynd_crm_url`` +
``phynd_crm_federation_token`` settings (env ``PHYND_CRM_URL`` /
``PHYND_CRM_FEDERATION_TOKEN``). Unset → ``PhyndAuthorizationsUnconfiguredError``
so callers can return an honest 503 instead of pretending the queue is
empty.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


class PhyndAuthorizationsUnconfiguredError(RuntimeError):
    """PHYND_CRM_URL / PHYND_CRM_FEDERATION_TOKEN are not both set."""


class PhyndAuthorizationsError(RuntimeError):
    """PhyndCRM rejected the call; ``detail`` carries its message."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _config() -> tuple[str, str]:
    settings = get_settings()
    base = (settings.phynd_crm_url or "").strip()
    token = (settings.phynd_crm_federation_token or "").strip()
    if not base or not token:
        raise PhyndAuthorizationsUnconfiguredError(
            "PhyndCRM authorization bridge unconfigured: set PHYND_CRM_URL "
            "and PHYND_CRM_FEDERATION_TOKEN."
        )
    return base.rstrip("/"), token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _unwrap(status_code: int, body: Any) -> Any:
    if isinstance(body, dict):
        if 200 <= status_code < 300:
            return body.get("result", {}).get("data", {}).get("json")
        err = body.get("error", {})
        if isinstance(err, dict):
            message = err.get("json", {}).get("message") or err.get("message") or str(err)
        else:
            message = str(err)
        raise PhyndAuthorizationsError(message, status_code)
    raise PhyndAuthorizationsError(str(body), status_code)


async def _query(procedure: str, input_data: dict[str, Any] | None = None) -> Any:
    base, token = _config()
    params = {"input": json.dumps({"json": input_data})} if input_data is not None else None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{base}/api/trpc/{procedure}", headers=_headers(token), params=params
        )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return _unwrap(resp.status_code, body)


async def _mutate(procedure: str, input_data: dict[str, Any]) -> Any:
    base, token = _config()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{base}/api/trpc/{procedure}",
            headers=_headers(token),
            json={"json": input_data},
        )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        return _unwrap(resp.status_code, body)


async def list_pending() -> list[dict[str, Any]]:
    rows = await _query("campaignAuthorizations.listPending")
    return rows if isinstance(rows, list) else []


async def get_preview(authorization_id: str) -> dict[str, Any]:
    preview = await _query("campaignAuthorizations.getPreview", {"id": authorization_id})
    return preview if isinstance(preview, dict) else {}


async def decide(
    *, authorization_id: str, decision: str, operator: str, note: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": authorization_id,
        "decision": decision,
        "actor": operator,
    }
    if note:
        payload["note"] = note
    record = await _mutate("campaignAuthorizations.decide", payload)
    return record if isinstance(record, dict) else {}


async def request_fresh(campaign_id: str) -> dict[str, Any]:
    record = await _mutate("campaignAuthorizations.request", {"campaignId": campaign_id})
    return record if isinstance(record, dict) else {}
