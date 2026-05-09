# RFC 0019 — Cross-service CDC audit topic

**Status**: Draft
**Author**: Claude Opus (anonymous-co-author)
**Date**: 2026-05-04
**Supersedes**: nothing (extends RFC 0006 ecosystem audit, RFC 0018 A2A external tenant)
**Related**: `docs/AUDIT_TRAIL_GAP_ANALYSIS.md`, [ROADMAP.md](../../ROADMAP.md) Phase 3 §"Audit trail completeness"

---

## 1. Problem

After audit-trail waves 1-3 (PRs #130, #131, #133), 37 of 37 in-Selva
mutation sites emit `TaskEvent` rows when state changes. **That answers
"what changed in Selva"** — but it doesn't answer **"what changed in
the MADFAM ecosystem on behalf of tenant X."**

Concrete examples of cross-service queries that are unanswerable today:

- "Show me everything that touched tenant `org-acme` between
  2026-04-15 09:00 and 12:00 — Janua sessions issued, Selva tasks
  dispatched, Dhanam billing events recorded, Karafiel CFDIs
  submitted, Enclii deploys that affected services they use."
  → 5 separate audit logs, no joinable identifier across them.

- "Which tenant's PII appeared in which logs in the last 30 days?"
  → no answer; would need to grep 5 different services' log retentions.

- "Did consent-mode change in Selva precede or follow the LFPDPPP
  data-deletion request that Tezca processed for the same tenant?"
  → today, manual archaeology across two systems.

**Why the manual `emit_event_db` discipline doesn't scale**:

1. **Per-engineer compliance**. Every new mutation endpoint depends on
   the engineer remembering to call `emit_event_db`. Audit-trail wave 1
   (PR #130) found 4 endpoints that the gap-doc author had assumed
   existed but didn't, and 4 more that existed but weren't on the list.
   Coverage drift is inevitable as the codebase grows.

2. **Cross-service correlation requires coordination**. Selva's
   `TaskEvent.payload.tenant_id` and Dhanam's `BillingEvent.org_uuid`
   and Janua's `SessionLog.subject_id` aren't guaranteed to be the
   same string format, let alone the same value. Today's manual
   approach has no enforcement of this contract across services.

3. **Reactive, not proactive**. The audit trail exists to answer
   compliance + incident-response queries AFTER the fact. Today the
   answer to "did we capture event X" is "let me grep the code."
   That's a flag-on-merge gate, not a runtime guarantee.

4. **No replay**. If a downstream consumer (compliance dashboard,
   anomaly detector) needs to rebuild its state, it can't replay the
   stream — `TaskEvent` is an append-only Postgres table, not a Kafka
   topic with offsets and consumer groups.

---

## 2. Proposal

Replace the manual `emit_event_db`-everywhere discipline with **CDC
(Change Data Capture)** at the database layer:

```
Postgres (each service)  →  Debezium  →  Kafka  →  audit topic  →  consumers
```

Every row INSERT / UPDATE / DELETE on tenant-scoped tables (the same
18 tables that have RLS policies — see migration 0025) automatically
becomes a Kafka message. No app-layer remembering required.

The audit topic is **single, ecosystem-wide, schema-versioned**. Janua,
Dhanam, Selva, Enclii, Karafiel, Tezca all write to it. A unified
consumer can join events by `tenant_id` (the sole cross-service
identifier we standardize on) and answer the queries §1 lists today.

---

## 3. Architecture

### 3.1 Per-service producer

Each service runs a Debezium connector configured against its
production Postgres. Debezium tails the WAL (write-ahead log) and
emits one Kafka message per row change. Configuration lives in each
service's `infra/debezium/connector.json`:

```json
{
  "name": "selva-postgres-cdc",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "${POSTGRES_HOST}",
    "database.port": "5432",
    "database.user": "${DEBEZIUM_USER}",
    "database.password": "${DEBEZIUM_PASSWORD}",
    "database.dbname": "autoswarm",
    "database.server.name": "selva",
    "table.include.list": "public.swarm_tasks,public.tenant_configs,public.consent_ledger,...",
    "plugin.name": "pgoutput",
    "snapshot.mode": "never",
    "transforms": "addOrgId,addServiceName",
    "transforms.addOrgId.type": "org.apache.kafka.connect.transforms.ExtractField$Value",
    "transforms.addOrgId.field": "org_id"
  }
}
```

Three Debezium-specific requirements that need engineering:

1. **A `BYPASSRLS` Postgres role** for Debezium so it sees every
   tenant's row (RLS strict mode lands in PR #134 — Debezium would
   otherwise see zero rows). The `app_admin` role added in PR #134
   covers this; Debezium's connector uses `database.user=app_admin`.

2. **`REPLICA IDENTITY FULL`** on every tenant-scoped table so the
   pre-image of UPDATE / DELETE rows is captured. New Alembic migration
   to set this on the 18 tables.

3. **Schema registry** (Confluent Schema Registry or equivalent) to
   version the Avro / JSON Schema for each table's CDC payload.

### 3.2 Topic structure

One topic per (service × table). Topics live in a single Kafka
cluster shared across the ecosystem:

```
selva.swarm_tasks
selva.tenant_configs
selva.consent_ledger
janua.sessions
janua.users
dhanam.subscriptions
dhanam.billing_events
karafiel.cfdis
enclii.deploys
...
```

Naming: `<service>.<table>` — predictable, greppable, lets a
consumer subscribe to "everything Janua does" via wildcard.

A second tier of derived topics for cross-service queries:

```
ecosystem.tenant_lifecycle    -- joined view: created → upgraded → deleted
ecosystem.compliance_audit    -- LFPDPPP-relevant events only
ecosystem.security_signals    -- auth + permission failures across services
```

These derived topics are computed by Kafka Streams jobs that subscribe
to the per-service topics and republish.

### 3.3 Cross-service identifier contract

The single most important contract for cross-service correlation:
**every emitted row MUST carry a stable `tenant_id` field.**

- Selva uses `org_id` (the JWT claim Janua issues)
- Janua uses `tenant_id` (its primary key)
- Dhanam uses `org_uuid`
- Karafiel uses `tenant_id`

These all refer to the same logical entity but are typed + named
differently. RFC compliance requirement: **every service ships a
Kafka SMT (Single Message Transform) that renames its local field to
`tenant_id`** before publishing. The consumer side joins on this
single name.

For services that DON'T have a tenant in the row (e.g., Enclii deploy
events affect ALL tenants of the deployed service), the field is set
to `null` and the consumer's join logic handles that.

