# RFC 0020 — Per-tenant data residency for SAT-resident tenants

| Field | Value |
|---|---|
| Status | Draft |
| Author | Architect (Selva Office) |
| Created | 2026-05-03 |
| Supersedes | — |
| Related | RFC 0018 (A2A external-tenant model), RFC 0019 (cross-service CDC audit topic), RFC 0021 (multi-region failover, paired), migration 0028 (Phase 1.5 RLS strict mode), `apps/nexus-api/nexus_api/middleware/security.py` (`TenantRLSMiddleware`), `apps/nexus-api/nexus_api/billing_tiers.py`, `infra/k8s/production/backup-cronjob.yaml` |

## 1. Status quo and the regulatory ask

### 1.1 The single-region default

Selva runs one production Postgres (the `pgvector/pgvector:pg16`
StatefulSet behind the `selva` namespace). Every tenant — Mexican
SMEs using Karafiel for CFDI submission, US enterprise pilots, the
internal MADFAM org, future EU customers — shares the same database
host. The legal jurisdiction of every byte of customer data is
determined by where that one host sits.

This was acceptable while Selva's customer base was MADFAM-internal
and a handful of Mexican design partners on Tulana v0.1. It is no
longer acceptable as of the v2.2.x consent ledger work, which
deliberately codified outbound voice-mode under LFPDPPP, and as Selva
prepares to take SAT-resident production tenants whose CFDI
submissions land in Karafiel.

### 1.2 What LFPDPPP + SAT actually require

The Mexican Ley Federal de Protección de Datos Personales en Posesión
de los Particulares (LFPDPPP), as amended in 2025, plus SAT's
*Anexo 20 v4.0* technical resolutions for CFDI 4.0, between them
require:

1. **Datos sensibles** — CFDI invoices contain RFC (Mexican tax ID),
   facturado names + addresses, line-item descriptions that may
   contain trade-secret detail, and the digital signature of the
   issuing PAC. SAT's interpretation in administrative resolution
   2025-04 treats CFDI as `datos sensibles` requiring "permanencia
   territorial" — physically stored inside Mexican territory, on
   infrastructure subject to Mexican jurisdiction.
2. **Cross-border transfer notice** — even a transient pass-through to
   a US-region database for processing, then writeback to MX,
   constitutes an international transfer under LFPDPPP Art. 36, which
   requires explicit opt-in consent + the foreign jurisdiction's data
   protection adequacy notice. Selva's onboarding does not capture
   this consent today (the consent ledger only covers outbound
   communication voice-mode, not data-residency transfer).
3. **Audit trail residency** — the LFPDPPP regulator (INAI, soon to be
   reorganized under the 2025 transparency law) can request the audit
   trail of any access to a tenant's `datos personales`. That audit
   trail itself counts as `datos personales` and inherits the
   residency requirement.
4. **Backup residency** — backups of `datos sensibles` inherit the
   residency requirement. A US-region backup of an MX-region database
   violates the rule even if the live data is correctly placed.
5. **Log residency** — application logs that include RFC, invoice
   numbers, or facturado identifiers are themselves `datos personales`
   under the 2025 amendment that broadened the definition. Selva's
   structured logs (`packages/observability/`) are currently emitted
   to whatever Loki / cloud log store the cluster uses, with no
   region tagging.

What residency means in practice, decomposed across the four data
states:

| State | Today | Required for SAT tenants |
|---|---|---|
| At rest (DB rows) | Single region | MX region |
| In flight (worker → API, API → DB) | Cross-AZ within region | Stay in MX region; no cross-region replication for SAT tenants |
| In backups | Single region (same as DB) | MX region; backup encryption keys held in MX-jurisdiction KMS |
| In logs | Cluster log store, single region | MX region log store; PII redaction at producer side as defense in depth |

### 1.3 The ask

