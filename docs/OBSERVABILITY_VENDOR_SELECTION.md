# Observability Vendor Selection — OTel + Error Tracking

> Status: **decision document — vendor choice pending operator review**
> Owner: ops / platform
> Last Updated: 2026-05-03
> Related: ROADMAP.md Phase 1 ("OTel exporter actually wired" + "Sentry DSN per
> service"), [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md)
> (depends on the log backend chosen here)

## TL;DR (recommendations)

| Need | Recommendation | Fallback | Monthly cost at current scale |
|------|----------------|----------|------------------------------|
| OTel traces backend | **Grafana Cloud (Free → Pro)** | Honeycomb Free | **$0** (free tier covers our pre-launch volume); ~$50-90/mo within ~6 months |
| Error tracking | **Sentry Team plan** (already wired) | Self-hosted GlitchTip | **$26/mo** (Team, 50k errors/mo) |
| Alert routing | **Slack** (incoming webhook → Grafana Cloud Alerting + Sentry Alerts) | PagerDuty Free (Pro $21/user/mo) | $0 |
| Log backend (for `audience_shadow_block` queries) | **Grafana Cloud Logs (Loki)** — bundled in the Free tier | Self-hosted Loki | $0 free → ~$30/mo at next tier |

**Total realistic budget pre-launch: $26-30/mo. Soft ceiling at ~$120/mo for
the first 6 months post-launch.** Both budget points sit comfortably under the
$50-200/mo envelope the task brief assumed.

Single-vendor rationale: Grafana Cloud bundles **traces (Tempo) + logs (Loki) +
metrics (Mimir, OTel-native) + alerting + dashboards** under one free tier and
one bill. We already emit Prometheus metrics on every service's `/metrics`
endpoint — Grafana Cloud Mimir scrapes those for free. One vendor, one
dashboard, one auth context for ops.

Sentry stays separate because (a) it is already wired in
`packages/observability/src/selva_observability/sentry.py` and
`packages/config/sentry.ts`, (b) Grafana Cloud's error tracking is primitive
compared to Sentry's release-tracking + source-map upload, and (c) the cost is
a rounding error.

## Section 1 — Constraints

### 1.1 Mexican data residency (LFPDPPP)

Selva is incorporated as **Innovaciones MADFAM SAS de CV** and operates under
Mexican LFPDPPP 2025 amendments. The voice-mode + consent ledger system
(v2.2.0) already enforces lawful basis for outbound communication, but
observability data — request IDs, JWT subjects, error stack traces, log
payloads — also carries personal data classified as such by LFPDPPP.

**Decision rule used here**: pick a vendor that hosts in Mexico OR offers a
US/EU region with a published Data Processing Agreement (DPA) AND does not
egress to other regions for warm storage. Most observability SaaS only offer
US (Virginia/Oregon) or EU (Frankfurt/Ireland). None offer Mexico City. This
is acceptable because:

1. The data stays inside the OECD adequacy bloc (US has no formal adequacy with
   Mexico but LFPDPPP allows transfer with explicit DPA + safeguards).
2. We can use the EU region to reduce regulatory ambiguity (Mexico recognises
   GDPR as equivalent for international transfer).
3. Per `Settings._validate_config`, we already redact secrets before logging.
   Add a structlog filter to scrub `email`, `phone`, `rfc` fields before
   `configure_logging()` exports — handled in the wiring plan, Section 4.

### 1.2 Pricing tier we can sustain pre-revenue

Brief spec: $50-200/mo total observability budget. Our concrete numbers from
the codebase:

- **Services emitting telemetry**: 6 (nexus-api, office-ui, admin, colyseus,
  gateway, workers) — see ROADMAP.md "Built-in tools / Workflow graphs" table.
- **Trace volume estimate (pre-launch)**: ~10k spans/day. After launch with
  100 concurrent SwarmTasks (Phase 2 load test target), ~1M spans/day.
- **Log volume estimate (pre-launch)**: ~50 MB/day structured JSON. After
  launch: ~5 GB/day.
- **Error volume estimate**: low single digits per day pre-launch; <500/mo
  post-launch given current code stability (CI passes 794 test files).
- **Metrics volume**: every service exports Prometheus on `/metrics`. ~200
  series per service × 6 services = ~1.2k active series.

These numbers fit Grafana Cloud's Free tier (50 GB logs, 50 GB traces, 10k
metric series, 14-day retention). They also fit Honeycomb's Free tier (20M
events/mo). They will NOT fit Datadog's free tier (100 hosts × 15-day metric
retention, but per-host pricing kicks in at $15/host/mo immediately).

