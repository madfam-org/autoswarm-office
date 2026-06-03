# Nine-State Executive Harness — Node Architecture

This document maps the Swarm Governing Manifesto's 9 nodes to concrete
services, agents, tools, graphs, and external systems in the MADFAM ecosystem.

## Node-to-Service Mapping

### 1. Executive Node (Chief of Staff)
**Purpose:** Apex allocator. Directs API budgets, enforces circuit breakers, commands swarm focus.

| Component | Implementation |
|-----------|---------------|
| Agent | Centinela (L9) |
| Department | Executive Brain Trust |
| Service | Selva (Selva Office) |
| Key Tools | PlaybookGuard, FinancialCircuitBreaker, ProductCatalogTool |
| Responsibilities | Playbook management, budget allocation, wave coordination, autonomous dispatch gating |
| API Routes | `GET/POST /api/v1/playbooks` (CRUD), `GET /api/v1/playbooks/match` (event matching), `GET /api/v1/metrics/roi` (revenue attribution) |

### 2. Build Node
**Purpose:** Creates code, structures logic, deploys digital assets.

| Component | Implementation |
|-----------|---------------|
| Agents | Codice (L9, Lead Dev), Telar (L7, Product Owner) |
| Department | Build & Run Engine |
| Services | Selva workers, Enclii (deployment) |
| Graphs | `coding` (plan->implement->test->review->push), `deployment` (validate->deploy->monitor) |
| Key Tools | BashExecTool, GitCommitTool, GitPushTool, DeployTool |

### 3. Growth Node (The Catalyst)
**Purpose:** Content blitzes, cultural attention capture, CRM automation, lead funneling.

| Component | Implementation |
|-----------|---------------|
| Agents | Heraldo (L8, Growth Director), Nexo (L8, CRM Lead) |
| Department | Growth & Market Syndicate |
| Services | PhyndCRM, Resend (email), madfam-site (CMS) |
| Graphs | `crm` (qualify->outreach->follow-up), `research` (discover->analyze->report) |
| Key Tools | SendMarketingEmailTool, CreateLeadTool, UpdateLeadStatusTool, CreateContactTool, CreateActivityTool |
| Playbooks | Lead Response, Content Publish, Trial Retention |
| Webhooks | `POST /api/v1/gateway/phynd-crm` (CRM event auto-dispatch via playbook matching) |

### 4. Identity Node (Sovereign Border)
**Purpose:** Zero-trust access, ecosystem citizenship. If not verified through Janua, it does not exist.

| Component | Implementation |
|-----------|---------------|
| Agents | None (service-level node) |
| Service | Janua (self-hosted OAuth2/OIDC) |
| Key Features | 13+ OAuth clients, OIDC provider, SCIM provisioning, MFA, WebAuthn, zero-touch `/register` |
| Dogfooding | All MADFAM services authenticate through Janua. No external auth providers. |

### 5. Legal Node (Obsidian Mirror)
**Purpose:** Parses, maps, and weaponizes legal code into programmable automated advantages.

| Component | Implementation |
|-----------|---------------|
| Agents | None (service-level node) |
| Services | Tezca (30K+ Mexican laws), Karafiel (SAT compliance) |
| Key Tools | LawSearchTool, ComplianceCheckTool, CFDIGenerateTool, CFDIStampTool, RFCValidationTool |
| Capabilities | Article 69-B blacklist, DIOT auto-generation, DOF monitoring, obligation scanner |

### 6. Ledger Node
**Purpose:** Autonomous accounting, fiscal tracking, resource routing optimization.

| Component | Implementation |
|-----------|---------------|
| Agent | Aureo (L7, Finance Controller) |
| Department | Physical-Digital Bridge |
| Service | Dhanam (billing engine) |
| Key Tools | CreateCheckoutLinkTool, GetRevenueMetricsTool, ISRCalculatorTool, IVACalculatorTool |
| Data | MRR/ARR dashboard, credit metering, overage invoicing, product catalog |
| Playbooks | Trial Retention |
| API Routes | `GET /api/v1/metrics/roi` (per-agent cost/revenue, revenue attribution pending Phase 4) |

### 7. Archive Node
**Purpose:** Open-source compliance, documentation, knowledge base management.

| Component | Implementation |
|-----------|---------------|
| Agents | None (infrastructure-level node) |
| Services | Documentation infrastructure, solarpunk-foundry |
| Key Features | AGPLv3 compliance, CLAUDE.md per repo, llms.txt, internal-devops runbooks |
| Principle | All source code open under AGPL. Proprietary value in orchestration, not code. |

### 8. Orchestration Node (Biological Siphoning)
**Purpose:** Human-swarm interface. Absorbs external energy into trained Biological Orchestrators.

| Component | Implementation |
|-----------|---------------|
| Agents | Forjador (L10, CTO), Vigia (L8, SRE) |
| Department | Build & Run Engine |
| Services | Selva (agent orchestration), Enclii (infrastructure) |
| Key Tools | EncliiExecTool, EncliiRestartTool, EncliiScaleTool, EncliiLogsTool, EncliiHealthTool, EncliiSecretsTool |
| Key Features | Skill marketplace, iterative refinement, A2A protocol, WebRTC proximity video |
| Principle | Map human biological intuition to synthetic speed. Train orchestrators, not operators. |

### 9. Phygital Node (Yantra4D Engine)
**Purpose:** Multi-material simulation, 4D hyperobject computation, micro-factory governance.

