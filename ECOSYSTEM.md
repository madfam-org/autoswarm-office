# selva-office — Ecosystem Context

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


> **Selva — gamified multi-agent business orchestration + OpenAI-compatible LLM inference routing.**

This file is self-contained: a Claude session on a fresh machine can operate
this service by reading only this one document. No external links are
load-bearing — the MADFAM ecosystem map and the full enclii CLI reference are
embedded below.

---

## 1. What this repo is

Selva Office (repo `selva-office`) is MADFAM's AI inference + agent orchestration platform. Two roles: (1) **inference proxy** — OpenAI-compatible `/v1` endpoint (`nexus-api`) that every ecosystem service routes its LLM calls through; (2) **agent platform** — LangGraph workers + Colyseus real-time state + 2D Phaser office UI for drafting agents, assigning them to departments, and approving their actions via a gamepad. Target domain: `selva.town`.

**Pillar**: Intelligence / Agents + LLM routing
**Type**: platform
**Status**: production (staging tier live 2026-05-30; north-star program in [docs/AUTONOMOUS_OPERATIONS_PROGRAM.md](docs/AUTONOMOUS_OPERATIONS_PROGRAM.md); commercial GA no-go gates in [docs/COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md](docs/COMMERCIAL_GA_REMEDIATION_PLAN_2026-06-04.md))

### Deployed services

> See [docs/PORTS.md](docs/PORTS.md) for canonical port assignments.

| Service | Public domain | Container port |
|---|---|---|
| `selva-nexus-api` | api.selva.town | 4300 |
| `selva-office-ui` | app.selva.town | 3000 |
| `selva-admin` | admin.selva.town | 3000 |
| `selva-colyseus` | ws.selva.town | 4303 |
| `selva-gateway` | gw.selva.town (health/metrics) | 4304 |
| `selva-workers` | (langgraph worker, internal) | 4305 |

**Kubernetes namespace**: `selva` (production) / `selva-staging` (staging) in source. Live cutover from the prior operational namespaces is sequenced through ArgoCD to avoid pruning healthy workloads.
**Cluster**: bare-metal k3s on Hetzner (see topology section below).

### Upstream dependencies (this repo consumes)

- LLM providers: openai, anthropic, deepinfra, groq, etc.
- postgres (agent state, tasks, approvals)
- redis (colyseus room state)
- janua (operator auth + M2M for downstream services)
- shared: @madfam/budget-gate, @madfam/revenue-loop-probe, factory-manifest

### Downstream consumers (this repo is consumed by)

- every ecosystem service doing LLM inference — routes through `/v1`
- phynd-crm (digital-project execution updates)
- symbiosis-hcm (human-AI dyad orchestration)
- proton-bridge-pipeline (email classification via M2M)

### Key environment variables

- `OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPINFRA_API_KEY — upstream providers`
- `DATABASE_URL — Postgres`
- `REDIS_URL — colyseus`
- `JANUA_JWKS_URI — auth`
- `ENCLII_API_URL — HITL budget gate callback`

---

## MADFAM Ecosystem Map

MADFAM runs ~40 services on sovereign bare-metal infrastructure. Everything
below is embedded here so this document stands alone.

### The platforms every repo should know about

| Platform | Repo | Role |
|---|---|---|
| **Enclii** | `madfam-org/enclii` | PaaS control plane — all deploys go through this |
| **Janua** | `madfam-org/janua` | OIDC/OAuth 2.0 provider — RS256 JWKS at `auth.madfam.io/.well-known/jwks.json` |
| **Dhanam** | `madfam-org/dhanam` | Billing + payment gateways (Stripe, Mercado Pago, SPEI, etc.) |
| **Selva** | `madfam-org/selva-office` | LLM inference routing + agent orchestration |
| **Karafiel** | `madfam-org/karafiel` | Operational compliance — CFDI, NOM-151, e.firma, SAT-adjacent. Owns legal-ops / contract templates |
| **Tezca** | `madfam-org/tezca` | Mexican law oracle (informational only — feeds Karafiel) |
| **Cotiza** | `madfam-org/digifab-quoting` | MADFAM's quoting engine (fabrication + services) |
| **Forgesight** | `madfam-org/forgesight` | Digital fabrication industry intelligence (pricing/vendor feed to Cotiza) |
| **Pravara MES** | `madfam-org/pravara-mes` | Fabrication-node routing and dispatch (physical jobs) |
| **PhyndCRM** | `madfam-org/phynd-crm` | Client-facing deliverables portal (single pane of glass per engagement) |
| **Fortuna** | `madfam-org/fortuna` | Problem intelligence / zeitgeist analysis |
| **Avala** | `madfam-org/avala` | Learning verification platform |

