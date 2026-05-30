"""Application configuration via environment variables and .env files."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, NoDecode

# Resolve project root so env_file works regardless of CWD.
# config.py -> nexus_api -> nexus-api -> apps -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _parse_cors_origins(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return value
    return []


class Settings(BaseSettings):
    """Central configuration for the Nexus API.

    All values are read from environment variables (case-insensitive) and
    can be overridden via a ``.env`` file at the project root.
    """

    # -- Infrastructure -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://autoswarm:autoswarm@localhost:5432/autoswarm"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800  # 30 minutes
    db_pool_timeout: int = 30
    # Optional connection string for the ``app_admin`` BYPASSRLS Postgres
    # role created by migration 0028. When set, ``admin_session()`` opens
    # sessions against this connection so cross-tenant maintenance ops
    # (reap-stale, audit exports, future Celery jobs) skip RLS policy
    # checks at the database level. When empty, ``admin_session()`` falls
    # back to ``database_url`` and logs a warning -- strict-mode policies
    # will then return zero rows for cross-tenant queries, which is the
    # deliberate "misconfigured" signal. Set to e.g.
    # ``postgresql+asyncpg://app_admin:...@host:5432/autoswarm``.
    database_admin_url: str = ""
    # Pool sizing for the admin engine. Cross-tenant ops are rare by
    # design so the pool is intentionally small -- bumping it is a smell.
    db_admin_pool_size: int = 2
    db_admin_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379"

    # -- Auth (Janua OIDC) ----------------------------------------------------
    janua_issuer_url: str = ""
    janua_client_id: str = "autoswarm-office"
    janua_client_secret: str = ""

    # -- Billing (Dhanam) -----------------------------------------------------
    dhanam_api_url: str = ""
    dhanam_webhook_secret: str = ""
    dhanam_catalog_apply_secret: str = ""

    # -- Tulana (pricing intelligence handoff) --------------------------------
    tulana_api_url: str = ""
    tulana_selva_webhook_secret: str = ""

    # -- Gateway (GitHub webhooks) ---------------------------------------------
    github_webhook_secret: str = ""

    # -- Enclii (deployment webhooks) ------------------------------------------
    enclii_webhook_secret: str = ""

    # -- Harness communication gateway ---------------------------------------
    # Multi-channel gateway tokens and channel-specific shared secrets.
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    discord_webhook_secret: str = ""
    slack_signing_secret: str = ""  # Slack v0 HMAC signing secret
    teams_webhook_secret: str = ""  # Microsoft Teams outgoing-webhook / relay secret
    irc_webhook_secret: str = ""  # IRC bridge HMAC/Bearer relay secret
    qq_webhook_secret: str = ""  # QQ Bot HMAC/Bearer relay secret
    yuanbao_webhook_secret: str = ""  # Yuanbao HMAC/Bearer relay secret
    # Comma-separated authorised sender addresses for the inbound-email
    # parse webhook (POST /api/v1/gateway/email/inbound). Acts as the
    # equivalent of a shared HMAC secret for the other 14 gateway
    # handlers: empty string means the endpoint is disabled (503), not
    # "accept any sender". See `_require_inbound_allowlist` in
    # `routers/gateway.py` for the threat model.
    gateway_email_whitelist: str = ""
    twilio_auth_token: str = ""  # Twilio account auth token
    twilio_account_sid: str = ""  # Twilio account SID

    # MCP tool server credentials
    tavily_api_key: str = ""
    github_token: str = ""

    # Continuous learning / skills registry
    selva_skills_dir: str = "/var/lib/autoswarm/skills"
    skill_refine_interval_days: int = 7  # Refine skills older than N days

    # Memory compaction
    autoswarm_state_db_path: str = "/var/lib/autoswarm/autoswarm_state.db"
    memory_retention_days: int = 30  # Compact transcripts older than N days

    # -- AI Inference ---------------------------------------------------------
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    deepinfra_api_key: str | None = None
    siliconflow_api_key: str | None = None
    moonshot_api_key: str | None = None
    groq_api_key: str | None = None
    mistral_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    org_config_path: str = "~/.autoswarm/org-config.yaml"

    # -- Analytics ------------------------------------------------------------
    posthog_api_key: str = ""
    posthog_host: str = ""

    # -- Webhooks -------------------------------------------------------------
    autoswarm_webhook_secret: str = ""

    # -- Karafiel (RFC / SAT validation) ----------------------------------------
    karafiel_api_url: str = ""

    # -- Phynd-CRM ------------------------------------------------------------
    phynd_crm_url: str | None = None

    # -- Worker-to-API auth ---------------------------------------------------
    worker_api_token: str = "dev-bypass"  # Shared secret for worker/gateway → API calls

    # -- Colyseus -------------------------------------------------------------
    colyseus_secret: str = "change-me-in-production"

    # -- Server ---------------------------------------------------------------
    environment: str = "production"
    port: int = 4300
    public_app_url: str = Field(
        default="http://localhost:4301",
        validation_alias=AliasChoices("PUBLIC_APP_URL", "NEXT_PUBLIC_APP_URL"),
    )
    cors_origins: Annotated[
        list[str],
        NoDecode,
        BeforeValidator(_parse_cors_origins),
    ] = [
        "http://localhost:4301",
        "http://localhost:4302",
    ]

    # -- Dangerous Command Approval (Gap 2) -----------------------------------
    auto_approve_dangerous: bool = False  # Set True in CI — bypasses HITL gate
    command_approval_timeout_seconds: int = 60  # Fail-closed after N seconds

    # -- Plugin Architecture (Gap 3) ------------------------------------------
    plugin_dirs: list[str] = []  # Additional plugin scan directories

    # -- Gateway Wave 2 (Gap 8) -----------------------------------------------
    # WhatsApp (Meta Cloud API)
    whatsapp_verify_token: str = ""  # Used during webhook registration challenge
    whatsapp_access_token: str = ""  # Meta Graph API access token
    # Matrix / Element
    matrix_appservice_token: str = ""  # Shared secret for appservice auth
    matrix_homeserver_url: str = ""  # e.g. https://matrix.example.com
    # Mattermost
    mattermost_token: str = ""  # Shared secret from Mattermost slash command
    # Signal (via signal-cli REST)
    signal_cli_url: str = ""  # URL of running signal-cli REST API
    signal_allowed_numbers: str = ""  # Comma-separated E.164 source numbers

    # -- Gateway Wave 3 (Phase 1 hardening) -----------------------------------
    # These were previously read via getattr(settings, "...", None) — moving
    # them to explicit fields so the fail-closed _require_secret pattern has
    # a single source of truth and tests can monkeypatch the field directly.
    dingtalk_app_secret: str = ""  # DingTalk webhook HMAC-SHA256 secret
    feishu_app_secret: str = ""  # Feishu/Lark event webhook signing secret
    wecom_token: str = ""  # WeCom outgoing webhook query-param token
    weixin_app_token: str = ""  # Weixin via WxPusher appToken
    bluebubbles_password: str = ""  # BlueBubbles iMessage bridge basic-auth pwd
    ha_token: str = ""  # Home Assistant long-lived bearer token

    # -- Security -------------------------------------------------------------
    dev_auth_bypass: bool = False
    rate_limit_per_minute: int = 60
    dispatch_rate_limit: int = 10
    dispatch_rate_window: int = 60
    csp_extra_sources: str = ""
    log_format: str = "json"

    # -- WebSocket message-flood guards ---------------------------------------
    # Per-client inbound message limits on long-lived WS connections.
    # /events/ws and /approvals/ws share the same defaults (the OpsFeed
    # and approval queue UIs have similar interaction patterns) but are
    # split so they can be tuned independently.
    events_ws_rate_limit: int = 30
    events_ws_rate_window_seconds: float = 60.0
    approvals_ws_rate_limit: int = 30
    approvals_ws_rate_window_seconds: float = 60.0

    # -- Health endpoint dashboard sizing -------------------------------------
    # How many recent DLQ entries `/api/v1/health/dlq-stats` returns.
    # Bumped here when an ops dashboard wants a deeper history without a
    # code change.
    dlq_recent_limit: int = 10

    # HMAC signing secret for the consent_ledger row digests. Required in
    # production — the literal sentinel ``dev-default-CHANGE-ME`` is
    # rejected by ``_validate_config`` outside the development environment.
    # Old rows signed under a previous secret will fail
    # ``verify_signature``, which is the desired auditable behaviour at
    # the migration boundary.
    consent_ledger_signing_secret: str = "dev-default-CHANGE-ME"

    # -- Revenue-loop probe (A.7) ---------------------------------------------
    # Bearer token the external probe presents to hit /api/v1/probe/*.
    # Empty default means the endpoints return 503 (feature not configured),
    # matching the pattern of other optional external-provider tokens.
    nexus_probe_token: str = ""

    # Default outbound From: header used by the probe contract validator and
    # any other dry-run paths that need a stable sender identity. Workers
    # that actually send email use the per-tenant identity resolved by
    # ``_fetch_tenant_identity`` (see CLAUDE.md "Outbound email lockdown")
    # — this value is *not* a fallback for live sends.
    email_from: str = "noreply@selva.town"

    # -- Billing router (Dhanam-first) ----------------------------------------
    # When true (default), Stripe/POS webhooks MUST land on Dhanam first.
    # Selva consumes Dhanam-normalized events at /api/v1/billing/webhooks/dhanam.
    # Direct /api/v1/stripe/webhook is break-glass only when this is false.
    billing_via_dhanam: bool = True

    # -- Stripe webhook (legacy break-glass when billing_via_dhanam=false) ----
    # Required when ``feature_stripe_mxn_live`` is true (see
    # _validate_config below). Empty default means the webhook endpoint
    # responds 503 — same fail-closed pattern as the gateway providers.
    # Secret is the Stripe Dashboard webhook signing secret (whsec_...).
    stripe_webhook_secret: str = ""
    feature_stripe_mxn_live: bool = False

    # JSON mapping of Stripe price IDs — **deprecated when billing_via_dhanam=true**.
    # Price→tier mapping belongs in Dhanam (canonical POS router). Selva's direct
    # Stripe handlers consult this map only in break-glass mode.
    stripe_price_to_tier_map: dict[str, str] = {}

    model_config = {
        "env_file": (str(_PROJECT_ROOT / ".env"), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }

    @model_validator(mode="after")
    def _validate_config(self) -> Settings:
        """Validate configuration values and warn about insecure defaults."""
        if self.dev_auth_bypass and self.environment != "development":
            warnings.warn(
                "DEV_AUTH_BYPASS is enabled in a non-development environment! "
                "This is a security risk.",
                stacklevel=2,
            )

        if not self.database_url.startswith(("postgresql", "sqlite")):
            raise ValueError(
                f"DATABASE_URL must start with 'postgresql' or 'sqlite', "
                f"got: {self.database_url[:20]}..."
            )

        if not self.redis_url.startswith("redis"):
            raise ValueError(
                f"REDIS_URL must start with 'redis://' or 'rediss://', "
                f"got: {self.redis_url[:20]}..."
            )

        if self.colyseus_secret == "change-me-in-production" and self.environment != "development":
            raise ValueError(
                "COLYSEUS_SECRET must be set in production (cannot use default). "
                "Generate with: openssl rand -hex 32"
            )

        if (
            self.consent_ledger_signing_secret == "dev-default-CHANGE-ME"
            and self.environment == "production"
        ):
            raise ValueError(
                "CONSENT_LEDGER_SIGNING_SECRET must be set in production "
                "(cannot use the dev-default sentinel). The consent ledger "
                "is a legal-compliance audit trail (LFPDPPP, GDPR, CASL, "
                "SB-1001) and its row digests must be HMAC-signed with a "
                "server-only secret. Generate with: openssl rand -hex 32"
            )

        if self.worker_api_token == "dev-bypass" and self.environment == "production":
            raise ValueError(
                "WORKER_API_TOKEN=='dev-bypass' is not allowed in production. "
                "Set a strong shared secret (openssl rand -hex 32) — the "
                "worker→API auth path uses constant-time comparison against "
                "this value, and the dev sentinel is publicly known."
            )

        if (
            self.feature_stripe_mxn_live
            and not self.billing_via_dhanam
            and not self.stripe_webhook_secret
            and self.environment == "production"
        ):
            raise ValueError(
                "STRIPE_WEBHOOK_SECRET is required when FEATURE_STRIPE_MXN_LIVE "
                "is true and BILLING_VIA_DHANAM is false. Prefer Dhanam-first "
                "billing: set BILLING_VIA_DHANAM=true and configure webhooks on Dhanam."
            )

        return self


def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