### 3.4 Consumer model

Two reference consumers ship with this RFC's implementation:

1. **`apps/audit-aggregator/`** (new service in this repo) — Python
   FastAPI app that subscribes to the audit topics + maintains a
   denormalized Postgres table (`unified_audit_log`) joinable by
   tenant_id. Backs a `/api/v1/audit/unified` endpoint (already
   scaffolded — `apps/nexus-api/nexus_api/routers/audit_unified.py`)
   that today returns mocked data.

2. **`apps/anomaly-detector/`** (out of scope for THIS RFC; tracked
   separately) — ML/heuristic consumer that flags unusual patterns
   (e.g., 100x normal task dispatch rate from one tenant).

Other consumers can be added by any team without coordination —
Kafka's offset-per-consumer-group semantics mean a new subscriber
doesn't impact existing ones.

---

## 4. Migration path (4 phases)

### Phase A: Single-service pilot (Selva only) — 2 weeks

1. Stand up Kafka cluster (3-broker minimum for HA; can start with
   single-broker dev for the pilot)
2. Stand up Schema Registry
3. Run Debezium against Selva's prod Postgres, configured to publish
   only `swarm_tasks` and `tenant_configs` to start
4. Verify CDC events flow + Schema Registry validates them
5. Build the consumer side of `audit-aggregator` reading from these 2
   topics, persisting to `unified_audit_log` table
