"""SQLAlchemy ORM models for the AutoSwarm Nexus database."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Department(Base):
    """A virtual office department that houses agents."""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    max_agents: Mapped[int] = mapped_column(Integer, default=5)
    position_x: Mapped[int] = mapped_column(Integer, default=0)
    position_y: Mapped[int] = mapped_column(Integer, default=0)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    agents: Mapped[list[Agent]] = relationship(
        "Agent", back_populates="department", lazy="selectin"
    )


class Agent(Base):
    """A swarm agent that belongs to a department and executes tasks."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="coder")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")
    level: Mapped[int] = mapped_column(Integer, default=1)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    skill_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    synergy_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    # Performance tracking (migration 0013)
    tasks_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_denial_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_task_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_task_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    department: Mapped[Department | None] = relationship(
        "Department", back_populates="agents", lazy="selectin"
    )


class ApprovalRequest(Base):
    """A human-in-the-loop approval request created when an agent hits an interrupt."""

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    action_category: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[Agent] = relationship("Agent", lazy="selectin")


class SwarmTask(Base):
    """A task dispatched to one or more agents in the swarm."""

    __tablename__ = "swarm_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    graph_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sequential")
    assigned_agent_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Queue tracking (migration 0004)
    stream_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Workflow reference (migration 0005)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )


class Workflow(Base):
    """A custom workflow definition stored as YAML."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    yaml_content: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Artifact(Base):
    """A task output artifact persisted in storage."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swarm_tasks.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/plain")
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ComputeTokenLedger(Base):
    """Immutable ledger of compute token debits and credits."""

    __tablename__ = "compute_token_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swarm_tasks.id"), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SkillMarketplaceEntry(Base):
    """A published skill available in the marketplace for installation."""

    __tablename__ = "skill_marketplace_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    yaml_content: Mapped[str] = mapped_column(Text, nullable=False)
    readme: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    ratings: Mapped[list[SkillRating]] = relationship(
        "SkillRating",
        back_populates="entry",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class SkillRating(Base):
    """A user rating and optional review for a marketplace skill entry."""

    __tablename__ = "skill_ratings"
    __table_args__ = (UniqueConstraint("entry_id", "user_id", name="uq_skill_rating_entry_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_marketplace_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entry: Mapped[SkillMarketplaceEntry] = relationship(
        "SkillMarketplaceEntry", back_populates="ratings", lazy="selectin"
    )


class CalendarConnection(Base):
    """A user's connected calendar (Google or Microsoft)."""

    __tablename__ = "calendar_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Map(Base):
    """A custom office map stored as TMJ (Tiled Map JSON)."""

    __tablename__ = "maps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    tmj_content: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class TaskEvent(Base):
    """INSERT-only event record for full-stack task observability."""

    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task_created", "task_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("swarm_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    graph_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChatMessage(Base):
    """A persistent chat message in a room."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    room_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_session_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Wave 4 models (Gap 2: Command Approvals, Gap 3: Cron Scheduler)
# ---------------------------------------------------------------------------


class ApprovalStatus(enum.StrEnum):
    """Status for dangerous-command approval requests."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class CommandApprovalRequest(Base):
    """Approval gate for dangerous commands detected by the ACP QA Oracle."""

    __tablename__ = "command_approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ScheduledAction(enum.StrEnum):
    """Actions that can be scheduled via cron expressions."""

    ACP_INITIATE = "acp_initiate"
    SKILL_REFINE = "skill_refine"
    MEMORY_COMPACT = "memory_compact"
    # Outbound public-social post (Reddit MVP; X/LinkedIn parity later).
    # Schedules carry the playbook id + payload; the worker invokes the
    # SOCIAL_POST-categorised tool and the playbook's HITL gate fires
    # the same way as for ad-hoc dispatches.
    SOCIAL_POST = "social_post"


class Schedule(Base):
    """A user-defined recurring schedule executed by Celery Beat."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cron_expr: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[ScheduledAction] = mapped_column(Enum(ScheduledAction), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Multi-tenant enterprise provisioning (migration 0015)
# ---------------------------------------------------------------------------


class TenantConfig(Base):
    """Per-organization configuration for multi-tenant operations.

    Stores business identity (RFC, razon social), localization preferences,
    ecosystem integration references (Karafiel, Dhanam, Phyne), feature
    flags, and resource limits.
    """

    __tablename__ = "tenant_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # Business identity
    rfc: Mapped[str | None] = mapped_column(String(13), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)
    regimen_fiscal: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Localization
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="es-MX")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="America/Mexico_City")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MXN")

    # Ecosystem integration references
    karafiel_org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dhanam_space_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phyne_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Feature flags
    cfdi_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intelligence_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Resource limits
    max_agents: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_daily_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Enterprise SSO (migration 0016)
    janua_connection_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # White-label branding (migration 0016)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_primary_color: Mapped[str | None] = mapped_column(
        String(7), nullable=True
    )  # hex e.g. #4a9e6e

    # Outbound voice mode (migration 0018). NULL = onboarding incomplete;
    # no outbound sends allowed until set. CHECK constraint in DB pins
    # values to the 3 legal modes.
    voice_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Stripe subscription state (migration 0027). Populated by the Stripe
    # webhook handlers in ``routers/stripe_webhooks.py`` -- never written
    # by application code directly. ``stripe_customer_id`` is the lookup
    # key webhook handlers use to resolve a tenant from any
    # ``customer.subscription.*`` or ``invoice.*`` event (UNIQUE +
    # indexed at the DB level). ``subscription_status`` mirrors Stripe
    # values (``active``, ``trialing``, ``past_due``, ``cancelled``, ...);
    # NULL means "no Stripe subscription on file". ``subscription_tier``
    # is the Selva tier slug derived from the price ID via
    # ``Settings.stripe_price_to_tier_map`` and matches a key in
    # ``billing_tiers.TIER_DAILY_TASK_LIMIT``.
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Outbound identity (migration 0026). First-class columns so tenants
    # can configure From: header inputs from the office UI without ops
    # intervention. All nullable — the email lockdown's fallback chain
    # (brand_name / razon_social / tenant_identities.primary_contact_email)
    # still applies for tenants who haven't populated these columns.
    # ``outbound_user_email`` drives the From: address in user_direct +
    # dyad modes (and Reply-To across all modes). ``outbound_user_name``
    # is the display name for that address. ``outbound_agent_slug``
    # constrains agent_identified mode to a specific entry of the
    # server-side allow-list (sales/support/growth/ops/research). NULL on
    # any of these means "use the legacy fallback chain", not "block".
    outbound_user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outbound_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outbound_agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ---------------------------------------------------------------------------
# Audit trail (migration 0017)
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Immutable audit log for state-changing API actions.

    Every POST, PUT, PATCH, DELETE request that reaches a 2xx response is
    recorded with the authenticated user, resource path, and action details.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_org_created", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # POST, PUT, PATCH, DELETE
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Outbound voice-mode consent ledger (migration 0018)
# ---------------------------------------------------------------------------


class ConsentLedgerSigningKey(Base):
    """Per-period HMAC signing key registry (migration 0030).

    Each row is a key version that has ever been current. The active
    key has ``is_current=True`` and ``retired_at=NULL``; promoted-away
    keys have ``is_current=False`` and ``retired_at=<promotion time>``.

    Append-only at the application layer (UPDATE/DELETE revoked from
    ``autoswarm_app`` in migration 0030). Promotion is the one
    documented mutation, performed via
    ``POST /api/v1/admin/consent-ledger/promote-key`` inside a
    transaction that flips the previous current row to retired and
    inserts a new row marked current.

    A partial unique index on ``is_current`` enforces "at most one
    current key" at the DB layer (Postgres only — see migration).
    """

    __tablename__ = "consent_ledger_signing_keys"

    key_version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ConsentLedger(Base):
    """Append-only record of voice-mode consent events.

    UPDATE and DELETE are revoked from the app role at the DB level (see
    migration 0018). Writes are the only legal operation — replay the log
    to audit consent history.

    The ``signing_key_version`` column (migration 0030) records which
    HMAC key version signed this row, so verification still works
    after a key rotation. The verifier looks up the row's
    ``signing_key_version`` in ``consent_ledger_signing_keys`` and
    recomputes the HMAC under that key's value. Pre-0030 rows
    backfill to version 1 (the bootstrap key).
    """

    __tablename__ = "consent_ledger"
    __table_args__ = (
        Index("ix_consent_ledger_org_created", "org_id", "created_at"),
        Index("ix_consent_ledger_user", "user_sub"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    clause_version: Mapped[str] = mapped_column(String(16), nullable=False)
    typed_confirmation: Mapped[str] = mapped_column(Text, nullable=False)
    signer_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    signer_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signing_key_version: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("consent_ledger_signing_keys.key_version"),
        nullable=False,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# RFC 0005 — Selva K8s secret write audit log (migration 0019)
# ---------------------------------------------------------------------------


class SecretAuditLog(Base):
    """Append-only audit row for every K8s Secret write attempt.

    See ``internal-devops/rfcs/0005-selva-secret-management.md`` §"Audit
    trail" for the schema contract. UPDATE/DELETE are revoked from the
    app role at the DB level in migration 0019 — corrections land as
    new rows with ``rollback_of_id`` set, never as mutations.

    Crucially, ``value_sha256_prefix`` is exactly 8 hex chars: enough
    to correlate rotations of the same secret (same prefix before/after
    a deploy), not enough to brute-force the original value.
    """

    __tablename__ = "secret_audit_log"
    __table_args__ = (
        Index(
            "ix_secret_audit_target",
            "target_cluster",
            "target_namespace",
            "target_secret_name",
            "target_key",
        ),
        Index("ix_secret_audit_created", "created_at"),
        Index("ix_secret_audit_approval", "approval_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # -- Actors ---------------------------------------------------------
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- Target ---------------------------------------------------------
    target_cluster: Mapped[str] = mapped_column(String(64), nullable=False)
    target_namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    target_secret_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)

    # -- Write intent + hash ------------------------------------------
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    # Exactly 8 hex chars. RFC 0005 §"Audit trail" — enough for
    # rotation correlation, not a brute-forceable fingerprint.
    value_sha256_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    predecessor_sha256_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # -- Approval chain ------------------------------------------------
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # JSON: [{"user_sub": "...", "approved_at": "ISO-8601"}, ...]
    approval_chain: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    # -- Lifecycle -----------------------------------------------------
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # -- Tamper-evidence hash -----------------------------------------
    # Same shape as ``ConsentLedger.signature_sha256``: a SHA-256 over
    # the row's identifying fields so any post-insert mutation is
    # detectable via ``verify_signature``.
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# RFC 0006 — Selva GitHub admin audit log (migration 0020)
# ---------------------------------------------------------------------------


class GithubAdminAuditLog(Base):
    """Append-only audit row for every ``github_admin.*`` tool invocation.

    See ``internal-devops/rfcs/0006-selva-github-admin-tools.md`` §"Audit
    trail" for the schema contract. UPDATE/DELETE are revoked from the
    app role at the DB level in migration 0020 — corrections land as
    new rows with ``rollback_of_id`` set, never as mutations.

    The GitHub PAT itself is NEVER stored. Only the 8-hex-char SHA-256
    prefix (``token_sha256_prefix``) crosses this model's boundary. That's
    enough to correlate a row to a PAT rotation window at audit time but
    not enough to brute-force the token.
    """

    __tablename__ = "github_admin_audit_log"
    __table_args__ = (
        Index(
            "ix_github_admin_audit_target",
            "target_org",
            "target_repo",
            "target_team_slug",
        ),
        Index("ix_github_admin_audit_created", "created_at"),
        Index("ix_github_admin_audit_approval", "approval_request_id"),
        Index("ix_github_admin_audit_operation", "operation", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # -- Actors ---------------------------------------------------------
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- Operation + target ----------------------------------------------
    # ``operation`` is one of: create_team, set_team_membership,
    # set_branch_protection, audit_team_membership. Enforced by CHECK.
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    target_org: Mapped[str] = mapped_column(String(255), nullable=False)
    target_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_team_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- PAT fingerprint (8 hex chars) ----------------------------------
    token_sha256_prefix: Mapped[str] = mapped_column(String(8), nullable=False)

    # -- Request + response payloads ------------------------------------
    # ``request_body`` is the full tool input (no PAT -- contract).
    # ``response_summary`` is a structured diff of what the apply step did.
    request_body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- Approval chain --------------------------------------------------
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # JSON: [{"user_sub": "...", "approved_at": "ISO-8601"}, ...]
    approval_chain: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    # -- Lifecycle -------------------------------------------------------
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # -- Tamper-evidence -------------------------------------------------
    # SHA-256 over the row's identifying fields. See
    # nexus_api.audit.github_admin_audit.verify_signature.
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# RFC 0007 — Selva ConfigMap audit log (migration 0021)
# ---------------------------------------------------------------------------


class ConfigmapAuditLog(Base):
    """Append-only audit row for every ``config.*`` tool invocation.

    See ``internal-devops/rfcs/0007-selva-configmap-and-feature-flag-tool.md``
    §"Audit trail" for the schema contract. UPDATE/DELETE are revoked from
    the app role at the DB level in migration 0021 — corrections land as
    new rows with ``rollback_of_id`` set, never as mutations.

    Unlike ``SecretAuditLog`` (which refuses to see the value at all),
    this ledger stores the 8-hex-char SHA-256 prefix of both the new and
    the predecessor value. That lets a forensic reviewer reconstruct a
    diff of which keys flipped without ever storing plaintext — important
    because ConfigMaps legitimately carry semi-sensitive data (internal
    hostnames, webhook URLs, cron expressions).

    ``target_key`` is nullable because ``list`` and (rarely) ``read``
    operations are not key-scoped.
    """

    __tablename__ = "configmap_audit_log"
    __table_args__ = (
        Index(
            "ix_configmap_audit_target",
            "target_cluster",
            "target_namespace",
            "target_configmap_name",
            "target_key",
        ),
        Index("ix_configmap_audit_created", "created_at"),
        Index("ix_configmap_audit_approval", "approval_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # -- Actors ---------------------------------------------------------
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Opaque correlation id set by the caller (tool or API). Lets ops
    # correlate an audit row to a specific worker task / HTTP request
    # without leaking internal IDs.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- Target ---------------------------------------------------------
    target_cluster: Mapped[str] = mapped_column(String(64), nullable=False)
    target_namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    target_configmap_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable: list/read-all operations are not key-scoped.
    target_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- Write intent + hash prefixes ----------------------------------
    # read / write / delete / list (see migration 0021 CHECK).
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    # Exactly 8 hex chars when present. Nullable for read/list/delete
    # operations. NEVER the raw value.
    value_sha256_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Predecessor value hash prefix — lets forensics reconstruct a
    # before/after diff for any key flip without plaintext on either side.
    previous_value_sha256_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # -- HITL enforcement snapshot -------------------------------------
    # One of "allow", "ask", "ask_dual" — records which gate was enforced
    # for this specific call (so we can post-hoc audit escalation decisions
    # on feature-flag keys without re-running the gate logic).
    hitl_level: Mapped[str] = mapped_column(String(16), nullable=False)

    # -- Approval chain ------------------------------------------------
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # JSON: [{"user_sub": "...", "approved_at": "ISO-8601"}, ...]
    approval_chain: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    # -- Lifecycle -----------------------------------------------------
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # -- Tamper-evidence -----------------------------------------------
    # SHA-256 over the row's identifying fields. See
    # nexus_api.audit.configmap_audit.verify_signature.
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# RFC 0008 — Selva provider webhook management audit log (migration 0022)
# ---------------------------------------------------------------------------


class WebhookAuditLog(Base):
    """Append-only audit row for every provider webhook operation.

    See ``internal-devops/rfcs/0008-selva-provider-webhook-management.md``
    §"Audit trail" for the schema contract. Mirrors ``secret_audit_log``
    append-only semantics: UPDATE/DELETE are revoked from the app role at
    the DB level in migration 0022; corrections land as new rows.

    The webhook signing secret returned by the provider is captured in
    worker-process memory for ~100ms and written directly via the RFC 0005
    secret writer. Only ``linked_secret_audit_id`` (FK → secret_audit_log)
    survives here — neither the signing secret nor the raw endpoint URL
    (which often carries tokens in its path) is ever stored on this row.

    ``target_url_sha256_prefix`` is exactly 8 hex chars: enough to
    correlate rotations of the same endpoint, not enough to brute-force
    the original URL if it embeds a token.
    """

    __tablename__ = "webhook_audit_log"
    __table_args__ = (
        Index(
            "ix_webhook_audit_target",
            "provider",
            "target_url_sha256_prefix",
        ),
        Index("ix_webhook_audit_created", "created_at"),
        Index("ix_webhook_audit_approval", "approval_request_id"),
        Index("ix_webhook_audit_webhook_id", "provider", "webhook_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # -- Actors ---------------------------------------------------------
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- Target ---------------------------------------------------------
    # Provider identifier: "stripe", "resend", "janua", ...
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Action: "create", "list", "delete", "register_oidc_redirect"
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # Provider-assigned webhook ID, if one was returned (None for list ops
    # and for pre-API validation rejections).
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # First 8 hex chars of SHA-256(endpoint_url). Never the raw URL —
    # webhook URLs often embed tokens in their paths.
    target_url_sha256_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Events registered on create/rotate (JSON array of strings). NULL
    # for non-Stripe providers and non-create actions.
    events_registered: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # -- Linked secret write (RFC 0005 chain) --------------------------
    # FK into ``secret_audit_log.id``. Populated whenever the provider
    # returned a signing secret that the tool handed off to
    # secrets.write_kubernetes_secret. NULL for list/delete/redirect ops
    # that don't mint a secret.
    linked_secret_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Human-readable pointer to the resulting K8s Secret for operators
    # (e.g. "karafiel/karafiel-secrets:STRIPE_WEBHOOK_SECRET"). This is
    # a REFERENCE — NOT the secret value. Safe to surface in UIs.
    resulting_secret_name: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # -- Approval chain ------------------------------------------------
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_chain: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # -- Lifecycle -----------------------------------------------------
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Request correlation ------------------------------------------
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- Tamper-evidence hash -----------------------------------------
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# HITL Confidence (Sprint 1 — observe only)
# ---------------------------------------------------------------------------
#
# The HITL confidence system tracks approve/modify/reject decisions per
# (agent, action_category, org, context_signature) bucket so that — in
# later sprints — policy can widen autonomy for buckets with sustained
# high approval rates. Sprint 1 is observe-only: we record decisions and
# roll them into `hitl_confidence` but never change the permission engine's
# behaviour. See the design doc for the promotion ladder and thresholds.


class HitlOutcome(enum.StrEnum):
    """Terminal outcomes for a HITL decision.

    Order matters for the Beta posterior update:
        approved_clean      → α += 1.0  (full trust signal)
        approved_modified   → α += 0.3, β += 0.7  (partial rejection)
        rejected            → β += 1.0
        timeout             → β += 0.5  (silence ≠ approval)
        downstream_reverted → β += 2.0  (loud negative; demotes buckets)
    """

    APPROVED_CLEAN = "approved_clean"
    APPROVED_MODIFIED = "approved_modified"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    DOWNSTREAM_REVERTED = "downstream_reverted"


class HitlConfidenceTier(enum.StrEnum):
    """Promotion ladder. Sprint 1 only ever assigns ASK."""

    ASK = "ask"
    ASK_QUIET = "ask_quiet"
    ALLOW_SHADOW = "allow_shadow"
    ALLOW = "allow"


class HitlDecision(Base):
    """Append-only event log for every HITL decision.

    Primary source of truth — `hitl_confidence` is derived from this
    table and can always be rebuilt. Rows are never updated or deleted;
    downstream signals (revert / complaint) appear as new rows that
    reference the original via ``parent_decision_id``.
    """

    __tablename__ = "hitl_decisions"
    __table_args__ = (
        Index("ix_hitl_decisions_bucket_decided", "bucket_key", "decided_at"),
        Index("ix_hitl_decisions_agent_cat", "agent_id", "action_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Pre-computed sha256 of agent_id:action_category:org_id:context_signature.
    # Used as the join key to `hitl_confidence`.
    bucket_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_category: Mapped[str] = mapped_column(String(50), nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    context_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    context_signature_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    approver_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[HitlOutcome] = mapped_column(Enum(HitlOutcome), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Hashes — never the raw payload, so the audit trail is PII-free even
    # when rebuilt or replicated. Investigators follow the hash back to
    # the primary request store if they need the text.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diff_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Reference to the original decision when this row is a downstream
    # signal (revert / complaint). Null for the primary approve/deny row.
    parent_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hitl_decisions.id"), nullable=True
    )

    # Free-form annotation by the approver (optional). Capped at 500 chars.
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class HitlConfidence(Base):
    """Rolling per-bucket confidence state.

    Incrementally updated on every write to `hitl_decisions`. The Beta
    distribution shape (α, β) is the canonical posterior; `confidence`
    is the mean (α / (α+β)) cached for fast dashboard reads. Tier stays
    ``ASK`` throughout Sprint 1 — promotion logic lands in Sprint 2.
    """

    __tablename__ = "hitl_confidence"
    __table_args__ = (Index("ix_hitl_confidence_agent_cat", "agent_id", "action_category"),)

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_category: Mapped[str] = mapped_column(String(50), nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    context_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    context_signature_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    n_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_approved_clean: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_approved_modified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_reverted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Beta posterior — starts at (1.0, 1.0) for an uninformative prior.
    beta_alpha: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    beta_beta: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Cached mean = alpha / (alpha + beta). Recomputed on every update.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    tier: Mapped[HitlConfidenceTier] = mapped_column(
        Enum(HitlConfidenceTier),
        nullable=False,
        default=HitlConfidenceTier.ASK,
    )
    last_promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When a revert/complaint fires we set `locked_until` and refuse to
    # promote past the current tier until the lock clears. Sprint 1 never
    # writes this field — kept on the model so Sprint 2 can use it.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class TenantIdentity(Base):
    """Central cross-service ID map for a single tenant.

    Every onboarded MADFAM tenant has identities across Janua, Dhanam,
    PhyneCRM, Karafiel, Resend, Cloudflare, and Selva Office. When any
    one drifts, data orphans. This table is the canonical mapping so
    reconciliation + offboarding can enumerate every place a tenant
    exists in O(1). Canonical id is the Janua org_id.
    """

    __tablename__ = "tenant_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(String(512), nullable=False)
    primary_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    janua_org_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dhanam_space_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    phynecrm_tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    karafiel_org_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    resend_domain_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    cloudflare_zone_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    selva_office_seat_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    r2_bucket_names: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# A2A external callers (migration 0029)
# ---------------------------------------------------------------------------


class ExternalA2ACaller(Base):
    """First-class tenant model for inbound A2A protocol peers.

    Today the A2A bridge in ``main.py`` funnels every peer through the
    synthetic ``org_id="a2a-external"`` org. That synthetic org has
    no quota, no consent ledger entry, no per-caller billing
    attribution, and no revocation primitive. See
    ``docs/rfcs/0018-a2a-external-tenant-model.md`` for the full
    problem statement and migration path.

    This model is the schema scaffold for Phase A. The bridge in
    ``main.py`` is **not** migrated to use it yet — that lands in
    a follow-up PR (Phase C in the RFC) gated by the
    ``A2A_PER_CALLER_TENANT`` env flag.

    Identity: ``agent_card_url`` is the natural key (UNIQUE). The
    derived org_id is ``a2a:<sha256(agent_card_url)[:16]>`` —
    deterministic, namespaced, doesn't leak the URL into every
    ``swarm_tasks.org_id`` cell.

    Auth: ``public_key`` holds a PEM-encoded key for verifying the
    peer's per-request signed JWT (RFC §5 Option B). NULL until the
    peer registers a key during the DNS-verified registration step.

    Quota: ``daily_task_limit`` is a per-caller cap that overrides
    the tier default in ``billing_tiers.TIER_DAILY_TASK_LIMIT`` when
    set. The tier slug ``"external_a2a"`` will be added to that
    dict in the cutover PR.

    Revocation: setting ``status='revoked'`` is the single-caller
    kill switch. Suspended (temporary) vs revoked (permanent) is a
    soft distinction — both block dispatch.
    """

    __tablename__ = "external_a2a_callers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_card_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, unique=True, index=True
    )
    # PEM-encoded; TEXT (unbounded) so future key rotation to a
    # longer algorithm doesn't require an ALTER COLUMN.
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # CHECK constraint at the DB level (see migration 0029) pins
    # values to {'active', 'suspended', 'revoked'}. The app layer
    # also validates but defence-in-depth.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )
    subscription_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="external_a2a"
    )
    daily_task_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The MADFAM user_sub who approved this caller during registration.
    # NULL for the legacy/seed row inserted by ops.
    owner_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
