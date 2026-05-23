"""Core types for the HITL permission system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class PermissionLevel(StrEnum):
    """Possible permission decisions for an action.

    ASK_DUAL is a strict super-set of ASK that additionally requires a
    second, distinct approver. Any policy pipeline that already special-
    cases ASK should treat ASK_DUAL identically for the *first* approval
    slot; the second-approver constraint is enforced by the approval
    queue consumer, not by this enum. See RFC 0005 and RFC 0006/0007
    which also re-use this primitive.
    """

    ALLOW = "allow"
    ASK = "ask"
    ASK_DUAL = "ask_dual"
    DENY = "deny"


class ActionCategory(StrEnum):
    """Categories of actions that agents can request."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    BASH_EXECUTE = "bash_execute"
    GIT_COMMIT = "git_commit"
    GIT_PUSH = "git_push"
    EMAIL_SEND = "email_send"
    CRM_UPDATE = "crm_update"
    DEPLOY = "deploy"
    API_CALL = "api_call"
    BILLING_WRITE = "billing_write"
    MARKETING_SEND = "marketing_send"
    # Outbound social-platform post (Reddit, X/Twitter, LinkedIn). Distinct
    # from MARKETING_SEND because (a) the audience is public, (b) the
    # platform's anti-spam rules apply (per-subreddit / per-account rate
    # limits, mandatory AI-agent disclosure), and (c) revoking is impossible
    # — a sent email can be unsent in spirit; a Reddit post is forever.
    # Always HITL-gated by default; per-org overrides via the playbook
    # system, never via the matrix.
    SOCIAL_POST = "social_post"
    INFRASTRUCTURE_EXEC = "infrastructure_exec"
    SECRET_MANAGEMENT = "secret_management"
    INFRASTRUCTURE_MONITOR = "infra_monitor"
    DATABASE_MIGRATION = "database_migration"
    # RFC 0005: k8s Secret write is a distinct risk class (values never
    # leave worker memory, but bad writes can break consumers instantly).
    K8S_SECRET_WRITE = "k8s_secret_write"
    # RFC 0006: GitHub org/repo admin (team CRUD, membership reconcile,
    # branch protection). Mutating operations are HITL-gated; read-only
    # audits default to ALLOW.
    GITHUB_ADMIN = "github_admin"
    # RFC 0007: k8s ConfigMap writes (feature flags, non-secret config).
    # dev=ALLOW / staging=ASK / prod=ASK. Feature-flag-shaped keys in
    # prod auto-escalate to ASK_DUAL at the tool layer.
    K8S_CONFIGMAP_WRITE = "k8s_configmap_write"
    # RFC 0008: provider webhook management (Stripe/Resend/Janua). Signing
    # secrets returned by the provider are captured in-memory and written
    # via K8S_SECRET_WRITE; a bad webhook destination could exfiltrate
    # payment/auth events so mutating ops are HITL-gated.
    WEBHOOK_MANAGEMENT = "webhook_management"
    PRICING_PROPOSAL = "pricing_proposal"


class PermissionResult(BaseModel):
    """Outcome of evaluating a permission request."""

    action_category: ActionCategory
    level: PermissionLevel
    requires_approval: bool
    reason: str