6. Wire the existing `routers/audit_unified.py` to the real
   `unified_audit_log` table (today it returns mocks)

**Acceptance**: a Selva tenant_configs change is queryable via
`GET /api/v1/audit/unified?tenant_id=X` within 5 seconds of the
mutation.

### Phase B: Selva full coverage — 1 week

7. Extend Debezium config to all 18 RLS-managed tables
8. Verify per-table SMTs correctly emit `tenant_id` in every payload
9. Backfill: snapshot the existing tables once via Debezium's snapshot
   mode (one-shot); after that snapshots are off and only WAL deltas
   are captured

**Acceptance**: every Selva mutation in the last 7 days is queryable
via the unified audit endpoint within the same 5s budget.

### Phase C: Sibling services join (1 service per week) — 5-6 weeks

10. Janua first (most queries depend on auth events for context)
11. Dhanam second (billing audit is the most-asked LFPDPPP question)
12. Karafiel third (Mexican SAT submissions are the highest-stakes)
13. Tezca, Enclii, PhyndCRM round out the set

Each sibling service follows the same pattern: stand up Debezium →
verify per-table SMTs → ship to staging → 7-day soak → enable in prod.

**Acceptance per service**: cross-service join queries (Janua session
issuance + Selva task dispatch for the same tenant within 60s)
return results.

### Phase D: Deprecate manual `emit_event_db` discipline — 2 weeks

14. CDC-derived `unified_audit_log` becomes the authoritative source
15. The in-Selva `task_events` table stays (downstream UI consumers
    rely on its specific shape) but is ALSO populated by the CDC
    consumer rather than by manual `emit_event_db` calls
16. The 37 manual `emit_event_db` call sites get marked deprecated;
    new mutation endpoints don't need to add them
17. Existing `emit_event_db` calls stay for a 90-day grace period so
    downstream UI breakage is detectable; then removed

**Acceptance**: a new mutation endpoint added with NO `emit_event_db`
call still produces an audit event because CDC catches the row write.

Total duration: ~10-11 weeks engineering across 4 phases. Phase A is
prerequisite for everything else; Phases B-D can ship sequentially.

---

## 5. Schema versioning

Each per-service topic carries Avro / JSON Schema messages registered
with the Schema Registry. Schema evolution rules:

- **BACKWARD compatible** (default): consumers built against schema
  v1 can read v2 messages. New fields with defaults; never delete or
  rename existing fields.
- **Breaking changes** (e.g., type change of an existing field) get a
  new topic version: `selva.swarm_tasks.v2`. v1 stays running for a
  90-day deprecation window. Consumers migrate independently.

PRs that change a schema MUST update the Schema Registry + bump
the topic version. CI gate (cross-repo, lives in the schema-registry
repo) blocks the change if the new schema breaks BACKWARD
compatibility.

---

## 6. Quota + access control

Kafka topics are not free to read; granting unlimited consumption to
any service that asks would let a runaway consumer DOS the Kafka
cluster.

ACL model:

- **Producers** (the Debezium connectors, one per service): own
  topic(s) only — `selva.*` connector can write to topics matching
  `selva.*`, nothing else
- **Consumers**: per-team SCRAM credentials with read access scoped
  to the topics that team needs. Granted via PR to a central
  `kafka-acls.yaml` repo.
- **Cross-service joins**: the `audit-aggregator` is a privileged
  consumer with read access to ALL topics. Other consumers that need
  a join build a derived topic and subscribe to that.

---

## 7. Open questions

1. **Kafka cluster ownership** — does this live in the `internal-devops`
   K8s cluster or get its own? Cost vs ops-surface tradeoff. Recommend:
   start in `internal-devops` cluster; spin out only when load justifies.

2. **Debezium hosting** — Kafka Connect cluster (one per Kafka cluster)
   or per-service sidecar? Recommend: shared Kafka Connect cluster
   for ops simplicity; per-service connector configs.