Make the single-region default a per-tenant choice. SAT-bound tenants
get an MX-region cluster; everyone else stays on the existing cluster
(initially US-region; future EU region as enterprise pilots demand).
The choice is declared at onboarding, persisted on `tenant_configs`,
and routed at runtime by the application layer.

The smell this RFC corrects: today, residency is determined by *where
we happened to put the cluster*, which is an operational accident
that has now become a legal liability.

## 2. Three patterns with explicit trade-offs

### 2.1 Pattern A — Tenant-scoped DB per region (cleanest isolation)

**Shape**: N independent Postgres clusters, one per region. Each
cluster has its own Alembic migration history (or shared schema +
N migration runs), its own backup pipeline, its own monitoring, its
own connection pool from each app pod.

**Pros**:
- Strongest data-residency story — a row physically cannot end up in
  the wrong region because the cross-region network path doesn't
  exist.
- Per-region performance isolation — a noisy MX tenant doesn't
  compete for IOPS with a US tenant.
- Per-region compliance posture — SAT can audit the MX cluster
  without touching any other region's data.
- Per-region backup encryption keys — `KMS_KEY_ID_MX` lives in a
  Mexican-jurisdiction KMS, never leaves.
- Failover scope is tighter — RFC 0021 failover is region-local by
  default.

**Cons**:
- Operational surface scales linearly with regions: every Alembic
  migration is now N migrations to run, each with its own rollout
  window and its own potential to drift. Today's single-cluster
  release is a `make db-migrate`; under Pattern A it becomes
  `for region in mx us eu; do REGION=$region make db-migrate-region;
  done`, with regional sign-off required before the next region
  proceeds.
- Cross-region operations (admin reap-stale, billing rollups, fleet
  stats) need explicit cross-region access — see §6.
- Connection pool count multiplies — each app pod holds a pool to
  every region it might serve. With pool-size 10 and 3 regions, a
  pod's idle connection budget triples.
- Backup pipeline is N pipelines — `infra/k8s/production/backup-cronjob.yaml`
  becomes a per-region template; each cronjob owns its own S3 bucket
  in the appropriate jurisdiction.
- Cost — every region has a baseline of cluster + read replica +
  backup storage + monitoring even when the region has 1 tenant.

**Verdict**: highest fidelity, highest operational cost. Right answer
for SAT-resident tenants because the regulatory ask is explicit and
non-negotiable. Wrong answer for a free-tier US tenant where the
cost-per-tenant blows the unit economics.

### 2.2 Pattern B — Postgres partitioning by `tenant_region` column

**Shape**: One Postgres cluster, table-level partitioning by a
`tenant_region` column that's set at row-insert time. Each partition
lives on a separate tablespace mapped to a region-specific filesystem
mount (or, in cloud Postgres, a separate region-tagged disk).
Cross-region writes are blocked at the DB layer via CHECK constraints.

**Pros**:
- Single Alembic migration history — one schema, one migration run,
  one place to read the truth.
- Single connection pool — apps don't need to know the region
  topology.
- Cross-tenant joins (admin / billing) work without cross-region
  network access — they're a single SQL statement.
- Cost is roughly flat — the partition for a tiny region adds storage
  but not compute.

**Cons**:
- The "data is physically in MX" story becomes "the tablespace mount
  for the MX partition is on a disk attached to MX-region compute" —
  which is technically true but harder to explain to a SAT auditor
  than "this is the MX cluster."
- Cross-AZ replication of the master inside the cloud provider may
  spread a write across multiple availability zones in a single
  region; that's typically fine for SAT (still in-country) but needs
  per-cloud verification.
- Cluster failure is a global failure — no per-region blast radius.
  The MX SAT tenants and the US tenants go down together if the
  cluster goes down.
- Backup is one backup, encrypted with one KMS key. To get
  per-region backup encryption you'd need to back up partitions
  separately, which is not a first-class Postgres operation and
  defeats most of Pattern B's simplicity.
