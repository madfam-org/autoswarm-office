"""Built-in tools for AutoSwarm agents."""

from __future__ import annotations

from ..base import BaseTool

# Wave 4 additions
from ..execute_code import ExecuteCodeTool
from ..extra_tools import DelegateTaskTool, ReadCredentialFileTool, WebExtractTool
from ..extra_tools import WebSearchTool as WebSearchToolV2
from ..media_tools import GenerateImageTool, TextToSpeechTool
from ..process_registry import (
    KillBackgroundProcessTool,
    ListBackgroundProcessesTool,
    StartBackgroundProcessTool,
)
from .a2a_tool import CallExternalAgentTool
from .accounting import (
    BankReconciliationTool,
    DeclarationPrepTool,
    ISRCalculatorTool,
    IVACalculatorTool,
    PaymentSummaryTool,
)
from .argocd import get_argocd_tools
from .artifact import ListArtifactsTool, RetrieveArtifactTool, SaveArtifactTool
from .backup_ops import get_backup_tools
from .belvo_spei import get_belvo_spei_tools
from .billing_tools import CreateCheckoutLinkTool, GetRevenueMetricsTool
from .calendar_tools import (
    CreateCalendarEventTool,
    ListCalendarEventsTool,
    MexicanBusinessCalendarTool,
)
from .cloudflare import get_cloudflare_tools
from .cloudflare_r2 import get_r2_tools
from .cloudflare_saas import get_cloudflare_saas_tools
from .cloudflare_tunnel import get_cloudflare_tunnel_tools
from .code import BashExecTool, PythonExecTool
from .communication import CreateReportTool, SendNotificationTool
from .crm_tools import CreateActivityTool, CreateLeadTool, UpdateLeadStatusTool
from .data import CsvReadTool, DataTransformTool, JsonParseTool
from .database_tools import DatabaseSchemaTool, SQLQueryTool, SQLWriteTool
from .db_lifecycle import get_db_lifecycle_tools
from .deploy import DeployStatusTool, DeployTool
from .deploy_preflight import DeployPreflightTool
from .dev_quality import LintAndTypeCheckTool, TestCoverageForDiffTool
from .dhanam_provisioning import get_dhanam_provisioning_tools
from .discord import get_discord_tools
from .dns import get_dns_tools
from .document_tools import GenerateChartTool, GeneratePDFTool, MarkdownToHTMLTool, ParsePDFTool
from .email_tools import ReadEmailTool, SendEmailTool
from .enclii_infra import (
    EncliiExecTool,
    EncliiHealthTool,
    EncliiLogsTool,
    EncliiRestartTool,
    EncliiScaleTool,
    EncliiSecretsTool,
)
from .environment import EnvInfoTool, PackageInstallTool
from .erp import CONTPAQiExportTool, GenericERPExportTool
from .factory_manifest import get_factory_manifest_tools
from .files import FileDeleteTool, FileListTool, FileReadTool, FileSearchTool, FileWriteTool
from .git import GitBranchTool, GitCommitTool, GitCreatePRTool, GitDiffTool, GitPushTool
from .github_admin import (
    GithubAdminAuditTeamMembershipTool,
    GithubAdminCreateTeamTool,
    GithubAdminSetBranchProtectionTool,
    GithubAdminSetTeamMembershipTool,
)
from .grafana import get_grafana_tools
from .hitl_introspection import get_hitl_introspection_tools
from .http_tools import GraphQLQueryTool, HTTPRequestTool, WebhookSendTool
from .image_analysis import ImageAnalysisTool
from .intelligence import (
    DOFMonitorTool,
    ExchangeRateTool,
    InflationTool,
    SATMonitorTool,
    SIEMComplianceTool,
    TIIETool,
    UMATrackerTool,
)
from .janua_admin import get_janua_admin_tools
from .k8s_configmap import (
    DeleteConfigMapKeyTool,
    ListConfigMapsTool,
    ReadConfigMapTool,
    SetConfigMapValueTool,
)
from .k8s_diagnostics import get_k8s_diagnostic_tools
from .k8s_secret import KubernetesSecretWriteTool
from .karafiel import (
    BlacklistCheckTool,
    CFDIGenerateTool,
    CFDIStampTool,
    CFDIStatusTool,
    ComplementoPagoTool,
    ConstanciaFiscalTool,
    NOM035ReportTool,
    NOM035SurveyTool,
    RFCValidationTool,
)
from .karafiel_provisioning import get_karafiel_provisioning_tools
from .kustomize import get_kustomize_tools
from .legal import (
    ComplianceCheckTool,
    ContractGenerateTool,
    LawSearchTool,
    REPSECheckTool,
)
from .loki import get_loki_tools
from .marketing_tools import SendMarketingEmailTool
from .mastodon_tools import MastodonPostTool
from .meeting_scheduler import get_meeting_scheduler_tools
from .meta_harness import get_meta_harness_tools
from .npm_registry import get_npm_registry_tools
from .operations import CarrierTrackingTool, InventoryCheckTool, PedimentoLookupTool
from .phygital_tools import (
    CreateWorkOrderTool,
    GenerateParametricModelTool,
    GenerateQuoteTool,
    RunDFMAnalysisTool,
)
from .phynecrm_provisioning import get_phynecrm_provisioning_tools
from .pricing_intel import (
    CatalogLoadTool,
    CatalogPromoStackTool,
    CatalogTierGapTool,
    CompetitorPriceLookupTool,
)
from .privacy import DataDeletionTool, PIIClassificationTool, PrivacyNoticeGeneratorTool
from .product_catalog import ProductCatalogTool
from .prometheus import get_prometheus_tools
from .reddit_tools import RedditPostTool
from .resend_domain import get_resend_domain_tools
from .selva_office_provisioning import get_selva_office_provisioning_tools
from .sentry import get_sentry_tools
from .skill_performance import get_skill_performance_tools
from .slack import SlackMessageTool
from .stripe_connect import get_stripe_connect_tools
from .stt import SpeechToTextTool
from .telegram import get_telegram_tools
from .tenant_identity import get_tenant_identity_tools
from .tool_catalog import get_tool_catalog_tools
from .twilio_sms import get_twilio_sms_tools
from .vault import get_vault_tools
from .voice_call import get_voice_call_tools
from .web import WebFetchTool, WebScrapeTool, WebSearchTool
from .webhooks import (
    JanuaOidcRedirectRegisterTool,
    ResendWebhookCreateTool,
    StripeWebhookCreateTool,
    StripeWebhookDeleteTool,
    StripeWebhookListTool,
)
from .whatsapp import WhatsAppTemplateTool


