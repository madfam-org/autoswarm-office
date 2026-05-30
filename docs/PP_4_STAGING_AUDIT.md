# PP.4 — autoswarm-office staging audit vs RFC 0001

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


> Last Updated: 2026-04-17
> RFC: [internal-devops/rfcs/0001-dev-staging-prod-pipeline.md](https://github.com/madfam-org/internal-devops/blob/main/rfcs/0001-dev-staging-prod-pipeline.md)
> Reference impls:
> - Karafiel PP.1 — `karafiel/infra/k8s/overlays/staging/` + `karafiel/.github/workflows/staging-deploy-*.yml`
> - Dhanam PP.2b/PP.2c — `dhanam/infra/k8s/overlays/staging/` + `dhanam/.github/workflows/{deploy-staging,promote-to-prod,rollback-prod}.yml`
> Scope: audit **and** ship structural convergence in a single PR (PP.4). Prod path stays additive — legacy `deploy.yml` remains side-by-side for 14-day soak.

## TL;DR

autoswarm-office (rebranded to Selva, target apex `selva.town`) is the
most complex service in the ecosystem to converge: **6 deployments**
(nexus-api, office-ui, colyseus, admin, gateway, workers) and 3 HPAs
sitting on top of a single `autoswarm` namespace. The current state is
**direct-to-prod** with no staging tier whatsoever:

1. `infra/k8s/production/` is the canonical base and is the only
   environment-specific directory. There is no `overlays/` tree.
2. `deploy.yml` builds 6 images on every push to `main`, patches prod
   digests into `infra/k8s/production/kustomization.yaml`, and ArgoCD
   reconciles prod directly. No pre-prod stop.
3. Images ARE already digest-pinned in prod (kustomize `edit set image
   ...@sha256:...` in the workflow) — this is the one RFC 0001 row
   already satisfied. Promotion, soak, and rollback workflows are all
   absent.
4. No staging namespace, no staging ingress, no staging secrets, no
   staging ArgoCD Application, no staging smoke.
5. The legacy `deploy-enclii.yml` referenced in task context does NOT
   exist in this repo — Enclii lifecycle notification is a subjob of
   `deploy.yml` (`notify-enclii`). Nothing to decommission yet.

Compliance estimate **before** PP.4: **~15%** (1 aligned: digest pinning
in prod; 2 partially aligned: multi-image build + concurrency group).
Compliance estimate **after** PP.4: **~85%** (staging overlay, promote,
rollback, smoke, ArgoCD staging manifest, `.enclii.yml` Pattern B all
shipped; remaining 15% is operator actions + deferred nightly masked DB
restore).

## Current state

- `infra/k8s/production/` holds the canonical base — 6 Deployments +
  3 HPAs + PDBs + ServiceMonitors + KEDA ScaledObject + backup CronJob +
  RFC 0005 secret-writer SA/Role/RoleBinding.
- Namespace: `autoswarm` (per `kustomization.yaml`).
- Images (in GHCR) are still `ghcr.io/madfam-org/autoswarm-*` except
  `selva-workers`. This PR does NOT rename registry paths per
  constraint; the kustomization overlay references the existing paths.
- `.github/workflows/deploy.yml` is the single deploy path: detect
  changes → build matrix of 6 → commit digests to prod kustomization →
  notify Enclii. No staging fork.
- `.enclii.yml` (actually `enclii.yaml`) declares 6 Enclii Services with
  `autoDeploy: true` on `main`. No `promotion:` key.
- `infra/argocd/application.yaml` watches `infra/k8s/production` →
  `autoswarm` namespace with `automated: { prune, selfHeal }`. No
  staging Application.

## Gap vs RFC 0001

1. **No base/overlay split.** `production/` is canonical, no
   `overlays/{staging,production}/` layout. Per RFC 0001 Phase 1 we keep
   `production/` as the canonical base and add `overlays/staging/`
   (and optionally `overlays/production/` as a symmetric peer that
   promote-to-prod writes to). A future PR does the full
   `production/` → `base/` rename.
2. **No staging namespace.** RFC 0001 expects `<service>-staging`.
   For autoswarm-office the ecosystem convention (matches Karafiel's
   `karafiel-staging`, Dhanam's `dhanam-staging`) is
   **`autoswarm-staging`** — not `selva-staging`, because the K8s
   namespace follows the repo name to avoid breaking the RFC 0005
   secret-writer RBAC references already scoped to `autoswarm`.
3. **No staging image digests pinned separately from prod.** Prod is
   the only digest pin target today. Staging needs its own 6-digest
   block that CI updates on every main merge.
4. **No staging-side env overrides.** `ENVIRONMENT=production` is
   hardcoded in every Deployment spec. Staging needs to override to
   `ENVIRONMENT=staging`, set `SENTRY_ENVIRONMENT=staging`, turn
   `AUTO_DISPATCH_ENABLED=false` on gateway (autonomous loop must NOT
   fire in staging — it would spam real customer emails via Resend),
   and flip any `FEATURE_*` that could cause real-world side effects
   (voice mode email, Reddit bot, Stripe relay).
5. **No staging secrets template.** Prod uses `autoswarm-secrets`,
   `autoswarm-llm-secrets`, `autoswarm-admin-auth`,
   `autoswarm-org-config` ConfigMap. Staging needs analogous
   `-staging` variants (except the ConfigMap, which the overlay
   inherits unchanged).
6. **HPAs not disabled for staging.** `hpa.yaml` declares 3 HPAs
   (nexus-api 1-6, office-ui 1-4, colyseus 1-3). Staging needs these
   pinned to maxReplicas=1 so deploys are visible and don't burn
   resources autoscaling against low staging traffic.
7. **No staging ArgoCD Application.** Prod has one; staging needs a
   peer that points at `infra/k8s/overlays/staging` on the same `main`
   branch.
8. **No promote workflow.** Prod digests are committed directly by
   `deploy.yml` on every merge. RFC 0001 Pattern B (manual gate) is
   required for autoswarm-office because the workers run agent code
   that touches prod customer data via SendEmail, SendMarketingEmail,
   database writes, and Stripe/Resend/GitHub API calls. Mistakes
   here would email real customers or push real git branches.
9. **No rollback workflow.** No single-command rollback exists;
   operators would have to revert the digest commit manually.
10. **No staging smoke.** `deploy.yml` only checks build success — no
    HTTP health check against the staging (or any) URL post-deploy.
11. **No `promotion:` key in `.enclii.yml`.** Needs explicit
    `pattern: manual` declaration with soak + smoke requirements.
12. **No staging DNS.** `api.selva.town`, `selva.town`,
    `admin.selva.town`, `ws.selva.town`, `gw.selva.town` are prod
    hosts. Staging needs `staging-*.selva.town` (or
    `staging.selva.town` + path-based routing; hyphenated pattern
    matches ecosystem convention per `domain_conventions` memory).
    **Operator action** — Cloudflare DNS + tunnel route changes are
    out-of-band for this PR.
13. **No staging Janua OAuth client.** Janua's `autoswarm-office`
    client is prod-only. Staging needs a distinct client with
    redirect URIs for `staging-admin.selva.town` and
    `staging.selva.town`. **Operator action** — registered via
    Janua's `POST /api/v1/oauth/clients/register` using
    `scripts/bootstrap-ecosystem.sh` (not present yet; tracked as
    post-PR work).
14. **No staging PhyndCRM endpoint.** Gateway + workers wire to
    `phynd-crm-web.phynd-crm.svc.cluster.local` (prod cluster-internal).
    For staging we either (a) point at the same prod PhyndCRM with
    `AUTO_DISPATCH_ENABLED=false` so nothing actually dispatches, or
    (b) stand up a staging PhyndCRM peer. PP.4 ships option (a) — HITL
    gate is closed so no side effects occur. Option (b) is a
    separate cross-repo RFC.
15. **No nightly prod → staging DB refresh.** RFC 0001 open question
    (masking tool TBD). Deferred to PP.6 per task constraint.

## Compliance estimate

| Area | RFC 0001 expects | Before PP.4 | After PP.4 |
| ---- | ---------------- | ----------- | ---------- |
| Base/overlay layout | `base/` + `overlays/{staging,production}/` | production/ canonical, no overlays (0%) | production/ canonical + overlays/staging + symmetric overlays/production (95%) |
| Digest pinning (prod) | `sha256:...` | Aligned (100%) | Aligned (100%) |
| Digest pinning (staging) | `sha256:...` per image | N/A (0%) | 6 digests, CI-patched per main merge (100%) |
| All 6 services in staging | api + ui + colyseus + admin + gateway + workers | N/A (0%) | Aligned (100%) |
| HPAs disabled in staging | maxReplicas=1 | N/A (0%) | Aligned (100%) |
| Staging namespace | `<service>-staging` | N/A (0%) | `autoswarm-staging` (100%) |
| Staging secrets template | Separate `-staging` secrets | N/A (0%) | Template shipped, operator provisions (80%; operator action pending) |
| Staging ingress/DNS | `staging-*.<domain>` | N/A (0%) | env + Cloudflare config template shipped; operator creates DNS (60%) |
| Staging smoke | 6×20s retry on /health | None (0%) | Shipped for api + office-ui + admin + gateway + colyseus (100%) |
| Promote workflow | `workflow_dispatch`, Pattern B | None (0%) | Shipped, manual gate, soak check (100%) |
| Rollback workflow | `workflow_dispatch`, RTO <5min | None (0%) | Shipped (100%) |
| `.enclii.yml` promotion key | `pattern: manual` | None (0%) | Shipped (100%) |
| ArgoCD staging Application | `autoswarm-office-staging` App | None (0%) | Manifest shipped, operator registers (80%) |
| Nightly masked DB refresh | RFC 0001 open question | None (0%) | Deferred to PP.6 (0%) |

**Overall**: ~15% → ~85%. Remaining 15% is operator action (register
Janua staging OAuth client, provision staging Secrets, create
Cloudflare DNS/tunnel routes, register staging ArgoCD Application) plus
deferred PP.6 (masked DB restore).

## Recommended ordering of fixes

PP.4 (this PR) ships items 1–11 and 15 in the table above. Post-merge
operator actions, in order:

1. **Provision staging Secrets** (K8s):
   ```bash
   kubectl create namespace autoswarm-staging
   kubectl create secret generic autoswarm-staging-secrets -n autoswarm-staging \
     --from-literal=database-url='postgres://...autoswarm-staging...' \
     --from-literal=redis-url='redis://...autoswarm-staging...' \
     --from-literal=secret-key='<rand-64>' \
     --from-literal=RESEND_API_KEY='<staging-resend-key>' \
     --from-literal=WORKER_API_TOKEN='<rand-64>' \
     --from-literal=colyseus-secret='<rand-32>' \
     --from-literal=PHYND_CRM_TOKEN='<staging-phynd-token>' \
     --from-literal=ENCLII_API_TOKEN='<staging-enclii-token>'
   kubectl create secret generic autoswarm-staging-llm-secrets -n autoswarm-staging \
     --from-literal=ANTHROPIC_API_KEY='<staging-anthropic-key>' \
     --from-literal=DEEPINFRA_API_KEY='<staging-deepinfra-key>' \
     --from-literal=WORKER_API_TOKEN='<rand-64>'
   kubectl create secret generic autoswarm-staging-admin-auth -n autoswarm-staging \
     --from-literal=NEXT_PUBLIC_JANUA_PUBLISHABLE_KEY='<staging-janua-client-id>' \
     --from-literal=NEXT_PUBLIC_JANUA_ISSUER_URL='https://auth.selva.town' \
     --from-literal=JANUA_SECRET_KEY='<staging-janua-client-secret>'
   ```
   Template at `infra/k8s/overlays/staging/staging-secrets-template.yaml`.
2. **Register Janua staging OAuth client** (out-of-band — Janua
   `POST /api/v1/oauth/clients/register` with redirect URIs
   `https://staging-admin.selva.town/api/auth/callback` and
   `https://staging.selva.town/auth/callback`).
3. **Apply Cloudflare DNS + tunnel routes** — records are codified in
   `infra/cloudflare/dns-records.yaml` + `tunnel-routes.yaml`. Apply with
   `./scripts/bootstrap-staging.sh` (or `python3 scripts/apply-cloudflare-infra.py`).
   Requires `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`.
4. **Register ArgoCD staging Application**:
   ```bash
   kubectl apply -f infra/argocd/staging.yaml
   argocd app sync autoswarm-office-staging
   ```
5. **First staging deploy**: push any commit to `main`; observe
   `staging-deploy.yml` patch all 6 digests and `staging-smoke.yml`
   (subjob of that workflow) hit every health endpoint.
6. **14-day soak**: both `deploy.yml` (legacy direct-to-prod) AND
   `staging-deploy.yml` + `promote-to-prod.yml` (new path) run in
   parallel. Legacy stays; once 14 days of staging-then-promote
   pass cleanly, a follow-up PR decommissions `deploy.yml`'s
   `commit-digests` stage and leaves only the staging build.
7. **PP.5** (separate PR): promote-to-prod writes to the new
   `overlays/production/kustomization.yaml` instead of
   `production/kustomization.yaml`, and the prod ArgoCD Application
   switches its `path:` from `infra/k8s/production` to
   `infra/k8s/overlays/production`. This is the "production cutover"
   step and is NOT in scope here.
8. **PP.6** (separate PR): nightly masked DB restore once RFC 0001
   picks a masking tool.

## Cross-references

- RFC 0001 — [internal-devops/rfcs/0001-dev-staging-prod-pipeline.md](https://github.com/madfam-org/internal-devops/blob/main/rfcs/0001-dev-staging-prod-pipeline.md)
- Runbook — `internal-devops/runbooks/staging-bootstrap.md`
- Karafiel PP.1 — `karafiel/infra/k8s/overlays/staging/`
- Dhanam PP.2b/2c — `dhanam/infra/k8s/overlays/staging/` +
  `dhanam/.github/workflows/{deploy-staging,promote-to-prod,rollback-prod}.yml`
- This PR — `feat/pp4-autoswarm-staging-convergence`
- Follow-up PRs — PP.5 (prod ArgoCD cutover), PP.6 (masked DB restore),
  PP.7 (decommission legacy `deploy.yml` direct-to-prod)