- Logs and application memory still cross regions — when the API pod
  in US-region serves an MX tenant request, the MX row is in the US
  pod's RAM during the request, even if it never lands in a US
  tablespace. This is a transient cross-border transfer under
  strict LFPDPPP reading and would need explicit consent.

**Verdict**: clever, lower ops cost, weaker residency story. Acceptable
for soft data-residency requirements (e.g., enterprise customer
preference for "data in EU"); insufficient for a hard regulatory
requirement.

### 2.3 Pattern C — Gateway-routed regional shards (simplest, weakest)

**Shape**: N Postgres clusters as in Pattern A, but the routing
decision lives entirely in the application layer. No DB-level
constraint prevents a misrouted write from ending up in the wrong
cluster — we trust the app to compute the correct cluster from
`tenant_configs.data_residency_region` on every request.

**Pros**:
- Simplest to introduce — no DB migrations, no partitioning, no
  cross-cluster constraint logic. Just a routing helper in
  `database.py` and per-region env vars.
- Apps still see a clean "one DB per call" model — no partition
  awareness leaks into ORM code.
- Region-level failover stays local (no cross-cluster constraints
  to satisfy).

**Cons**:
- No DB-level enforcement of residency. A bug in
  `get_engine_for_tenant()` — say, a cache returning the wrong
  engine after a tenant moves regions — silently writes MX data into
  the US cluster. The first time you find out is during an INAI
  audit.
- Same operational surface as Pattern A (N clusters, N migrations, N
  backup pipelines), without the strongest-isolation benefit
  Pattern A provides.
- No defense in depth — the residency boundary is a single layer
  (application code), not multiple layers (app code + DB constraint
  + tablespace).

**Verdict**: looks like Pattern A, has Pattern A's costs, has Pattern
B's residency weakness. Worst of both worlds when applied to
SAT-bound tenants. **Acceptable** for non-regulated tenants where
residency is a preference, not a legal requirement, because the
operational simplicity (one routing helper, no DB-level check) is
worth the trade.

## 3. Selection — hybrid Pattern A + Pattern C

The recommendation is a hybrid:

- **SAT-bound tenants** (any tenant with `data_residency_region = "MX"`)
  → Pattern A. Their data lives in a dedicated MX-region cluster
  with per-region backups, per-region KMS, per-region log store.
- **All other tenants** (default `data_residency_region = "US"`,
  optional `"EU"`) → Pattern C. Application-layer routing chooses
  the right cluster from a small fixed set; DB-level residency is
  not enforced because no regulator requires it.

The single column that drives the dispatch:
`tenant_configs.data_residency_region`, an ENUM of `('MX','US','EU')`,
with the existing tenant base case defaulting to `'US'` to preserve
current behavior.

The hybrid honors the principle from CLAUDE.md's tool-audience model
(§"Tool + Skill Audience Split"): we apply the strongest enforcement
where the regulatory requirement is non-negotiable, and the
lightest-weight pattern where the requirement is preference-driven.

The selection is also a defense-in-depth play: even if Pattern C's
routing helper has a bug, the failure mode for a US tenant is
"data ended up in EU instead of US" — a privacy preference violation,
not a federal-criminal exposure. For an MX tenant on Pattern A, the
routing-helper bug results in `OperationalError: connection refused`
because the US engine doesn't have credentials for the MX network —
fail-closed.

## 4. Migration path

Phased rollout that keeps existing tenants untouched.

### Phase A — Schema scaffold

1. Add `tenant_configs.data_residency_region` ENUM column, default
   `'US'`, NOT NULL after backfill. Migration N (provisional 0029,
   coordinates with RFC 0018's migration 0029 — only one of them
   takes that slot; this RFC defers to whichever lands first).
2. Backfill existing rows with `'US'` (the current cluster's region —
   this is a fact about the existing deployment, not a recommendation
   for new tenants).
3. No behavior change. Routing helper not yet added.

### Phase B — Routing helper, single region (no-op for callers)

