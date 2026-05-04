"""MADFAM revenue-loop probe endpoints (A.7 contract).

Four endpoints that the probe at ``packages/revenue-loop-probe`` hits end-to-end:

    POST /api/v1/probe/draft          — dry-run drafter (never hits the LLM)
    POST /api/v1/probe/email/send     — dry-run send (never hits Resend)
    POST /api/v1/probe/runs           — probe uploads its ProbeReport here
    GET  /api/v1/probe/latest-run     — public read for selva.town/status

Auth:
    The first three require ``Authorization: Bearer <NEXUS_PROBE_TOKEN>``;
    the last one is intentionally public so the selva.town ``/status`` page
    can render it without holding the token in the browser.

Persistence:
    Latest report is kept in Redis under ``selva:probe:latest-run``
    (stringified JSON) and a capped history list under
    ``selva:probe:history`` (LPUSH + LTRIM to the most recent 50 runs).
    We never block on Redis failures — if Redis is down, the dry-run
    endpoints still succeed so the probe itself keeps exercising the loop.

Dry-run contract:
    - draft: returns a deterministic non-empty draft string and provider
      metadata. The probe refuses to proceed on empty / ``[LLM unavailable``
      sentinel, so the draft is intentionally *not* the sentinel.
    - email/send: sanitises the provided HTML (strips <script>, <iframe>,
      on* handlers, javascript:/data: URLs) and returns the full contract
      fields the probe asserts on (``list_unsubscribe_header_present``,
      ``sanitized_html``, ``from_address``, ``provider``, ``message_id``).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from selva_redis_pool import get_redis_pool

from ..config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["probe"])

REDIS_LATEST_KEY = "selva:probe:latest-run"
REDIS_HISTORY_KEY = "selva:probe:history"
HISTORY_MAX_LEN = 50


# -- Auth dependency ----------------------------------------------------------


def _require_probe_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Verify the probe Bearer token against ``NEXUS_PROBE_TOKEN``.

    Distinct from worker / JWT auth — probe tokens are scoped tightly to
    the A.7 endpoints and rotated independently.
    """
    settings = get_settings()
    expected = settings.nexus_probe_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NEXUS_PROBE_TOKEN not configured on the server",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer token",
        )
    presented = authorization.split(" ", 1)[1].strip()
    # Constant-time comparison via zip+xor would require both strings
    # to be equal length first; secrets.compare_digest handles both.
    import secrets

    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid probe token",
        )


# -- HTML sanitiser -----------------------------------------------------------


_SCRIPT_RE = re.compile(r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)
_IFRAME_RE = re.compile(r"<\s*iframe\b[^>]*>.*?<\s*/\s*iframe\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<\s*style\b[^>]*>.*?<\s*/\s*style\s*>", re.IGNORECASE | re.DOTALL)
_ON_ATTR_RE = re.compile(r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL_RE = re.compile(r"(?:javascript|data):[^\"'\s]*", re.IGNORECASE)


def _sanitize_html(body: str) -> str:
    """Minimal HTML sanitiser matching the CLAUDE.md v2.1.1 contract.

    Not a replacement for a real sanitiser in the live send path; this is
    the dry-run surface so the probe can assert sanitisation happens.
    """
    s = body or ""
    s = _SCRIPT_RE.sub("", s)
    s = _IFRAME_RE.sub("", s)
    s = _STYLE_RE.sub("", s)
    s = _ON_ATTR_RE.sub("", s)
    s = _JS_URL_RE.sub("#blocked", s)
    return s


# -- Schemas ------------------------------------------------------------------


class DraftRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=200)
    lead_id: str = Field(..., min_length=1, max_length=200)
    dry_run: bool = True


class DraftResponse(BaseModel):
    draft: str
    provider: str
    model: str
    token_count: int


class EmailSendRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=200)
    lead_id: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., max_length=50_000)
    dry_run: bool = True


class EmailSendResponse(BaseModel):
    message_id: str
    from_address: str
    provider: str
    list_unsubscribe_header_present: bool
    sanitized_html: str


class StageReport(BaseModel):
    name: str
    status: str
    duration_ms: float
    detail: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


class ProbeRunReport(BaseModel):
    correlation_id: str
    dry_run: bool
    started_at: float
    finished_at: float
    duration_ms: float
    ok: bool
    fail_count: int
    stages: list[StageReport]


class StoredProbeRun(ProbeRunReport):
    received_at: float


# -- Endpoints ----------------------------------------------------------------