3. **PII redaction** — some columns (email, RFC, phone) are PII per
   LFPDPPP. Should CDC redact them at producer time, consumer time, or
   not at all (relying on consumer ACLs)? Recommend: producer-side
   redaction via Debezium SMT for known-PII columns; consumer ACLs
   as defense in depth.

4. **Cost** — Kafka cluster + Schema Registry + Kafka Connect cluster
   is not cheap. Estimate operator-side: ~$300-800/mo for a 3-broker
   AWS MSK + Confluent Schema Registry + 2 Connect workers. Justified
   by replacing 5+ separate audit logs and the manual-discipline
   coverage gap.

5. **Backwards compatibility with the existing `task_events` table** —
   downstream UI (OpsFeed component in office-ui) reads from
   `task_events` directly. Migration plan: a Kafka consumer projects
   `selva.swarm_tasks` → `task_events` rows so the UI keeps working
   unchanged. Deletion of `task_events` deferred until all UI
   consumers can be repointed at the unified endpoint.

6. **Replay semantics** — if a consumer needs to rebuild from
   scratch, how far back can it go? Kafka topic retention default
   168h (7d). For audit purposes, this is too short. Recommend:
   compacted-tier topics with 1-year retention for the per-service
   audit topics.

7. **Debezium snapshot of existing data** — Phase B step 9 mentions
   one-shot snapshot. Concern: a snapshot of `swarm_tasks` (10M+ rows
   at scale) takes hours and bombards the audit topic. Recommend:
   incremental snapshots (Debezium 1.6+) that chunk the snapshot into
   manageable batches.

---

## 8. Acceptance criteria (RFC complete when)

- [ ] Operator decision on Kafka cluster ownership (§7 q1)
- [ ] Operator approves the cost estimate (§7 q4)
- [ ] Phase A pilot lands: `selva.swarm_tasks` + `selva.tenant_configs`
      flowing through CDC, queryable via `audit_unified` endpoint
- [ ] Phases B + C + D execute on the published timeline
- [ ] `docs/AUDIT_TRAIL_GAP_ANALYSIS.md` superseded — manual emit
      coverage stops being a code-review gate
- [ ] Cross-service queries (e.g., "show me tenant X's lifecycle
      across Janua + Selva + Dhanam") return results
- [ ] Per-service Debezium config + Kafka ACLs documented in each
      service's repo

---

## 9. Alternatives considered

### A. Stay with manual `emit_event_db` + cross-service `tenant_id` standardization

Lower cost, higher engineering ongoing-discipline burden. Coverage
drift is inevitable as the codebase grows; we have evidence (audit
gap doc found 16 of 38 routers had GAPS). Not selected.

### B. Outbox pattern (per-service) + REST aggregator

Each service writes events to a local `outbox` table, and a sidecar
process publishes them to the aggregator over REST. Avoids Kafka
ops cost. Loses replay semantics + cross-service join performance.
Acceptable for 3-service ecosystems; doesn't scale to 6+. Not
selected.

### C. AWS EventBridge / GCP Eventarc managed bus

Lowest operator burden. Vendor lock-in (we'd be choosing a cloud
even where Selva might want to be cloud-portable for a regulated MX
tenant). Limited consumer-side replay. Not selected for the long
arc; revisit if MADFAM commits to a single cloud.

### D. Postgres Foreign Data Wrapper / cross-service schema

Each service exposes a read-only FDW into its tables. Joins happen
in SQL. Doesn't scale to 6+ services (every consumer needs a
connection to every service's DB). Tightly couples deployment
schedules. Not selected.

CDC was selected because it's the only architecture that gives us
all four properties: per-service decoupling, replay semantics,
cross-service join, and zero engineering ongoing discipline.

---

## 10. Owner + timeline

- **Owner**: Backend infra (Selva team driving Phase A; sibling
  service teams own their respective Phase C steps)
- **Phase A**: 2 weeks engineering
- **Total**: 10-11 weeks across 4 phases
- **Operator decisions blocking start**: §7 q1 (cluster ownership) +
  §7 q4 (cost approval)