1. Add `get_engine_for_tenant(org_id) -> AsyncEngine` to
   `apps/nexus-api/nexus_api/database.py`. Initially, every region
   key resolves to the same single engine — the helper is in place
   but the topology is still single-region.
2. Migrate `Depends(get_db)` chain to read the engine via the helper
   instead of the module-level `engine` constant. This is a
   ~50-callsite refactor; can land as a single PR because the
   behavior is identical.
3. Worker side: the worker package gets the same helper. The
   `X-Selva-Tenant-Org` header (CLAUDE.md §"Worker → API auth") is
   already propagated on every worker → API call; the API just needs
   to use it to pick the engine.

### Phase C — Stand up MX-region cluster (zero tenants on it)

1. Provision a separate Postgres cluster in MX region (cloud-region
   tagged appropriately for the cloud provider — for AWS, a region
   like `mx-central-1`; for self-hosted, a Mexican datacenter
   provider like KIO or Neutral Networks).
2. Run all Alembic migrations against it from scratch.
3. Set up its own backup-cronjob (per-region template — see §5).
4. Set `DATABASE_URL_MX` env var in the prod ConfigMap; routing
   helper now resolves `region='MX'` to the new cluster.
5. Verify with a synthetic test tenant whose `org_id` is set to
   `region='MX'` — round-trip a write through the API and confirm it
   lands in the MX cluster, not the US cluster.

### Phase D — Onboarding prompts for new tenants

1. `/onboarding` flow gains a `data_residency_region` step BEFORE
   the voice-mode step (residency is more fundamental — voice-mode
   is meaningless if the data is in the wrong jurisdiction).
2. UI copy explains the choice in plain Spanish + English: "Su
   facturación CFDI requiere residencia en México (LFPDPPP)" / "We
   recommend MX region for any business issuing CFDIs."
3. The choice is persisted to `tenant_configs.data_residency_region`
   and is **immutable** post-onboarding. To move regions, a tenant
   files a support ticket → ops runs the migration tool (see Phase E).

### Phase E — Migration tool for existing SAT-bound tenants

1. CLI: `python scripts/migrate-tenant-region.py --org-id=<uuid>
   --target-region=MX --confirm`. Two-phase:
   1. Dump the tenant's rows from the source cluster (using RLS-
      bypass `app_admin` role).
   2. Restore into the target cluster.
   3. Update `tenant_configs.data_residency_region` to the target
      value in the source cluster (so any stale read finds the new
      pointer).
   4. Update again in the target cluster (the source-of-truth row).
2. The migration is offline for the affected tenant — their
   `tenant_configs.status` flips to `migrating` for the duration,
   and the API returns 503 for that tenant. Expected duration: ~5
   min for a typical small tenant; longer for tenants with large
   `swarm_tasks` history.
3. Post-migration verification: a sample of rows is checksummed in
   both clusters; the source-cluster rows are then DROPped (not
   soft-deleted — LFPDPPP would treat soft-deleted rows as still
   resident in the wrong region).

### Phase F — Deprecation of the all-tenants-US assumption

1. Remove the default `'US'` for new rows after 90 days; require
   onboarding to explicitly set the region (no default).
2. Remove the legacy `engine` module-level constant from
   `database.py` — every callsite must go through
   `get_engine_for_tenant()`.

## 5. What changes operationally

### 5.1 New env vars

| Var | Set on | Notes |
|---|---|---|
| `DATABASE_URL_MX` | nexus-api, workers, gateway | MX-region Postgres URL; resolves via in-region private DNS |
| `DATABASE_URL_US` | nexus-api, workers, gateway | Existing `DATABASE_URL` renamed; backwards-compat fallback for one release cycle |
| `DATABASE_URL_EU` | nexus-api, workers, gateway | Future region; unset until first EU tenant onboards |
| `KMS_KEY_ID_MX` | backup cronjob, MX region only | KMS key in Mexican jurisdiction; controls backup encryption for MX cluster |
| `KMS_KEY_ID_US` | backup cronjob, US region only | Existing key, renamed |
| `LOG_REGION` | every pod | Tags structured logs with the region for downstream routing to the right log store |
| `CROSS_REGION_ADMIN_ENABLED` | nexus-api admin namespace only | Gates the cross-region admin endpoints (§6); default `false` |

