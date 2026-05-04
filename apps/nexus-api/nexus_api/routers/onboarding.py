"""Onboarding API — voice-mode selection and consent ledger writes.

The outbound voice mode controls how the Selva office represents itself
when sending email, SMS, or other outbound communications on the user's
behalf.  It must be explicitly chosen before any outbound send is
allowed.  Selection is recorded in the append-only `consent_ledger`
(UPDATE/DELETE revoked from the app role at the DB level — see migration
0018).

The three modes:

- **user_direct** — outbound sends authored by agents go out *as the
  user*, from the user's own mailbox/number, with no AI disclosure.
  Legally the riskiest mode (see California BOT Act SB-1001 risk for
  commercial/transactional contact with CA residents, and CASL sender-
  identification obligations in Canada).  Requires explicit typed
  confirmation of the heads-up clause.
- **dyad_selva_plus_user** — outbound sends are jointly attributed
  ("Selva on behalf of <user>"). Lowest legal risk, highest brand
  clarity.
- **agent_identified** — the agent sends from
  `{agent-slug}@selva.town`, disclosing itself as a Selva agent acting
  for the org.  Requires the SPF/DKIM/DMARC alignment to `selva.town`.

The `clause_version` string is the versioned identifier for the legal
copy the user agreed to.  Incrementing the version forces a re-consent
cycle for existing users.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_non_guest
from ..config import get_settings
from ..database import get_db
from ..idempotency import IdempotencyContext, get_idempotency_context
from ..models import ConsentLedger, TenantConfig, TenantIdentity
from .events import emit_event_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Constants — voice-mode definitions and legal clauses
# ---------------------------------------------------------------------------

VOICE_MODES = ("user_direct", "dyad_selva_plus_user", "agent_identified")

CLAUSE_VERSION = "voice-mode-v1.0"

# Clause text the user must type VERBATIM to consent.  Kept short so the
# ledger row is human-auditable and so the user is not tempted to
# scroll-past.  Legal research basis:
#   - Mexico LFPDPPP 2025 amendments: consent must be free, specific,
#     informed, and demonstrable.
#   - GDPR Art.7: clear affirmative action, distinguishable, withdrawable.
#   - California BOT Act SB-1001: bot disclosure required for commercial
#     contact with CA residents (user_direct mode places that duty on
#     the user, not Selva).
#   - CASL Canada: sender-identification must name both the sender and
#     the person on whose behalf the message is sent.
#   - CAN-SPAM: accurate From/Reply-To headers required.
#   - LGPD Brazil: explicit consent with processing record.
CONSENT_CLAUSES: dict[str, dict[str, str]] = {
    "user_direct": {
        "label": "Send as me, no AI disclosure",
        "typed_phrase": "I authorize Selva to send messages as me without AI disclosure",
        "heads_up": (
            "Heads up: outbound sends under this mode go out from your "
            "mailbox with no AI disclosure. In some jurisdictions "
            "(notably California under SB-1001 for commercial contact, "
            "and Canada under CASL for sender identification) this can "
            "shift legal exposure to you. You are responsible for "
            "compliance with the laws that apply to your recipients."
        ),
        "clause_body": (
            "I, acting on behalf of my organization, authorize Selva to "
            "generate and dispatch outbound communications (email, SMS, "
            "and equivalent channels) from my personal sending identity "
            "without any AI-generated or agent-origin disclosure in the "
            "message body or headers. I confirm that I have reviewed "
            "the jurisdictional heads-up, that my consent is free, "
            "specific, and informed, and that I may withdraw this "
            "consent at any time via the office settings. This consent "
            "is recorded immutably for audit purposes."
        ),
    },
    "dyad_selva_plus_user": {
        "label": "Co-branded — Selva on behalf of me",
        "typed_phrase": "I authorize Selva to send on my behalf with co-branded attribution",
        "heads_up": (
            "Outbound messages will carry co-branded attribution "
            '("Selva on behalf of <you>"). This is the default and '
            "lowest-risk option for most jurisdictions."
        ),
        "clause_body": (
            "I authorize Selva to generate and dispatch outbound "
            "communications on behalf of my organization with dual "
            "attribution naming both Selva (as the sending platform) "
            "and myself (as the principal). I confirm my consent is "
            "free, specific, and informed, and that I may withdraw it "
            "at any time."
        ),
    },
    "agent_identified": {
        "label": "Selva agent — from the agent's own address",
        "typed_phrase": "I authorize Selva agents to send from their own selva.town addresses",
        "heads_up": (
            "Messages will be sent from `<agent-slug>@selva.town` and "
            "clearly identify the agent. Selva.town must be added to "
            "your SPF/DKIM/DMARC records before sends can leave."
        ),
        "clause_body": (
            "I authorize named Selva agents to dispatch outbound "
            "communications from the selva.town domain, disclosing "
            "themselves as autonomous agents acting for my "
            "organization. I confirm my consent is free, specific, and "
            "informed, and that I may withdraw it at any time."
        ),
    },
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class OnboardingStatus(BaseModel):
    """Whether the tenant has completed voice-mode onboarding."""

    voice_mode: str | None
    onboarding_complete: bool
    clause_version: str


class VoiceModeSelection(BaseModel):
    """Payload for POST /voice-mode and PUT /settings/outbound-voice."""

    mode: str = Field(..., description="One of the three legal voice modes.")
    typed_confirmation: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Verbatim typed phrase matching the mode's clause.",
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        if v not in VOICE_MODES:
            raise ValueError(f"mode must be one of {VOICE_MODES}")
        return v


class VoiceModePreview(BaseModel):
    """Clause preview for a single mode (read-only)."""

    mode: str
    label: str
    typed_phrase: str
    heads_up: str
    clause_body: str
    clause_version: str


class TenantIdentityResponse(BaseModel):
    """Server-resolved outbound identity for a tenant.

    Returned by ``GET /onboarding/tenant-identity``. Used by the email
    tools to populate the ``From:`` header without trusting any
    LLM-supplied kwargs (which would be a prompt-injection vector for
    sender spoofing within the tenant's verified Resend domain).

    Fields are nullable individually so the tool can detect partial
    configuration (e.g. brand_name set but no primary contact email
    resolved yet) and fail-closed on the missing piece.

    **Precedence chain** (resolved server-side; LLM has zero influence):

    - ``user_email``: ``tenant_configs.outbound_user_email`` (first-class,
      tenant-configurable via the office UI) → fall back to
      ``tenant_identities.primary_contact_email`` (legacy MADFAM-ops-set
      field).
    - ``user_name``: ``tenant_configs.outbound_user_name`` →
      ``tenant_configs.brand_name`` → ``tenant_identities.legal_name`` →
      ``tenant_configs.razon_social``.
    - ``org_name``: ``tenant_identities.legal_name`` →
      ``tenant_configs.razon_social`` → ``tenant_configs.brand_name``.
    - ``agent_slug``: ``tenant_configs.outbound_agent_slug`` if set and
      in the email-tool allow-list, else None (caller falls back to its
      own per-tool default — never to LLM-supplied raw text).
    """

    user_email: str | None = Field(
        default=None,
        description=(
            "Primary outbound mailbox for the tenant (drives From: in "
            "user_direct/dyad modes and Reply-To across all modes). "
            "Resolves tenant_configs.outbound_user_email then "
            "tenant_identities.primary_contact_email."
        ),
    )
    user_name: str | None = Field(
        default=None,
        description=(
            "Display name for the From: header. Resolves "
            "tenant_configs.outbound_user_name then brand_name then "
            "tenant_identities.legal_name then razon_social."
        ),
    )
    org_name: str | None = Field(
        default=None,
        description=(
            "Organization legal name for the agent_identified signature "
            "block. Sourced from tenant_identities.legal_name with "
            "fallback to tenant_configs.razon_social or brand_name."
        ),
    )
    agent_slug: str | None = Field(
        default=None,
        description=(
            "Optional tenant-configured agent slug for agent_identified "
            "mode. NULL means the email tool should fall back to its "
            "own per-call role → slug resolution. Constrained to the "
            "5-entry allow-list (sales/support/growth/ops/research) at "
            "PUT time."
        ),
    )


# ---------------------------------------------------------------------------
# Outbound identity update payload
# ---------------------------------------------------------------------------

# Mirror of ``email_tools._AGENT_ROLE_ALLOWLIST`` keys. Duplicated here
# rather than imported because nexus-api MUST NOT depend on selva_tools
# (worker package). Drift is caught by
# ``test_onboarding_outbound_identity.py::test_agent_slug_allowlist_in_sync``.
_AGENT_SLUG_ALLOWLIST = frozenset({"sales", "support", "growth", "ops", "research"})

# Same regex used by SendEmailTool (``email_tools._EMAIL_RE``). Conservative
# RFC-friendly check; rejects whitespace and missing @ / TLD.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OutboundIdentityUpdate(BaseModel):
    """Payload for PUT /api/v1/onboarding/tenant-identity.

    All three fields are optional. Submitting a field as ``None`` clears
    it (falls back to the legacy resolver chain on the next email send);
    omitting a field leaves the existing value untouched. To distinguish
    "omit" from "explicit null", the router uses ``model_dump(exclude_unset=True)``.
    """

    outbound_user_email: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Outbound mailbox for the From: address in user_direct + dyad "
            "modes (and Reply-To across all modes). Validated against "
            "_EMAIL_RE if non-null + non-empty."
        ),
    )
    outbound_user_name: str | None = Field(
        default=None,
        max_length=255,
        description="Display name shown in the From: header.",
    )
    outbound_agent_slug: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Tenant-pinned agent slug for agent_identified mode. Must "
            "be one of: sales, support, growth, ops, research."
        ),
    )

    @field_validator("outbound_user_email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Normalise whitespace; treat a trimmed empty string as "clear".
        stripped = v.strip()
        if not stripped:
            return None
        if not _EMAIL_RE.match(stripped):
            raise ValueError(
                f"outbound_user_email must be a valid email address (got: {stripped[:32]!r})"
            )
        return stripped

    @field_validator("outbound_user_name")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("outbound_agent_slug")
    @classmethod
    def _validate_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip().lower()
        if not stripped:
            return None
        if stripped not in _AGENT_SLUG_ALLOWLIST:
            raise ValueError(
                "outbound_agent_slug must be one of: "
                + ", ".join(sorted(_AGENT_SLUG_ALLOWLIST))
            )
        return stripped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request) -> str:
    """Return the client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _signing_secret() -> bytes:
    """Return the HMAC signing secret as bytes.

    Read from ``Settings.consent_ledger_signing_secret`` on every call so
    operators rotating the secret pick it up after a settings reload
    without restarting the process. ``Settings`` already refuses the
    ``dev-default-CHANGE-ME`` sentinel in production via
    ``_validate_config``.
    """
    return get_settings().consent_ledger_signing_secret.encode("utf-8")


def compute_signature(
    *,
    org_id: str,
    user_sub: str,
    mode: str,
    clause_version: str,
    typed_confirmation: str,
    created_at: datetime,
) -> str:
    """HMAC-SHA256 integrity digest over the ledger row's identifying fields.

    Uses HMAC with a server-only secret (``CONSENT_LEDGER_SIGNING_SECRET``)
    so an adversary with INSERT access on the ledger table cannot forge
    rows that pass ``verify_signature`` — they would need the secret
    held in the application process.

    The output is structurally identical to a plain SHA-256 hex digest
    (64 lowercase hex chars), so the ``consent_ledger.signature_sha256``
    column shape is unchanged. Rows signed under a previous secret (or
    under the pre-HMAC plain SHA-256 algorithm) will fail verification
    at audit time, which is the desired behaviour at the migration
    boundary.

    Exported (not underscore-prefixed) so auditors holding the secret
    can import this function to re-verify ledger rows offline.
    """
    payload = "|".join(
        [
            org_id,
            user_sub,
            mode,
            clause_version,
            typed_confirmation,
            created_at.isoformat(),
        ]
    )
    return hmac.new(_signing_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(entry: ConsentLedger) -> bool:
    """Recompute the HMAC-SHA256 digest and compare to the stored value.

    Returns True iff the stored digest matches a fresh computation over
    the row's current fields under the currently configured signing
    secret. False means either: (a) the row has been tampered with,
    (b) the signing secret has rotated, or (c) the row predates the
    HMAC migration. All three cases warrant audit attention.

    Normalizes ``created_at`` the same way the ingest path does
    (microseconds zeroed, UTC) so the round-trip through the DB does
    not cause a false-negative. Uses ``hmac.compare_digest`` for
    constant-time comparison to neutralize timing oracles.
    """
    created_at = entry.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    created_at = created_at.replace(microsecond=0)
    expected = compute_signature(
        org_id=entry.org_id,
        user_sub=entry.user_sub,
        mode=entry.mode,
        clause_version=entry.clause_version,
        typed_confirmation=entry.typed_confirmation,
        created_at=created_at,
    )
    return hmac.compare_digest(expected, entry.signature_sha256)


# Back-compat alias — keeps the internal call-site signature stable.
_compute_signature = compute_signature


async def _load_tenant(db: AsyncSession, org_id: str) -> TenantConfig:
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not configured for this organization",
        )
    return config


async def _record_consent(
    db: AsyncSession,
    *,
    request: Request,
    org_id: str,
    user: dict[str, Any],
    body: VoiceModeSelection,
    is_change: bool,
) -> ConsentLedger:
    """Validate typed confirmation, append consent row, update tenant."""
    clause = CONSENT_CLAUSES[body.mode]
    expected = clause["typed_phrase"]
    submitted = body.typed_confirmation.strip()

    if submitted.casefold() != expected.casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Typed confirmation does not match the required phrase.",
        )

    user_sub = str(user.get("sub") or user.get("user_id") or "unknown")
    user_email = str(user.get("email") or "")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must have a verified email to sign consent.",
        )

    # Truncate to whole seconds so the signature survives DB round-trips
    # (some backends drop sub-second precision on timestamp columns).
    created_at = datetime.now(UTC).replace(microsecond=0)
    signer_ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    signature = compute_signature(
        org_id=org_id,
        user_sub=user_sub,
        mode=body.mode,
        clause_version=CLAUSE_VERSION,
        typed_confirmation=submitted,
        created_at=created_at,
    )

    entry = ConsentLedger(
        org_id=org_id,
        user_sub=user_sub,
        user_email=user_email,
        mode=body.mode,
        clause_version=CLAUSE_VERSION,
        typed_confirmation=submitted,
        signer_ip=signer_ip,
        signer_user_agent=user_agent,
        signature_sha256=signature,
        created_at=created_at,
    )
    db.add(entry)

    tenant = await _load_tenant(db, org_id)
    tenant.voice_mode = body.mode
    tenant.updated_at = created_at

    await db.flush()
    await db.refresh(entry)

    event_type = "voice_mode.changed" if is_change else "voice_mode.selected"
    await emit_event_db(
        db,
        event_type=event_type,
        event_category="onboarding",
        org_id=org_id,
        payload={
            "mode": body.mode,
            "clause_version": CLAUSE_VERSION,
            "consent_ledger_id": str(entry.id),
            "user_sub": user_sub,
        },
    )

    logger.info(
        "voice_mode %s org_id=%s user_sub=%s mode=%s clause=%s ledger_id=%s",
        "changed" if is_change else "selected",
        org_id,
        user_sub,
        body.mode,
        CLAUSE_VERSION,
        entry.id,
    )
    return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/onboarding/status", response_model=OnboardingStatus)