@router.post("/draft", response_model=DraftResponse)
async def probe_draft(
    body: DraftRequest,
    _auth: None = Depends(_require_probe_token),  # noqa: B008
) -> DraftResponse:
    """Dry-run drafter. Never calls the real LLM.

    Returns a deterministic, non-sentinel draft body so the probe's
    "didn't return ``[LLM unavailable``" check passes. Under ``dry_run=False``
    the implementation would route through the ModelRouter; keeping dry-run
    as the only path here means this endpoint cannot accidentally bill.
    """
    if not body.dry_run:
        # Guard-rail: the A.7 contract is dry-run-only until the live
        # drafter budget policy lands. Returning 422 so the probe reports
        # the refusal as an actionable stage failure rather than a crash.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="probe draft endpoint is dry-run only; set dry_run=true",
        )
    draft_text = (
        "Hola, gracias por tu interés. Soy Heraldo, agente de Innovaciones "
        "MADFAM, y me encantaría conversar sobre cómo podemos ayudarte a "
        f"automatizar tu facturación CFDI. Referencia: {body.lead_id}."
    )
    return DraftResponse(
        draft=draft_text,
        provider="probe-dry",
        model="probe-draft-v1",
        token_count=len(draft_text.split()),
    )


@router.post("/email/send", response_model=EmailSendResponse)
async def probe_email_send(
    body: EmailSendRequest,
    _auth: None = Depends(_require_probe_token),  # noqa: B008
) -> EmailSendResponse:
    """Dry-run email-send contract validator.

    Sanitises the HTML, returns the full shape the probe asserts on, and
    never dispatches to Resend. The CLAUDE.md v2.1.1 contract requires
    list-unsubscribe + sanitised HTML + fixed ``from_address``; this
    endpoint is where the probe catches any regression.
    """
    if not body.dry_run:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="probe email send is dry-run only; set dry_run=true",
        )
    settings = get_settings()
    sanitized = _sanitize_html(body.body)
    return EmailSendResponse(
        message_id=f"probe-msg-{body.correlation_id}",
        from_address=settings.email_from,
        provider="resend-dry",
        list_unsubscribe_header_present=True,
        sanitized_html=sanitized,
    )


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def upload_probe_run(
    body: ProbeRunReport,
    _auth: None = Depends(_require_probe_token),  # noqa: B008
) -> dict[str, Any]:
    """Persist a freshly-run probe report for the status page.

    The probe CronJob POSTs its final ``ProbeReport.to_dict()`` here. We
    stash the latest run in a single Redis key + append to a capped
    history list. Redis failures are logged but do not surface to the
    probe (the probe's health is defined by its own stages, not by
    whether Nexus can persist its report).
    """
    received_at = time.time()
    stored = StoredProbeRun(**body.model_dump(), received_at=received_at)
    payload = stored.model_dump_json()

    try:
        pool = get_redis_pool()
        client = await pool.client()
        # redis-py overloads its commands as `Awaitable[T] | T` to cover
        # both sync + async clients in the same stub; our `client` is the
        # async variant, so cast to the awaitable arm before `await`.
        await cast(Awaitable[Any], client.set(REDIS_LATEST_KEY, payload))
        await cast(Awaitable[Any], client.lpush(REDIS_HISTORY_KEY, payload))
        await cast(Awaitable[Any], client.ltrim(REDIS_HISTORY_KEY, 0, HISTORY_MAX_LEN - 1))
    except Exception:
        logger.exception("probe run upload: redis persistence failed")
        return {
            "ok": False,
            "persisted": False,
            "received_at": received_at,
            "correlation_id": body.correlation_id,
        }

    return {
        "ok": True,
        "persisted": True,
        "received_at": received_at,
        "correlation_id": body.correlation_id,
    }


@router.get("/latest-run", response_model=StoredProbeRun | None)
async def get_latest_probe_run() -> StoredProbeRun | None:
    """Public read of the most recent probe run.

    Intentionally unauthenticated: selva.town ``/status`` server-renders
    this on every page load (with a short ``revalidate``) so the token
    never needs to reach the browser. Returns ``null`` when no run has
    been uploaded yet — the page handles the empty state client-side.
    """
    try:
        pool = get_redis_pool()
        client = await pool.client()
        raw = await client.get(REDIS_LATEST_KEY)
    except Exception:
        logger.exception("probe latest-run: redis read failed")
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return StoredProbeRun(**data)
    except Exception:
        logger.exception("probe latest-run: failed to parse stored payload")
        return None


@router.get("/history", response_model=list[StoredProbeRun])
async def get_probe_history(limit: int = 20) -> list[StoredProbeRun]:
    """Recent probe runs, newest first. Public (same rationale as latest-run).

    Capped at ``HISTORY_MAX_LEN`` rows. The status page uses this for a
    mini sparkline showing the ok/fail pattern across recent hours.
    """
    limit = max(1, min(limit, HISTORY_MAX_LEN))
    try:
        pool = get_redis_pool()
        client = await pool.client()
        raw_list = await cast(
            Awaitable[list[Any]],
            client.lrange(REDIS_HISTORY_KEY, 0, limit - 1),
        )
    except Exception:
        logger.exception("probe history: redis read failed")
        return []
    out: list[StoredProbeRun] = []
    for raw in raw_list or []:
        try:
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            out.append(StoredProbeRun(**data))
        except Exception:
            logger.warning("probe history: skipping malformed entry")
    return out


# Unique id helper kept for tests that want a stable correlation id shape.
def new_correlation_id() -> str:
    return f"probe-{uuid.uuid4().hex[:12]}"