### 5.2 New routing helper

```python
# apps/nexus-api/nexus_api/database.py (new helper, signature only)

async def get_engine_for_tenant(org_id: str) -> AsyncEngine:
    """Resolve the right Postgres engine for a tenant.

    Reads tenant_configs.data_residency_region (cached in Redis with
    60s TTL) and returns the engine for that region. Falls back to
    the default region (US) when the tenant has no row yet (during
    onboarding bootstrap).
    """
```

The helper is the single chokepoint for residency dispatch. It is
covered by a unit test that asserts it raises (not silently
defaults) when given an `org_id` whose `data_residency_region` is set
to a region whose `DATABASE_URL_*` env var is unset — fail-closed,
not fail-to-default.

### 5.3 Per-region Alembic configurations

`alembic.ini` gains a `[<region>]` section per region with its own
`sqlalchemy.url` template. The migration runner becomes:

```
make db-migrate REGION=mx
make db-migrate REGION=us
make db-migrate REGION=eu  # when applicable
```

A wrapping `make db-migrate-all` runs the matrix. Migrations land in
one region first (canary), soak for 30 min (per the existing
`MIN_SOAK_MINUTES` repo var), then fan out.

### 5.4 Per-region backup cronjobs

The existing `infra/k8s/production/backup-cronjob.yaml` becomes a
template. The Kustomize overlay pattern from PP.4 (CLAUDE.md
§"Deployment Pipeline") suggests a new
`infra/k8s/overlays/production-mx/` overlay that re-uses the base
cronjob with an MX-specific S3 bucket, KMS key, and pgdump endpoint.

### 5.5 Per-region Cloudflare tunnels + Enclii deployments

Each region gets its own Cloudflare tunnel (`api-mx.selva.town`,
`api-us.selva.town` — though the public hostname is still
`api.selva.town`, which load-balances per the routing layer that RFC
0021 will define). Enclii's `enclii.yaml` may need a per-region
service definition; this is a conversation with the Enclii team and
is tracked in §7 Q3.

### 5.6 K8s topology

Two viable options, picked at the cluster-design level:

(a) **Namespace per region in the same cluster** — `selva-mx`,
   `selva-us`. Simple if all regions are in the same physical
   cloud (which defeats the purpose for SAT — MX must be on
   MX-jurisdiction infra). Acceptable as a transitional state.

(b) **Cluster per region** — `selva-mx-cluster`, `selva-us-cluster`.
   Each has its own ArgoCD app, its own image registry pull
   credentials, its own monitoring. Right answer long-term.

Recommend (b). Phase A-D can proceed in (a)-shaped infra (namespace
per region in the existing cluster) for development simplicity, with
an explicit cutover to (b) before the first SAT tenant goes live.

## 6. Cross-region operations that DON'T need to be region-scoped

A subset of platform operations span all tenants regardless of region.
These need explicit cross-region access via a service account that
holds credentials for every regional cluster.

| Operation | Why cross-region | Access pattern |
|---|---|---|
| `POST /api/v1/swarms/tasks/reap-stale` | Stale tasks can exist in any region | Iterate regions, run reap per region, aggregate results |
| Daily billing rollups | Dhanam needs total task counts per tenant regardless of where the tenant lives | Iterate regions, sum per-tenant, push to Dhanam |
| `/api/v1/health/dlq-stats` | DLQ depth is per-region but ops needs the union | Iterate regions, return per-region breakdown + total |
| MADFAM platform admin queries | Audit search for "find every tenant who did X" | Iterate regions, union results |
| Cross-region audit aggregation (RFC 0019) | The CDC audit topic spans all regions | Each region's Debezium publishes to a single shared Kafka cluster (which itself has its own residency story — see §7 Q5) |
| Quota enforcement (CLAUDE.md A2A §6) | Per-caller daily limit can be exceeded across regions | Use Redis cross-region counter (Redis cluster with global keys) OR sum at quota-check time |
| Tenant migration tool (Phase E) | Reads from one region, writes to another | The single legitimate cross-region data movement; logged + audited |