async def onboarding_status(
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> OnboardingStatus:
    """Return whether the org has chosen a voice mode yet.

    Used by the UI to decide between routing the user to `/onboarding`
    or letting them into `/office`.
    """
    org_id = user.get("org_id", "default")
    result = await db.execute(select(TenantConfig).where(TenantConfig.org_id == org_id))
    config = result.scalar_one_or_none()
    voice_mode = config.voice_mode if config else None
    return OnboardingStatus(
        voice_mode=voice_mode,
        onboarding_complete=voice_mode is not None,
        clause_version=CLAUSE_VERSION,
    )


@router.get(
    "/onboarding/voice-mode/preview/{mode}",
    response_model=VoiceModePreview,
)
async def voice_mode_preview(mode: str) -> VoiceModePreview:
    """Return the clause text + heads-up for a single mode (read-only)."""
    if mode not in VOICE_MODES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown voice mode: {mode}",
        )
    clause = CONSENT_CLAUSES[mode]
    return VoiceModePreview(
        mode=mode,
        label=clause["label"],
        typed_phrase=clause["typed_phrase"],
        heads_up=clause["heads_up"],
        clause_body=clause["clause_body"],
        clause_version=CLAUSE_VERSION,
    )


@router.get(
    "/onboarding/tenant-identity",
    response_model=TenantIdentityResponse,
)
async def tenant_identity(
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantIdentityResponse:
    """Return the server-controlled outbound identity for the caller's tenant.

    Used by ``SendEmailTool`` and ``SendMarketingEmailTool`` to populate
    the ``From:`` header without trusting LLM-supplied kwargs. The LLM
    has no input on what address goes into the From header — sender
    identity is exclusively a server concern, sourced from the tenant's
    own configuration.

    Returns 403 for the unscoped ``platform`` org (worker tokens calling
    without ``X-Selva-Tenant-Org``). Returns 404 when the tenant has no
    ``tenant_configs`` row at all (i.e. truly unprovisioned). Returns
    200 with nullable fields when the tenant exists but has not yet
    populated the relevant fields — callers are expected to fail-closed
    on missing fields rather than substituting LLM-supplied defaults.
    """
    org_id = user.get("org_id")
    if not org_id or org_id == "platform":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant identity requires org-scoped auth (X-Selva-Tenant-Org header)",
        )

    config_row = await db.execute(
        select(TenantConfig).where(TenantConfig.org_id == org_id)
    )
    config = config_row.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant identity not configured",
        )

    # Resolve cross-service identity (legal_name + primary_contact_email)
    # via the tenant_identities map. canonical_id == janua_org_id ==
    # tenant_configs.org_id by convention (see migration 0024 design).
    identity_row = await db.execute(
        select(TenantIdentity).where(TenantIdentity.canonical_id == org_id)
    )
    identity = identity_row.scalar_one_or_none()

    legal_name = identity.legal_name if identity else None
    primary_contact_email = identity.primary_contact_email if identity else None

    # Precedence chain (migration 0026): prefer the first-class
    # tenant-configurable columns over the legacy fallback chain. This
    # is the regression-fix path — tenants who set their outbound
    # identity via the office UI no longer need MADFAM ops to populate
    # ``tenant_identities`` for them.
    #
    # ``user_email``: tenant-set outbound > legacy primary_contact_email.
    # ``user_name``: tenant-set name > white-label brand > legal name >
    # fiscal razon_social. The white-label brand still beats legal_name
    # here because tenants who set brand_name explicitly want that to
    # appear in the From: header.
    user_email = config.outbound_user_email or primary_contact_email
    user_name = (
        config.outbound_user_name
        or config.brand_name
        or legal_name
        or config.razon_social
    )
    # Org name for the agent_identified signature block — preserve the
    # pre-0026 chain since legal_name (matches the consent ledger) is
    # the right anchor for legal/regulatory disclosure.
    org_name = legal_name or config.razon_social or config.brand_name
    # Tenant-pinned agent slug (None means "let the email tool pick its
    # own per-call default"). Already constrained to the allow-list at
    # PUT time, so the value is safe to pass through unchanged.
    agent_slug = config.outbound_agent_slug

    return TenantIdentityResponse(
        user_email=user_email,
        user_name=user_name,
        org_name=org_name,
        agent_slug=agent_slug,
    )