def get_builtin_tools() -> list[BaseTool]:
    """Return all built-in tool instances."""
    return [
        # File ops
        FileReadTool(),
        FileWriteTool(),
        FileListTool(),
        FileDeleteTool(),
        FileSearchTool(),
        # Code (original)
        PythonExecTool(),
        BashExecTool(),
        # Wave 4: execute_code sandbox (approval-gated)
        ExecuteCodeTool(),
        # Wave 4: process registry
        StartBackgroundProcessTool(),
        ListBackgroundProcessesTool(),
        KillBackgroundProcessTool(),
        # Git
        GitCommitTool(),
        GitPushTool(),
        GitDiffTool(),
        GitBranchTool(),
        GitCreatePRTool(),
        # Dev quality (pre-PR audit building blocks)
        LintAndTypeCheckTool(),
        TestCoverageForDiffTool(),
        # Deployment pre-flight
        DeployPreflightTool(),
        # Web (original)
        WebSearchTool(),
        WebFetchTool(),
        WebScrapeTool(),
        # Wave 4: enhanced web tools
        WebSearchToolV2(),
        WebExtractTool(),
        # HTTP / GraphQL / Webhooks
        HTTPRequestTool(),
        GraphQLQueryTool(),
        WebhookSendTool(),
        # Data
        JsonParseTool(),
        CsvReadTool(),
        DataTransformTool(),
        # Communication
        SendNotificationTool(),
        CreateReportTool(),
        SlackMessageTool(),
        # Email
        SendEmailTool(),
        ReadEmailTool(),
        # Calendar
        CreateCalendarEventTool(),
        ListCalendarEventsTool(),
        MexicanBusinessCalendarTool(),
        # Database
        SQLQueryTool(),
        SQLWriteTool(),
        DatabaseSchemaTool(),
        # Documents
        GeneratePDFTool(),
        ParsePDFTool(),
        MarkdownToHTMLTool(),
        GenerateChartTool(),
        # Environment
        EnvInfoTool(),
        PackageInstallTool(),
        # Deployment
        DeployTool(),
        DeployStatusTool(),
        # Artifacts
        SaveArtifactTool(),
        RetrieveArtifactTool(),
        ListArtifactsTool(),
        # Image analysis (original) + Generation (Wave 4)
        ImageAnalysisTool(),
        GenerateImageTool(),
        TextToSpeechTool(),
        # Voice: speech-to-text
        SpeechToTextTool(),
        # Wave 4: delegation + credentials
        DelegateTaskTool(),
        ReadCredentialFileTool(),
        # A2A protocol
        CallExternalAgentTool(),
        # Karafiel compliance
        RFCValidationTool(),
        CFDIGenerateTool(),
        CFDIStampTool(),
        CFDIStatusTool(),
        BlacklistCheckTool(),
        ConstanciaFiscalTool(),
        ComplementoPagoTool(),
        NOM035SurveyTool(),
        NOM035ReportTool(),
        # LFPDPPP privacy
        PIIClassificationTool(),
        PrivacyNoticeGeneratorTool(),
        DataDeletionTool(),
        # WhatsApp Business API
        WhatsAppTemplateTool(),
        # Legal tools (Karafiel CLM + Tezca)
        ContractGenerateTool(),
        REPSECheckTool(),
        LawSearchTool(),
        ComplianceCheckTool(),
        # Accounting / Contabilidad
        ISRCalculatorTool(),
        IVACalculatorTool(),
        BankReconciliationTool(),
        DeclarationPrepTool(),
        PaymentSummaryTool(),
        # Market intelligence
        DOFMonitorTool(),
        ExchangeRateTool(),
        UMATrackerTool(),
        TIIETool(),
        InflationTool(),
        SATMonitorTool(),
        SIEMComplianceTool(),
        # Operations
        PedimentoLookupTool(),
        CarrierTrackingTool(),
        InventoryCheckTool(),
        # ERP export
        CONTPAQiExportTool(),
        GenericERPExportTool(),
        # Product catalog (MADFAM ecosystem)
        ProductCatalogTool(),
        # Pricing intelligence (per RFC 0004 — Selva-local catalog audits;
        # deep competitor + WTP analysis delegated to Tulana once v0.2 ships)
        CatalogLoadTool(),
        CatalogTierGapTool(),
        CatalogPromoStackTool(),
        CompetitorPriceLookupTool(),
        # Revenue tools (Ledger Node)
        CreateCheckoutLinkTool(),
        GetRevenueMetricsTool(),
        # CRM tools (Growth Node)
        CreateLeadTool(),
        UpdateLeadStatusTool(),
        CreateActivityTool(),
        # Marketing tools (Growth Node)
        SendMarketingEmailTool(),
        # Public-social outbound (Growth Node — TENANT audience). Reddit
        # MVP; X/LinkedIn parity tracked in ROADMAP. Mandatory disclosure
        # + 30-min rate-limit + HITL gate via reddit_promo_v1 playbook.
        RedditPostTool(),
        # Public-social outbound (Growth Node — TENANT audience). Mastodon
        # (fediverse) parity to Reddit. Per-persona access tokens, per-
        # instance policy ConfigMap, default visibility 'unlisted' to
        # avoid spamming public timelines, mandatory disclosure footer +
        # 30-min Redis per-instance rate-limit, HITL gate via
        # mastodon_promo_v1 playbook.
        MastodonPostTool(),
        # Phygital tools (Yantra4D Engine Node)
        GenerateParametricModelTool(),
        RunDFMAnalysisTool(),
        GenerateQuoteTool(),
        CreateWorkOrderTool(),
        # Infrastructure tools (Orchestration Node — SecOps gated)
        EncliiExecTool(),
        EncliiRestartTool(),
        EncliiScaleTool(),
        EncliiLogsTool(),
        EncliiHealthTool(),
        EncliiSecretsTool(),
        # DNS management tools (Porkbun — Orchestration Node)
        *get_dns_tools(),
        # Cloudflare zone + DNS + Page Rules management
        *get_cloudflare_tools(),
        # Cloudflare Zero Trust Tunnel (route public hostnames to cluster)
        *get_cloudflare_tunnel_tools(),
        # Cloudflare R2 object storage (bucket CRUD + CORS)
        *get_r2_tools(),
        # Cloudflare for SaaS custom-hostname onboarding (tenant bring-your-own-domain)
        *get_cloudflare_saas_tools(),
        # ArgoCD application management (sync, refresh, read status)
        *get_argocd_tools(),
        # Kubernetes read-side diagnostics (pods, events, replicasets, rollouts)
        *get_k8s_diagnostic_tools(),
        # Kustomize manifest editing (digest pinning for GitOps)
        *get_kustomize_tools(),
        # pgBackRest operations (info, backup, check)
        *get_backup_tools(),
        # Phase 2 — Tenant onboarding primitives: Janua OAuth-client admin
        # (create/update/rotate/delete) + org creation for fresh tenants.
        *get_janua_admin_tools(),
        # Phase 2 — Tenant onboarding primitives: Dhanam space + subscription
        # + credit-ledger management for billing bootstrap.
        *get_dhanam_provisioning_tools(),
        # Phase 2 — Tenant onboarding primitives: PhyneCRM tenant_config +
        # pipeline bootstrap + config read (voice_mode / onboarding state).
        *get_phynecrm_provisioning_tools(),
        # Phase 2 — Tenant onboarding primitives: Karafiel org + SAT cert +
        # PAC register + invoice-serie setup (Mexican fiscal compliance).
        # SAT cert upload is explicitly HITL-gated (legal-entity signing key).
        *get_karafiel_provisioning_tools(),
        # Phase 2 — Tenant onboarding primitives: Resend domain add/verify/
        # list/delete (bring-your-own-domain email sending).
        *get_resend_domain_tools(),
        # Phase 2 — Tenant onboarding primitives: central tenant_identities
        # record (canonical_id ↔ per-service IDs) + resolve + drift check.
        *get_tenant_identity_tools(),
        # Phase 2 — Tenant billing: Stripe Connect Express onboarding
        # (tenant-side payment collection). Platform creates the account,
        # tenant completes KYC on Stripe's hosted form.
        *get_stripe_connect_tools(),
        # Phase 2 — Tenant workspace: Selva Office seat provisioning
        # (create / assign-department / revoke). Binds Janua user subs
        # to tenant orgs inside the office UI.
        *get_selva_office_provisioning_tools(),
        # Phase 4 — Meta-improvement: Meta-Harness budget gate, Selva
        # routing preview, role-summary + convergence + round-submit +
        # tier-escalation. Wraps tezca/experiments/meta-harness.
        *get_meta_harness_tools(),
        # Phase 4 — Meta-improvement: HITL introspection. Agents query
        # their own Bayesian trust state before acting (bucket state,
        # effective tier, recent decisions, "why asked" narrative).
        *get_hitl_introspection_tools(),
        # Phase 4 — Meta-improvement: tool-catalog self-introspection.
        # list_my_tools / search_tools_by_capability / describe_tool.
        *get_tool_catalog_tools(),
        # Phase 4 — Meta-improvement: factory-manifest publish + verify +
        # read for per-repo build-shape declarations.
        *get_factory_manifest_tools(),
        # Phase 4 — Meta-improvement: skill performance signal into the
        # ThompsonBandit + metric readback for the platform-evolution skill.
        *get_skill_performance_tools(),
        # Phase 5 — Observability: Prometheus instant/range queries,
        # Alertmanager active alerts + maintenance silences.
        *get_prometheus_tools(),
        # Phase 5 — Observability: Loki LogQL range queries + label listing
        # for incident-triage log correlation.
        *get_loki_tools(),
        # Phase 5 — Observability: Sentry issue list/get/update/events/
        # breadcrumbs for error-tracking + Seer-style RCA.
        *get_sentry_tools(),
        # Phase 5 — Observability: Grafana read-only dashboard list +
        # panel PNG export for incident + post-mortem reports.
        *get_grafana_tools(),
        # Phase 5 — Data lifecycle: Postgres dump-to-R2, restore-from-R2,
        # mask-and-copy (for staging refresh per PhyneCRM PP.5), and
        # per-table size reports.
        *get_db_lifecycle_tools(),
        # Phase 6 — Communications: Twilio SMS (send, template, status,
        # opt-out). Mexican CDI compliance — explicit consent required.
        *get_twilio_sms_tools(),
        # Phase 6 — Communications: outbound voice calls (Twilio Voice,
        # Vapi AI agent, and a hybrid call-and-transfer path). HITL-gated
        # per the voice_mode consent ledger.
        *get_voice_call_tools(),
        # Phase 6 — Communications: Telegram bot (send message, photo,
        # update webhook) for operator + ops-channel notifications.
        *get_telegram_tools(),
        # Phase 6 — Communications: Discord bot (channel message, DM,
        # webhook) for community + dev-channel notifications.
        *get_discord_tools(),
        # Phase 6 — Adjacent: meeting scheduler (Google Calendar +
        # Microsoft 365) with availability query + invite generation.
        *get_meeting_scheduler_tools(),
        # Phase 6 — Adjacent: Belvo SPEI bank transfers (Mexican SPEI
        # rails). HITL-gated for transfer creation; read-only for status.
        *get_belvo_spei_tools(),
        # NPM registry management (Verdaccio — token rotation + GitHub secrets)
        *get_npm_registry_tools(),
        # Vault — secure secret storage (Orchestration Node — HITL gated)
        *get_vault_tools(),
        # RFC 0005 Sprint 1a — Kubernetes Secret writer (HITL gated per env)
        KubernetesSecretWriteTool(),
        # RFC 0006 Sprint 1 — GitHub org/repo admin (team CRUD, membership
        # reconcile, branch protection, drift audit). HITL-gated per op.
        GithubAdminCreateTeamTool(),
        GithubAdminSetTeamMembershipTool(),
        GithubAdminSetBranchProtectionTool(),
        GithubAdminAuditTeamMembershipTool(),
        # RFC 0007 Sprint 1 — Kubernetes ConfigMap tools (feature flags,
        # non-secret config). dev=ALLOW / staging=ASK / prod=ASK;
        # FEATURE_*/ENABLE_*/*_ENABLED keys in prod escalate to ASK_DUAL.
        ReadConfigMapTool(),
        SetConfigMapValueTool(),
        DeleteConfigMapKeyTool(),
        ListConfigMapsTool(),
        # RFC 0008 Sprint 1 — provider webhook management
        # (signing secrets captured → RFC 0005 writer in one atomic flow)
        StripeWebhookCreateTool(),
        StripeWebhookListTool(),
        StripeWebhookDeleteTool(),
        ResendWebhookCreateTool(),
        JanuaOidcRedirectRegisterTool(),
    ]