The pattern: a `CROSS_REGION_ADMIN_ENABLED=true` flag gates the
nexus-api endpoints that need to span regions. The flag is set ONLY
on the admin-namespace deployment of nexus-api, never on the
tenant-facing deployments. This isolates the cross-region credential
holder to a single deployment class that can be locked down with
NetworkPolicy + admission controller checks.

The list above is closed by intent. Adding a new cross-region
operation requires an explicit RFC amendment (this is a tenancy /
residency boundary, not a "small operational tweak").

## 7. Open questions

| # | Question | Provisional direction |
|---|---|---|
| Q1 | Karafiel + Dhanam region story — do they shard the same way? | Yes, must — a Selva tenant in MX-region whose Karafiel CFDI submissions land in a US-region Karafiel database is a residency violation. This requires a parallel RFC in each ecosystem service. Selva's RFC 0020 lands first; sibling services follow within the same regulatory deadline window. |
| Q2 | Janua's auth — does the JWT carry region? | Janua issues one JWT per tenant. The `org_id` claim is the source of truth for residency dispatch; Janua does NOT need to embed `region` in the JWT because the API resolves region from `tenant_configs` server-side on every request. If Janua's session store is itself residency-scoped, that's Janua's RFC, not this one. |
| Q3 | Backup encryption keys per region | KMS key per region. Mexican tenant data encrypted with a key in Mexican-jurisdiction KMS; US data with US KMS. Keys do not cross regions; cross-region restore is impossible by design (this is intentional). |
| Q4 | Disaster-recovery cross-region failover | Out of scope — see RFC 0021. Critical interaction: an MX tenant's DR target MUST be another MX-region cluster, never a US-region cluster. RFC 0021 §10 calls this out explicitly. |
| Q5 | Audit log aggregation across regions (RFC 0019 interaction) | The Kafka cluster RFC 0019 stands up may itself need to be regional. Two options: (a) one Kafka per region, audit aggregator joins across — simpler residency story, harder query story; (b) one global Kafka, residency-aware producer SMTs that strip PII fields before cross-region publish — harder residency story, simpler queries. Resolution deferred to RFC 0019 amendment. |
| Q6 | Connection pool sizing under multi-region | Each app pod holds a pool to every region it might serve. Recommendation: lazy pool initialization — pool to region X is created on first request to a tenant in region X, never created if no tenant from that region ever calls this pod. Combined with a sticky load balancer that prefers in-region pods, the steady-state pool count is small. |
| Q7 | Read replicas | Out of scope for this RFC. A read replica in the same region as the master is straightforward and inherits the residency story. A cross-region read replica violates residency for SAT data and is forbidden by Pattern A. Within-region replicas are an RFC 0021 concern (latency / failover). |
| Q8 | Tenant growth path | A tenant that starts US (e.g., a US enterprise) and later wants to expand to a Mexican subsidiary that needs CFDI — do they get a second tenant row, or does their existing row migrate to MX? Recommendation: separate tenant rows. A tenant is residency-scoped at the tenancy boundary. The tenant's UI can switch between sub-tenants; the data does not commingle. |

## 8. Acceptance criteria

The implementation phase is complete when ALL of the following hold:

- [ ] `tenant_configs.data_residency_region` column exists in
      production with NOT NULL constraint and ENUM values
      `('MX','US','EU')`.
- [ ] `get_engine_for_tenant(org_id)` is the sole resolver of
      DB engines in nexus-api and workers; the legacy module-level
      `engine` constant is removed (Phase F).