### Cross-repo conventions

- **Auth**: every authenticated service verifies Janua JWTs via JWKS at
  `https://auth.madfam.io/.well-known/jwks.json`. RS256 only — HS256 is
  fail-closed after the 2026-04-23 audit (H3/H4). `https://auth.madfam.io`
  is the single canonical Janua URL and OIDC issuer for **all** Selva
  surfaces (office-ui, admin, nexus-api) across prod and staging. Janua is
  single-issuer per deployment (`JANUA_CUSTOM_DOMAIN=auth.madfam.io`; its
  `/.well-known/openid-configuration` returns `issuer: https://auth.madfam.io`
  and is not Host-aware), so every `JANUA_ISSUER_URL` / `NEXT_PUBLIC_JANUA_URL`
  / `NEXT_PUBLIC_JANUA_ISSUER_URL` value MUST be `https://auth.madfam.io` for
  discovery + token `iss` validation to pass. Do NOT introduce a
  `auth.selva.town` alias — it has no DNS/tunnel and would break OIDC issuer
  matching even if it did.
- **Billing**: credit metering + entitlements flow through Dhanam. See
  `madfam-org/dhanam` for the meter/entitlement/invoice APIs.
- **Inference**: every LLM call should route through Selva
  (`selva-office`, served at `api.selva.town/v1`, OpenAI-compatible). Do not
  talk directly to OpenAI / Anthropic from service code.
- **CORS**: explicit allowlist per service. Wildcards are banned
  (audit 2026-04-23 H2/H5/H6).
- **Images**: `@sha256:`-pinned in every manifest. Kyverno fail-closes on
  `:latest` or mutable tags.
- **Onboarding**: `POST /v1/admin/onboard` on switchyard-api creates
  namespace, ArgoCD app, Cloudflare tunnel routes, Janua client, and
  NetworkPolicies in one shot. See `enclii/docs/guides/ONBOARDING_GUIDE.md`.

### Production topology

Bare-metal k3s (v1.33+) on Hetzner, 3 nodes:

- `foundry-cp` (Hetzner EX44, 14C/20T, 128 GB) — control-plane + primary workload
- `foundry-worker-01` (Hetzner AX41-NVMe, Ryzen 5 3600, 64 GB) — worker + Longhorn 2nd replica
- `foundry-builder-01` (Hetzner VPS, 2 vCPU, 4 GB, tainted `builder=true:NoSchedule`) — ARC runners only

**Ingress**: Cloudflare Tunnel → 2× cloudflared pods → K8s ClusterIP → container port.
Zero exposed node ports. TLS terminated at Cloudflare edge.

**Storage**: Longhorn CSI v1.7+ in 2-replica mode across dedicated nodes.
Object storage: Cloudflare R2 (zero egress).

**GitOps**: ArgoCD App-of-Apps (~28 apps across ~22 namespaces) with self-heal.
Push to `main` → CI builds → GHCR → `kustomize edit set image` commits digest →
ArgoCD syncs → Switchyard tracks lifecycle events.

**Operational access** (SSH, kubeconfigs, server IPs, cost ledger): private repo
`madfam-org/internal-devops`. Not in any public repo.

---

## Enclii CLI — DevOps Reference

**Strong preference: use `enclii` over `kubectl`** for all operational
tasks. The CLI routes through Switchyard API, which gives you audit
logging, lifecycle event tracking, and service-scoped context. Escape
to kubectl only for the gaps listed at the end of this section.

### Install

```bash
# macOS
brew install enclii/tap/enclii

# Linux
curl -sSL https://get.enclii.dev | bash

# From source (in the enclii repo)
make build-cli && ./bin/enclii --version
```

### Auth

```bash
enclii login                  # browser SSO (Janua)
enclii whoami                 # verify active session
enclii logout                 # clear local creds
```