### 1.3 Existing stack

```
Python services  (nexus-api, gateway, workers)
  ├─ structlog            → JSON to stdout
  ├─ init_sentry()        → already wired, DSN missing from .env.example
  ├─ init_tracing()       → no-op when OTEL_EXPORTER_OTLP_ENDPOINT unset
  └─ Prometheus /metrics  → already exposed

TypeScript services  (office-ui, admin, colyseus)
  ├─ pino                 → JSON to stdout
  ├─ initSentry()         → already wired in packages/config/sentry.ts
  └─ /metrics              → exposed by colyseus, gateway, workers (Phase 1)

Deploy
  ├─ ArgoCD               → reconciles infra/k8s/{overlays/staging,production}
  └─ Enclii               → orchestrates promote/rollback (Pattern B)
```

The OTel grpc exporter is the only Python dep we'd add
(`opentelemetry-exporter-otlp-proto-grpc`). It's listed as an optional extra in
`packages/observability/pyproject.toml` already (the `init_tracing` function
imports it lazily and degrades to a warning if missing).

### 1.4 Alert routing destinations

**Decision: Slack as primary; PagerDuty deferred until we have on-call
rotation.** Selva is pre-launch with no on-call rotation defined. Adding
PagerDuty would force a per-user license fee and a paging schedule that nobody
will respond to outside business hours.

When the on-call rotation is defined (post-launch, roughly Phase 3 timeline),
re-evaluate PagerDuty Free (5 users, no paging) vs Better Stack ($24/mo for
unlimited paging) vs Opsgenie Free.

Slack channels to wire (operator action, Section 4):

- `#alerts-prod-critical` — paging-equivalent, 5xx spikes, RLS violations,
  consent ledger invariant failures.
- `#alerts-prod-warning` — DLQ growth, LLM provider rate limits, JWKS fetch
  failures.
- `#errors-sentry` — every Sentry alert.
- `#observability-ops` — Grafana Cloud usage warnings, billing alerts.

## Section 2 — OTel Exporter Backend Candidates

For each candidate the matrix below scores on six axes against our concrete
constraints. Pricing is taken from the vendor's public pricing page as of
2026-05-03 — verify before signing.

### 2.1 Comparison matrix

| Vendor | Free tier (traces) | Paid entry tier | Hosted regions | OTel-native | Trace retention | Alerting | Vendor-lock risk |
|---|---|---|---|---|---|---|---|
| **Grafana Cloud** | 50 GB traces + 50 GB logs + 10k series + 14-day retention | Pro: $0 base + usage (~$8/50GB traces, ~$0.50/GB logs over free) | US (Virginia, Oregon), EU (Ireland, Frankfurt), AU, India | Yes (Tempo is OTel-native) | 14d free, 30d Pro, 13mo Enterprise | Native (Grafana Alerting) → Slack, PagerDuty, Webhook | Low (Tempo + Loki + Mimir are Apache-licensed; can self-host) |
| **Honeycomb** | 20M events/mo, 60-day retention | Pro: $130/mo for 100M events | US (Virginia), EU (Frankfurt) | Yes (founded the OTel spec) | 60d on every paid tier | Native + PagerDuty + Slack | Low (events stored in proprietary BubbleUp index but exportable) |
| **Datadog** | 14-day metric retention only; no trace free tier | $31/host/mo (APM) + $0.10/GB logs | US, EU, AP, gov | Yes (OTel ingest) but pushes proprietary agent | 15d default, 30d at extra cost | Native + everything | High (proprietary agent + monitor query language; lock-in by design) |
| **New Relic** | 100 GB ingest free + 1 user free | $0.30/GB above 100 GB | US, EU | Yes (OTel ingest) | 8d default, 30d at extra cost | Native + Slack/PagerDuty | Medium (NRQL is proprietary; data exportable via API) |
| **Jaeger (self-hosted)** | Free (you operate it) | N/A | Anywhere you deploy | Yes | You decide (storage cost on your side) | None (need Grafana on top) | None (Apache-licensed) |
| **AWS X-Ray** | 100k traces/mo free | $5/M traces | AWS regions only | Partial (OTel works via ADOT collector but X-Ray sampler is opinionated) | 30d | CloudWatch alarms → SNS | High if not already AWS-bound (we are not — we run on Enclii/k8s, not AWS) |
| **Axiom** | 0.5 TB/mo + 30-day retention | $25/mo for 1 TB | US, EU | Yes (events) | 30d default, configurable | Native + webhook | Low (event-store is open-format; data exportable as Parquet) |
| **ClickHouse + Grafana (self-host)** | Free (operator-time) | Hardware $30-60/mo (k8s pod + PVC) | Wherever your cluster runs | Via OTel collector → ClickHouse exporter | Years (cheap storage) | Grafana Alerting | None |