- [ ] An MX-region Postgres cluster exists, has all migrations
      applied, has a per-region backup cronjob writing to a
      Mexican-jurisdiction S3 bucket encrypted with a Mexican-
      jurisdiction KMS key.
- [ ] At least one production tenant exists with
      `data_residency_region = 'MX'`, and that tenant's CFDI rows
      are physically and verifiably in the MX cluster (auditor-
      reproducible: log into the MX cluster, `SELECT … WHERE
      org_id = <tenant>` returns rows; same query against US
      cluster returns zero).
- [ ] Onboarding flow has a residency-region step, and the choice is
      persisted on the new tenant's `tenant_configs` row.
- [ ] Migration tool (`scripts/migrate-tenant-region.py`) exists,
      has been exercised against a synthetic tenant, and its
      verification step (checksum + drop-source) is implemented and
      tested.
- [ ] `CROSS_REGION_ADMIN_ENABLED` flag exists and is wired into
      every cross-region admin endpoint listed in §6.
- [ ] Per-region backup retention + restore drill has been
      exercised: pick a random row from the MX cluster, simulate a
      data-loss scenario, restore from the MX backup, verify the
      row returns. RTO target: 30 min.
- [ ] CLAUDE.md updated with the new env vars and the
      `get_engine_for_tenant` chokepoint pattern.
- [ ] Operator-side cost reporting (Dhanam) attributes infra cost
      per region per tenant, so the unit-economics question
      (§10) is answerable from real data, not estimate.
- [ ] RFC 0021's failover runbook honors residency (an MX tenant
      fails over to MX-region standby, never US).

## 9. Alternatives considered

### 9.1 Fully managed multi-region DB (AWS Aurora Global, GCP AlloyDB)

**Shape**: instead of standing up our own Postgres clusters per
region, use a managed multi-region Postgres product that handles the
replication topology, automated failover, and per-region writers.

**Pros**:
- Lower operational surface — the cloud provider handles backup,
  patching, failover orchestration, and replica management.
- Cross-region read replicas come for free.
- Backup-encryption-key-per-region typically supported (AWS KMS
  multi-region keys; GCP Cloud KMS regional keys).
- Mature production track record at large scale (Aurora Global
  serves several Fortune 500 multi-region deployments).

**Cons**:
- Vendor lock-in. SAT compliance requires us to be able to attest to
  the cloud provider's data-residency contract; Aurora Global's
  Mexican region availability is incomplete (as of 2026-Q1, AWS has
  no Mexico-mainland region — `mx-central-1` is announced for late
  2026 but not yet generally available). Until that lands, an
  AWS-only strategy can't serve SAT tenants without a hybrid that
  defeats the simplicity argument.
- Same problem on GCP — no Mexico region as of 2026-Q1.
- Cost per multi-region cluster is materially higher than self-
  managed Postgres (typically 2–4× per workload).
- Consent ledger work (CLAUDE.md v2.2.0) and the append-only
  REVOKE-pattern from migration 0018 are Postgres-role-specific;
  managed services may restrict role management. Aurora and AlloyDB
  both allow custom roles, but the REVOKE patterns need re-
  verification per service.

**Verdict**: revisit when AWS `mx-central-1` and GCP equivalent are
generally available with the role-management primitives we need.
Until then, self-managed Postgres in a Mexican-jurisdiction colo or
Mexican-jurisdiction cloud (KIO, Neutral Networks, Triara) is the
realistic path.

### 9.2 Single global cluster + application-layer encryption per region

**Shape**: keep the single Postgres, encrypt rows belonging to
SAT tenants with a key held in Mexican KMS, decrypt only when the
caller is in-Mexico.

**Pros**:
- No new clusters.
- Encryption-at-rest with regional key satisfies a literal reading
  of the LFPDPPP "datos en territorio" requirement (the key is in
  territory, the data is unreadable outside it).

**Cons**:
- The 2025 amendment broadened "datos personales" to include the
  storage medium itself, not just readable data. Under the new
  reading, encrypted CFDI rows in a US-region disk are still
  US-resident `datos personales`.