@router.put(
    "/onboarding/tenant-identity",
    response_model=TenantIdentityResponse,
    dependencies=[Depends(require_non_guest)],
)
async def update_tenant_identity(
    body: OutboundIdentityUpdate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantIdentityResponse:
    """Tenant-side update of outbound identity columns on tenant_configs.

    Lets tenants configure From: header inputs from the office settings
    UI without requiring MADFAM ops to populate tenant_identities. The
    ``org_id`` is forced from the JWT (matching every other tenant-
    scoped mutation) — request bodies cannot specify it.

    Submitting ``null`` for a field clears it (the legacy fallback
    chain takes over on the next email send). Omitting a field leaves
    the existing value untouched (uses ``exclude_unset=True``).

    Validation:

    - ``outbound_user_email``: must match ``[^@\\s]+@[^@\\s]+\\.[^@\\s]+``.
    - ``outbound_agent_slug``: must be in the 5-entry email-tool
      allow-list (sales/support/growth/ops/research).
    - ``outbound_user_name``: trimmed; max 255 chars (Pydantic).

    Audit: emits ``tenant_identity.updated`` to ``task_events`` with
    ``event_category="onboarding"`` so the change is in the audit
    trail. Payload includes the keys that changed but not the values
    (avoid leaking PII into the event log).
    """
    org_id = user.get("org_id")
    if not org_id or org_id == "platform":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant identity requires org-scoped auth (X-Selva-Tenant-Org header)",
        )

    config = await _load_tenant(db, org_id)

    # ``exclude_unset=True`` distinguishes "user wants to clear this
    # field to null" (key present with null value) from "user did not
    # touch this field" (key absent). The first should overwrite to
    # NULL; the second should leave the existing column unchanged.
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        # Nothing to do — return the current resolved identity. Avoids
        # writing a no-op audit row.
        return await tenant_identity(user=user, db=db)

    changed_keys: list[str] = []
    for key, value in updates.items():
        previous = getattr(config, key, None)
        if previous != value:
            setattr(config, key, value)
            changed_keys.append(key)

    if not changed_keys:
        # Submitted values matched stored values — no DB write, no event.
        return await tenant_identity(user=user, db=db)

    config.updated_at = datetime.now(UTC).replace(microsecond=0)
    await db.flush()

    user_sub = str(user.get("sub") or user.get("user_id") or "unknown")
    user_agent = request.headers.get("user-agent")
    actor_ip = _get_client_ip(request)
    await emit_event_db(
        db,
        event_type="tenant_identity.updated",
        event_category="onboarding",
        org_id=org_id,
        payload={
            "changed_keys": sorted(changed_keys),
            "actor_sub": user_sub,
            "actor_ip": actor_ip,
            "user_agent": user_agent,
        },
    )

    return await tenant_identity(user=user, db=db)