### 2.2 Eliminations

- **Datadog** — eliminated on cost. $31/host/mo × 6 services × 2 environments
  (staging + prod) = $372/mo just for APM, before logs or RUM. Three to seven
  times our budget.
- **AWS X-Ray** — eliminated because we are not AWS-resident. Selva runs on
  Enclii-managed k8s (per `infra/k8s/`). Adopting X-Ray would require running
  the ADOT collector and accepting the X-Ray sampling opinions, with no
  upside.
- **Jaeger self-hosted** — eliminated for now on operator-time grounds.
  Re-evaluate at the Phase 3 horizon (architectural changes) if Grafana
  Cloud's free tier outgrows.
- **ClickHouse + Grafana self-host** — same reasoning as Jaeger. Excellent
  long-term answer, wrong answer for "the next 6 months while we are
  pre-revenue."
- **New Relic** — eliminated on data-residency confidence. Their EU region is
  US-replicated for some pipelines per their public docs, which complicates
  the LFPDPPP DPA story. Honeycomb and Grafana Cloud have cleaner stories.

### 2.3 Final two: Grafana Cloud vs Honeycomb

| Axis | Grafana Cloud | Honeycomb |
|---|---|---|
| Free tier headroom for our scale | 50 GB traces + logs + metrics + 14d retention | 20M events/mo, 60d retention |
| Single-pane integration (logs + traces + metrics) | **Yes** — one UI, correlated TraceID across all three | Traces only; logs need a sidecar (you'd add Better Stack or similar) |
| Existing Prometheus `/metrics` endpoints | **Native scrape from Grafana Cloud Mimir** | Need to convert Prometheus → events ($) |
| OTel-native ingest | Yes (Tempo) | Yes (founded the OTel spec) |
| Engineer learning curve | LogQL + PromQL (we already write Prometheus queries) | Honeycomb query builder (BubbleUp is unique) |
| Mexican data residency story | EU region (Ireland or Frankfurt) — clean DPA | EU region (Frankfurt) — clean DPA |
| Alerting → Slack | Native, drag-and-drop | Native, integrates with PagerDuty/Slack |
| Lock-in risk | Low (Apache-licensed components, can self-host the same stack) | Low-medium (BubbleUp UI is unique but data is exportable) |
| Pricing forecast at 1M spans/day post-launch | ~$50-90/mo (overage at $0.50/GB logs, $8/50GB traces) | $130/mo Pro tier or stay free if under 20M events/mo |
| **Score** | **8/10** | 7/10 |

**Recommendation: Grafana Cloud (start on Free, expect to pay $50-90/mo
within 6 months post-launch).**

Rationale: the metric-traces-logs single-pane wins. We already export
Prometheus metrics; Grafana Cloud Mimir scrapes them for free. We need a log
backend anyway for the `audience_shadow_block` query (see
[docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md)) — Loki bundles in.
Honeycomb's BubbleUp is genuinely better at trace exploration but we don't yet
have the trace volume to make that ROI matter.

**Fallback if Grafana Cloud signup is blocked or hits a deal-breaker**:
Honeycomb Free. Same OTLP gRPC endpoint shape — flip
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`, no code
change needed. Lose the integrated logs+metrics story.

## Section 3 — Error Tracking Candidates

| Vendor | Free tier | Paid entry | Mexican data residency | Source maps | Already wired |
|---|---|---|---|---|---|
| **Sentry** (recommended) | 5k errors/mo | Team $26/mo (50k errors) | EU region available | Yes, native | **Yes** — `init_sentry()` Python + `initSentry()` TS already in repo |
| Rollbar | 5k events/mo | $21/mo (50k events) | US only | Yes | No |
| Bugsnag | 7.5k events/mo | $25/mo (200k events) | US, EU | Yes | No |
| GlitchTip (self-host) | Free | Hardware ~$15/mo | Wherever your cluster runs | Yes (Sentry-compatible) | Sentry SDK works against it |

### 3.1 Recommendation: Sentry Team

- **Already wired**: `packages/observability/src/selva_observability/sentry.py`
  + `packages/config/sentry.ts` are both in place; only DSNs are missing from
  `.env.example` (per ROADMAP.md Phase 1). Zero code change to enable.
- **EU region**: pick `https://o<orgid>.ingest.de.sentry.io/<projectid>` so
  data lands in Frankfurt. LFPDPPP DPA available on Sentry's legal page.
- **Source maps**: office-ui (Next.js) needs `@sentry/webpack-plugin` in CI
  for symbolicated stack traces. Adding the plugin is ~10 lines in
  `next.config.js` + 1 secret (`SENTRY_AUTH_TOKEN`).
- **Cost**: pre-launch we'll stay under 5k errors/mo (free). Post-launch the
  Team plan at $26/mo covers 50k errors with 90-day retention.

### 3.2 Fallback: GlitchTip self-hosted

If Sentry pricing scales badly (it does at >500k errors/mo, jumping to
Business at $80/mo), GlitchTip is **wire-compatible with the Sentry SDK** —
swap the DSN, no code change. Hardware cost ~$15/mo for a small Postgres + a
GlitchTip pod in our existing k8s cluster. Defer to Phase 3 unless Sentry
pricing surprises us.

### 3.3 Eliminations

- **Rollbar** — US-only data residency complicates the LFPDPPP story. No
  meaningful feature edge over Sentry.
- **Bugsnag** — fine product, but switching requires re-wiring all six
  services. Sentry is already wired.

## Section 4 — Wiring Plan

This section is what an ops engineer executes after the user approves the
recommendation. Keep checkpoints at each step — rollback is just "remove the
env var and re-deploy."

### 4.1 Account creation (operator action — ~30 min total)

#### Grafana Cloud
1. Sign up at <https://grafana.com/auth/sign-up/create-user> — pick the EU
   region during stack creation (Ireland or Frankfurt, both LFPDPPP-friendly).
2. Stack name: `selva-prod` (one stack covers all 6 services). Create a
   second stack `selva-staging` for the staging cluster (free tier covers
   both).
3. Create an API token under "Access Policies":
   - Name: `selva-otel-write`
   - Scopes: `metrics:write`, `traces:write`, `logs:write`
   - Save the token — this becomes `OTEL_EXPORTER_OTLP_HEADERS`.
4. Note the OTLP endpoint URL from the stack's "OpenTelemetry" page —
   format: `https://otlp-gateway-<region>.grafana.net/otlp` (HTTPS, gRPC).
5. Note the Loki and Mimir endpoints from the same page (for log shipping
   via Promtail and metric remote-write later).

#### Sentry
1. Sign up at <https://sentry.io/signup/> — pick Frankfurt region
   (`de.sentry.io`).
2. Create org `madfam-selva`.
3. Create six projects, one per service:
   - `selva-nexus-api` (platform: python-fastapi)
   - `selva-workers` (platform: python)
   - `selva-gateway` (platform: node)
   - `selva-colyseus` (platform: node)
   - `selva-office-ui` (platform: javascript-nextjs)
   - `selva-admin` (platform: javascript-nextjs)
4. Each project gives you a DSN — collect all six.
5. Generate one auth token under Settings → Auth Tokens with `project:write`
   for source-map uploads (`SENTRY_AUTH_TOKEN`).
6. Configure alerts → integrations → Slack → connect to
   `#errors-sentry`.

#### Slack
1. Create channels `#alerts-prod-critical`, `#alerts-prod-warning`,
   `#errors-sentry`, `#observability-ops`.
2. Generate incoming webhook URLs for the first two from
   <https://api.slack.com/messaging/webhooks> — these become Grafana Cloud
   Alerting contact points.

### 4.2 Secrets to provision

Add these to the staging and prod secret stores (per
`infra/k8s/overlays/staging/staging-secrets-template.yaml` pattern):

```bash
# Grafana Cloud OTel
OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-prod-eu-west-2.grafana.net/otlp"
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64(instance_id:token)>"
OTEL_EXPORTER_OTLP_PROTOCOL="grpc"

# Sentry — one DSN per service. Set the right one per Deployment.
SENTRY_DSN_NEXUS_API="https://<key>@o<orgid>.ingest.de.sentry.io/<projectid>"
SENTRY_DSN_WORKERS="..."
SENTRY_DSN_GATEWAY="..."
SENTRY_DSN_COLYSEUS="..."
SENTRY_DSN_OFFICE_UI="..."   # exposed to client as NEXT_PUBLIC_SENTRY_DSN
SENTRY_DSN_ADMIN="..."

# Sentry — release tagging + source maps
GIT_SHA="<deploy commit sha>"   # already wired in deploy.yml
SENTRY_AUTH_TOKEN="..."          # CI-only; needed for source-map upload

# Loki — log shipping (set on Promtail or Grafana Agent in the cluster)
LOKI_PUSH_URL="https://logs-prod-012.grafana.net/loki/api/v1/push"
LOKI_USERNAME="<instance id>"
LOKI_PASSWORD="<api token>"
```

The convention "one DSN env var per service" is needed because each
deployment passes its own DSN to `init_sentry(service_name, dsn=...)`. The
nexus-api and workers Settings classes don't need new fields — they read from
env directly via `os.environ.get("SENTRY_DSN")`. Wire each Deployment's
`SENTRY_DSN` env var to the correct per-service value via Kustomize.

### 4.3 Code changes

Today's wiring (per
`packages/observability/src/selva_observability/{tracing,sentry}.py` and
`packages/config/sentry.ts`) already reads from the env vars listed above and
no-ops when unset. So the rollout is:

1. **No code change** for backend selection — the env var IS the selection.
2. **One per-service env wire** in each Deployment:
   ```yaml
   # infra/k8s/overlays/production/<service>-patch.yaml
   - name: SENTRY_DSN
     valueFrom:
       secretKeyRef:
         name: selva-prod-secrets
         key: SENTRY_DSN_NEXUS_API
   - name: OTEL_EXPORTER_OTLP_ENDPOINT
     valueFrom:
       secretKeyRef:
         name: selva-prod-secrets
         key: OTEL_EXPORTER_OTLP_ENDPOINT
   - name: OTEL_EXPORTER_OTLP_HEADERS
     valueFrom:
       secretKeyRef:
         name: selva-prod-secrets
         key: OTEL_EXPORTER_OTLP_HEADERS
   ```
3. **Add the OTel gRPC exporter dependency** to `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   tracing = [
     "opentelemetry-api>=1.27",
     "opentelemetry-sdk>=1.27",
     "opentelemetry-exporter-otlp-proto-grpc>=1.27",
   ]
   ```
   Then install with `uv sync --extra tracing`. The `init_tracing()` function
   already lazy-imports — no further code change needed.
4. **Source-map upload for office-ui** (Next.js) — add to
   `apps/office-ui/next.config.js`:
   ```js
   const { withSentryConfig } = require('@sentry/nextjs');
   module.exports = withSentryConfig(
     existingConfig,
     { org: 'madfam-selva', project: 'selva-office-ui', silent: true },
     { hideSourceMaps: true, transpileClientSDK: true },
   );
   ```
   Then add `SENTRY_AUTH_TOKEN` to the GitHub Actions deploy secret store.