Env vars: `ENCLII_API_URL` (default `https://api.enclii.dev`),
`ENCLII_TOKEN` (alternative to interactive login),
`ENCLII_PROJECT`, `ENCLII_ENV`.

### Day-to-day for selva-nexus-api

The commands below default to `selva-nexus-api` — the primary service name for
this repo as registered in Switchyard. For any other service in the
ecosystem, swap the name.

```bash
# Status + where the pods are running
enclii ps --wide
enclii ps selva-nexus-api --env production

# Logs (tail, filter, history)
enclii logs selva-nexus-api -f                          # live tail
enclii logs selva-nexus-api --since 1h --level error    # last hour, errors only
enclii logs selva-nexus-api --env staging -f

# Deploy (preview, staging, production)
enclii deploy --env preview                       # from current branch
enclii deploy --env staging
enclii deploy --env production --strategy canary --canary-percent 10

# Rollback
enclii rollback selva-nexus-api                         # previous release
enclii rollback selva-nexus-api --to-revision 5

# Releases + history
enclii releases selva-nexus-api                          # list builds
enclii releases selva-nexus-api --latest --output json

# Secrets (routed through Lockbox → Vault → ESO → K8s)
enclii secrets list selva-nexus-api
enclii secrets set MY_KEY=value --service selva-nexus-api --secret
enclii secrets rm MY_KEY --service selva-nexus-api

# Domains, tunnel routes, DNS
enclii domains list selva-nexus-api
enclii domains add selva-nexus-api my.example.com       # auto-provisions tunnel route + DNS

# Scheduled jobs (cron + one-off)
enclii jobs list
enclii jobs run <job-name>                         # trigger one-off

# Routing (ingress + TLS)
enclii junctions list selva-nexus-api

# Serverless (scale-to-zero functions)
enclii functions list

# Local dev environment
enclii local up         # spin up dependent services (postgres, redis, …)
enclii local logs
enclii local down
```

### Full onboarding (only used when adding a brand-new service)

```bash
# One-shot: namespace + ArgoCD app + tunnel routes + Janua client + netpol
enclii onboard --repo madfam-org/<name> --db-name <db> --secrets-file .env
```

### Enclii-first production operations

Enclii is the required control plane for routine production operations.
Use the web UI, API, or CLI before reaching for raw infrastructure tools:

- ArgoCD sync / diff / rollback — `enclii ops apps ...`
- Pod logs, diagnosis, and safe restarts — `enclii ops pods ...`
- Longhorn / PVC / PV inspection and repair planning — `enclii ops storage ...`
- Kyverno violations and time-bound waivers — `enclii ops policy ...`
- ExternalSecrets and Vault readiness — `enclii ops secrets ...`
- ARC runner inspection and drain workflows — `enclii ops runners ...`
- DNS, tunnels, SaaS hostnames, providers, and repo automation — `enclii providers ...`
- Service lifecycle, domains, secrets, jobs, and observability — `enclii deploy`, `enclii rollback`, `enclii logs`, `enclii observe`, `enclii domains`, `enclii secrets`, `enclii jobs`

### Break-glass-only access

Raw `kubectl`, `helm`, SSH, provider CLIs/APIs, `docker exec`, and direct
container access are allowed only for platform bootstrap or documented
break-glass emergencies when Enclii is unavailable or lacks an implemented
adapter. Record the actor, reason, target service/environment, commands
executed, result, and follow-up Enclii adapter gap or incident link.

### Cluster access

kubeconfig + SSH keys live in `madfam-org/internal-devops` (private repo)
for bootstrap and break-glass use only. Routine production operations must
go through Enclii web, API, or CLI.

### Exit codes (scripting against the CLI)

| Code | Meaning |
|---|---|
| 0  | success |
| 10 | validation error |
| 20 | build failed |
| 30 | deploy failed |
| 40 | timeout |
| 50 | auth error |

---

## Document provenance

Generated 2026-04-23 as part of the "each repo stands alone" docs sweep. If the
ecosystem map or CLI reference drifts from reality, update the generator at
`madfam-org/enclii/docs/templates/ECOSYSTEM.md.template` and re-render — don't
edit per-repo copies in isolation.