@router.post(
    "/onboarding/voice-mode",
    response_model=OnboardingStatus,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_non_guest)],
)
async def select_voice_mode(
    body: VoiceModeSelection,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    idem: IdempotencyContext = Depends(get_idempotency_context),  # noqa: B008
) -> OnboardingStatus:
    """First-run voice-mode selection during onboarding.

    Fails with 409 if the tenant has already chosen a mode — use
    PUT /settings/outbound-voice to change it.

    Idempotency: when the caller sends ``Idempotency-Key`` header, a
    successful first-run selection is cached for 24h scoped by (org_id,
    POST, /api/v1/onboarding/voice-mode, key). Without this, a network
    blip on the first call would have the second call hit the 409
    "already selected" branch (because the first call did persist the
    consent ledger row + tenant_config update before the response was
    lost). Only the success path is cached — a 400 (typed-confirmation
    mismatch) or 409 (already resolved) leaves the cache empty.
    """
    if idem.is_replay and idem.cached is not None:
        return OnboardingStatus.model_validate(idem.cached)

    org_id = user.get("org_id", "default")
    tenant = await _load_tenant(db, org_id)

    if tenant.voice_mode is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Voice mode already selected. Use PUT /api/v1/settings/outbound-voice to change it."
            ),
        )

    await _record_consent(
        db,
        request=request,
        org_id=org_id,
        user=user,
        body=body,
        is_change=False,
    )

    response = OnboardingStatus(
        voice_mode=body.mode,
        onboarding_complete=True,
        clause_version=CLAUSE_VERSION,
    )

    # Cache only on success. No-op when Idempotency-Key was absent.
    await idem.save(response.model_dump(mode="json"))

    return response


@router.put(
    "/settings/outbound-voice",
    response_model=OnboardingStatus,
    dependencies=[Depends(require_non_guest)],
)
async def change_voice_mode(
    body: VoiceModeSelection,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> OnboardingStatus:
    """Change the tenant's voice mode from the /office modal.

    Appends a new `voice_mode.changed` row to the consent ledger (never
    overwrites the previous selection — the ledger is append-only).
    """
    org_id = user.get("org_id", "default")
    tenant = await _load_tenant(db, org_id)

    if tenant.voice_mode == body.mode:
        return OnboardingStatus(
            voice_mode=tenant.voice_mode,
            onboarding_complete=True,
            clause_version=CLAUSE_VERSION,
        )

    await _record_consent(
        db,
        request=request,
        org_id=org_id,
        user=user,
        body=body,
        is_change=True,
    )

    return OnboardingStatus(
        voice_mode=body.mode,
        onboarding_complete=True,
        clause_version=CLAUSE_VERSION,
    )