5. **Promtail / Grafana Agent for log shipping** — install in the k8s cluster
   to scrape stdout from all 6 Deployments and push to Loki. Standard helm
   chart: `grafana/grafana-agent` with the `LOKI_*` secrets above.
6. **Prometheus remote-write to Mimir** — point the existing Prometheus
   instance (or install Grafana Agent in metrics mode) at the Grafana Cloud
   Mimir endpoint with the same credentials.

### 4.4 Confirm traces flow

Single-trace smoke test (do this on staging first):

1. After step 4.3 deploy, hit a known traced endpoint:
   ```bash
   curl -H "Authorization: Bearer <staging-token>" \
        https://staging-api.selva.town/api/v1/health
   ```
2. Open Grafana Cloud → stack `selva-staging` → Explore → Tempo data source.
3. Search by service name `nexus-api`, time range "Last 5 minutes".
4. You should see at least one trace. Click it; you should see spans for
   FastAPI request → DB query → response.
5. **Sentry smoke test**: in nexus-api logs trigger a known error path:
   ```bash
   curl -H "Authorization: Bearer invalid-token" \
        https://staging-api.selva.town/api/v1/swarms/dispatch
   ```
   Check Sentry → `selva-nexus-api` → Issues. The 401 should NOT be there
   (it's expected behavior, not an error). Now intentionally break a known
   path (e.g. point `DATABASE_URL` to an invalid host in a one-off pod) and
   confirm the connection error lands in Sentry within 60s.

### 4.5 Update CLAUDE.md

After both are flowing in production, update the "Architecture Notes →
Observability" section in CLAUDE.md to remove "no-op when unset" qualifiers
and document the live endpoints. Update `.env.example` with the new env vars
(values empty, comments pointing here).

## Section 5 — Cost Estimate

### 5.1 Realistic monthly bill at current scale (pre-launch, low traffic)

| Line item | Vendor | Cost |
|---|---|---|
| OTel traces (Tempo) | Grafana Cloud Free | $0 |
| Logs (Loki) | Grafana Cloud Free | $0 |
| Metrics (Mimir) | Grafana Cloud Free | $0 |
| Error tracking | Sentry Team | $26/mo |
| Slack alert routing | Free tier | $0 |
| **Total pre-launch** | | **$26/mo** |

### 5.2 Forecast at "Phase 2 load test target" (100 concurrent SwarmTasks, ~1M spans/day, ~5GB logs/day)

| Line item | Free tier headroom | Estimated overage cost |
|---|---|---|
| Traces — 1M spans × 30 days × ~1 KB/span = ~30 GB/mo | 50 GB free | $0 |
| Logs — 5 GB × 30 = 150 GB/mo | 50 GB free | (150-50) × $0.50 = ~$50/mo |
| Metrics — 1.2k active series | 10k free | $0 |
| Errors — assume 10k/mo | 5k free, then Team plan covers | $26/mo (already paying) |
| **Total post-launch** | | **~$76/mo** |

### 5.3 Scale point at which we'd outgrow

- **Logs**: at ~150 GB/mo overage we'll be paying ~$50/mo for Loki. If we
  reach ~500 GB/mo logs, that's $225/mo for Loki alone — the point to
  re-evaluate **self-hosted Loki on the existing k8s cluster** (operator-time
  + $30/mo storage).
- **Traces**: 50 GB free covers 1.6k spans/sec sustained. We'd need to be
  running the platform 24/7 at the Phase 2 load test sustained rate to get
  there. Long timeline.
- **Sentry**: Team plan covers 50k errors/mo. Above that we jump to Business
  ($80/mo, 250k errors). Above 500k errors the GlitchTip self-host story
  becomes attractive.

### 5.4 Open questions for operator decision

1. **Region**: EU (Frankfurt/Ireland) is the safe default for LFPDPPP DPA.
   Confirm this is acceptable to legal — alternative is US East with the
   2024 Mexico-US sectoral data agreement.
2. **Trace sampling**: default is 10% (`traces_sample_rate=0.1` in
   `init_sentry`, no sampling configured for OTel). For pre-launch, 100%
   sampling is fine. After launch, drop OTel sampling to 10% via the
   collector to control trace volume — but defer that decision to the Phase
   2 load test data.
3. **PII scrubbing**: structlog already filters secrets (`Settings`
   validators). Confirm whether `email`, `phone_e164`, `rfc` (Mexican tax
   ID) need additional scrubbing before logs leave the cluster — Sentry has
   a built-in `before_send` filter; Loki needs a Promtail pipeline stage.
   Recommend adding both even if pre-launch volume makes the issue moot.
4. **On-call rotation**: Slack-only is fine while pre-launch. When we
   establish on-call, re-evaluate PagerDuty / Better Stack / Opsgenie.

## References

- Grafana Cloud pricing: <https://grafana.com/pricing/>
- Honeycomb pricing: <https://www.honeycomb.io/pricing>
- Sentry pricing: <https://sentry.io/pricing/>
- Sentry EU region docs: <https://docs.sentry.io/concepts/key-terms/data-storage-location/>
- LFPDPPP 2025 amendment overview (Diario Oficial): <https://dof.gob.mx/>
- OpenTelemetry OTLP spec: <https://opentelemetry.io/docs/specs/otlp/>
- AUDIENCE_FILTER_ENABLED rollout (depends on the log backend chosen here):
  [docs/AUDIENCE_FILTER_ROLLOUT.md](AUDIENCE_FILTER_ROLLOUT.md)