| Component | Implementation |
|-----------|---------------|
| Agent | Espectro (L7, MES Supervisor) |
| Department | Physical-Digital Bridge |
| Services | Yantra4D (parametric design), Pravara-MES (manufacturing execution), Cotiza (quoting), Sim4D (CAD) |
| Key Tools | GenerateParametricModelTool, RunDFMAnalysisTool, CreateWorkOrderTool, GenerateQuoteTool |
| Graph | `phygital` (validate->generate->dfm->simulate->quote->HITL->fabricate) |
| Principle | Axiom III: no extrusion until the digital twin has succeeded. |

---

## Agent-to-Node Assignment

| Agent | Level | Node | Department |
|-------|-------|------|------------|
| Oraculo | L10 | Executive | Executive Brain Trust |
| Centinela | L9 | Executive | Executive Brain Trust |
| Forjador | L10 | Orchestration | Executive Brain Trust |
| Telar | L7 | Build | Build & Run Engine |
| Codice | L9 | Build | Build & Run Engine |
| Vigia | L8 | Orchestration | Build & Run Engine |
| Heraldo | L8 | Growth | Growth & Market Syndicate |
| Nexo | L8 | Growth | Growth & Market Syndicate |
| Aureo | L7 | Ledger | Physical-Digital Bridge |
| Espectro | L7 | Phygital | Physical-Digital Bridge |

---

## Autonomous Operation Boundaries

### Playbook-Gated Actions (no HITL required)
Actions within a playbook's `allowed_actions` execute autonomously if:
1. The triggering event matches the playbook's `trigger_event`
2. The action is in the playbook's `allowed_actions` list
3. The token budget has not been exceeded
4. The financial cap ($ exposure) has not been exceeded
5. The default permission matrix does not DENY the action category

### Playbook CRUD API
- `GET /api/v1/playbooks` -- list all playbooks (6 seeded defaults)
- `POST /api/v1/playbooks` -- create a new playbook
- `GET /api/v1/playbooks/match?event=<key>` -- find matching enabled playbook for a trigger event
- `GET /api/v1/playbooks/{id}` -- get playbook by ID
- `PATCH /api/v1/playbooks/{id}` -- update playbook fields
- `DELETE /api/v1/playbooks/{id}` -- delete a playbook
- Source: `apps/nexus-api/nexus_api/routers/playbooks.py`

### Seeded Playbooks
| Name | Trigger Event | Allowed Actions | Token Budget | Financial Cap |
|------|--------------|-----------------|-------------|---------------|
| Lead Response | `crm:hot_lead` | api_call, email_send, crm_update, marketing_send | 50 | $0 |
| Content Publish | `content:scheduled_post` | api_call | 30 | $0 |
| Trial Retention | `billing:trial_expiring` | api_call, email_send, marketing_send | 40 | $0 |
| Auto-Restart on Pod Crash | `infra:pod_crash` | infra_monitor, deploy | 20 | $0 |
| Automated Health Analysis | `infra:health_degraded` | infra_monitor, api_call | 10 | $0 |
| Database Migration Runner | `infra:migration_pending` | infrastructure_exec, database_migration, infra_monitor | 30 | $0 (HITL) |

### CRM Webhook Auto-Dispatch
- `POST /api/v1/gateway/phynd-crm` -- receives PhyndCRM webhook events
- HMAC-SHA256 signature verification via `X-PhyndCRM-Signature` header
- Maps CRM events to internal event keys: `lead.hot` -> `crm:hot_lead`, `lead.created` -> `crm:lead_created`, `activity.overdue` -> `crm:support_ticket`, `opportunity.created` -> `crm:opportunity_created`
- Automatically dispatches SwarmTasks when a matching enabled playbook exists
- Source: `apps/nexus-api/nexus_api/routers/crm_webhooks.py`

### HITL-Required Actions (always require approval)
- `file_write` -- code modifications
- `git_push` -- publishing changes
- `deploy` -- production deployments
- Physical fabrication (phygital graph has mandatory HITL gate before `create_work_order`)

### Circuit Breakers
- **Token budget:** Per-playbook execution cap (default 50 tokens)
- **Financial cap:** Per-playbook $ exposure cap (default $0 for most playbooks)
- **Daily org limit:** $50/day total autonomous financial exposure (Redis-backed, `packages/orchestrator/selva_orchestrator/circuit_breaker.py`)
- **Task retry:** 3 attempts with exponential backoff, then DLQ

### Permission Engine Extensions
- `PlaybookGuard` in `packages/permissions/selva_permissions/playbook.py` -- evaluates action permissions within playbook boundaries (action category, token budget, financial cap)
- `PermissionEngine.evaluate()` accepts optional `playbook_guard` parameter -- playbooks can relax ASK to ALLOW but NEVER override DENY
- New `ActionCategory` values: `BILLING_WRITE`, `MARKETING_SEND`, `INFRASTRUCTURE_EXEC`, `SECRET_MANAGEMENT`, `INFRASTRUCTURE_MONITOR`, `DATABASE_MIGRATION`

### ROI Metrics
- `GET /api/v1/metrics/roi?period=30d` -- per-agent cost vs revenue dashboard
- Currently returns cost-side data (tasks completed, tokens used, estimated cost)
- Revenue attribution (Phase 4 RevenueAttribution model) pending
- Source: `apps/nexus-api/nexus_api/routers/metrics.py`