- Application-layer encryption breaks indexing — every WHERE
  clause that touches encrypted columns becomes a full table scan
  unless we maintain HMAC-blinded index columns, which is a large
  engineering investment.
- pgvector is one of our key technologies; encrypted vector columns
  break similarity search. Selva's memory subsystem
  (`packages/memory/`) depends on this.

**Verdict**: rejected. The amendment killed the legal cover this
approach used to enjoy; the engineering cost is large; the operational
benefit (no new clusters) is real but doesn't justify the legal risk.

### 9.3 Federated Postgres via Foreign Data Wrappers

**Shape**: per-region Postgres clusters, with FDW tables in a
"global" cluster that proxies queries across.

**Pros**: cross-region joins look like local SQL.

**Cons**: every cross-region read pulls data across the boundary in
flight, which is itself a regulated transfer. Defeats the purpose.

**Verdict**: rejected.

## 10. Cost estimate

Minimum viable Pattern-A-for-MX + Pattern-C-for-everyone-else, year 1:

| Line | Estimate (USD/mo) | Notes |
|---|---|---|
| MX-region Postgres cluster (3-node primary + 1 read replica) | $400–700 | Self-managed on Mexican cloud (KIO, Triara). Cheaper than AWS RDS multi-AZ; doesn't include the AWS savings-plan discounts we get on the US cluster. |
| MX-region backup storage (S3-compatible, MX jurisdiction) | $30–80 | 100 GB working set, 30-day retention. Cost grows linearly with tenant count. |
| MX-region KMS | $5–20 | Per-key + per-API-call cost. Very low at our current volume. |
| MX-region observability (logs, metrics) | $50–150 | Loki / VictoriaMetrics stack on MX cloud. |
| MX-region monitoring + alerting | $0 | Reuses existing Grafana, just adds an MX datasource. |
| MX-region Cloudflare tunnel | $0 | Cloudflare tunnels are free for our usage. |
| Engineering time for Phase A-F | ~6 person-weeks | Spread across 3 cycles. |
| Per-tenant operational overhead (ops oncall surface) | +1 region in the rotation | Concrete cost: one extra runbook the ops team needs to know. |
| Total recurring | **~$500–1000/mo** | For ONE tenant in MX-region. Marginal cost per additional MX tenant: storage + monitoring growth, not cluster cost. |

Notes on cost dynamics:

- The MX cluster is amortized over MX tenants. With one MX tenant,
  it's $500-1000/mo dedicated overhead; with 50 MX tenants on the
  same cluster, it's ~$15-25/tenant/mo of infrastructure. The
  unit-economics tipping point is around 5–10 MX tenants — below
  that, MX residency is a loss leader paid by the platform; above
  that, it's a margin business.
- The Tulana v0.1 pricing tiers (Maker 85 MXN/hr / Studio 170 MXN/hr
  / Enterprise 255 MXN/hr — CLAUDE.md §"Pricing & PMF Anchoring")
  do not currently price-in residency. Pattern A makes residency
  visible as a cost line, which forces the conversation: is MX
  residency a default-included feature for Mexican tenants (and
  factored into base pricing), or an explicit add-on SKU?
  Recommend the former — Mexican tenants are the home market;
  residency is table stakes, not an upsell.
- A future EU region triggers the same conversation under GDPR.
  Recommend treating EU as a Pattern A cluster from day one (don't
  attempt to defer to Pattern C for EU tenants — the regulatory
  ask is similar enough to LFPDPPP that the architecture choice
  should be the same).

---

*Sections written: §1–§10 complete. No TBDs in §1, §3, §4, §5, §6,*
*§8, §9, §10. §2 written as options analysis with explicit*
*recommendation in §3. §7 captures explicit open questions with*
*provisional directions; final answers expected during Phase A-B*
*review with Karafiel + Dhanam + Janua teams.*
