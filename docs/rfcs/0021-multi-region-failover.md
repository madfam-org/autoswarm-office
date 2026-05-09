# RFC 0021 — Multi-region failover

| Field | Value |
|---|---|
| Status | Draft |
| Author | Architect (Selva Office) |
| Created | 2026-05-03 |
| Supersedes | — |
| Related | RFC 0020 (per-tenant data residency, paired — failover MUST honor residency boundaries), RFC 0019 (cross-service CDC audit topic — replication backbone interacts with audit stream), RFC 0018 (A2A external-tenant model), `infra/k8s/production/`, `infra/argocd/staging.yaml`, `.github/workflows/promote-to-prod.yml`, `.github/workflows/rollback-prod.yml` |

## 1. Status quo

Selva is a single-region deployment today. Concretely:

- One ArgoCD application (`autoswarm-office` in production) syncs
  one Kustomize overlay to one Kubernetes cluster.
- One Postgres StatefulSet (`pgvector/pgvector:pg16`) holds every
  tenant's data — see RFC 0020 §1.1 for the residency analysis of
  that fact.
- One Redis instance (Streams + pub/sub for the worker queue and
  Colyseus state).
- One set of Cloudflare tunnels (`api.selva.town`, `selva.town`,
  `admin.selva.town`, `ws.selva.town`, `gw.selva.town`) routing to
  one cluster ingress.
- One Janua issuer; one Dhanam billing endpoint; one Karafiel; one
  PhyndCRM. The whole MADFAM ecosystem is co-resident.

The recovery surface today:

- **RTO**: undefined / unmeasured. If the region goes down, recovery
  time is "however long it takes to bring the region back up" — i.e.,
  it's the cloud provider's RTO, which Selva has no control over.
- **RPO**: bounded only by the backup cronjob cadence
  (`infra/k8s/production/backup-cronjob.yaml`, daily). Worst-case
  data loss in a region-loss scenario: ~24 hours.
- **DR plan**: nonexistent in any documented form. Implicit plan is
  "wait for the region to come back, then restore from backup if
  the region's storage was destroyed."

What this means in practice: a regional outage of the cloud Selva
runs in (whether the colo, the cloud-provider region, or the
network upstream of either) takes the entire platform offline for
the duration of the outage. For an internal-MADFAM tool this was
acceptable; for a platform that sends real customer emails (Resend),
pushes real git branches (GitHub API), and processes real Stripe
events, it is not.

The trigger for this RFC: SAT-bound tenants (RFC 0020) imply a
production-grade SLA that the single-region default cannot meet.

## 2. Recovery model — three options

### 2.1 Option A — Active-passive (warm standby in second region)

A second region runs a continuously-replicated read replica of the
primary's Postgres + a stopped (zero-replica) deployment of every
stateless service. On failover, ops promotes the replica to primary,
scales the stateless services up, and swaps DNS to the new region.

**Pros**:
- Lowest implementation complexity. Postgres streaming replication
  is well-understood. Stateless services scale up via standard
  Kubernetes / ArgoCD operations.
- Per-region cost is roughly +50% over single-region (one full
  passive cluster + replication network egress).
- Failover decisions remain human-in-the-loop, which is appropriate
  for a system that processes financial events.
- Compatible with RFC 0020 — passive standby in MX is a separate
  concern from passive standby in US, and they don't need to be
  symmetric.

**Cons**:
- RTO is bounded by human reaction time + DNS propagation, not by
  software. Best case: ~15 min; realistic: 30 min to 1 hour for the
  first incident before the runbook is muscle-memory.
- Passive cluster is idle compute most of the time — capital cost
  with no operational return until disaster strikes.
- Drill discipline is required to keep the standby actually
  recoverable (see §8).

### 2.2 Option B — Active-active (read split by latency, write to primary)

Both regions accept read traffic with latency-based DNS routing.
Writes still go to a designated primary, with async replication to
the secondary. On primary failure, the secondary's reads keep
serving while the secondary is promoted to writer.

**Pros**:
- Read latency improves for the secondary region's users (they
  serve their reads locally).
- Failover RTO is software-driven, ~5 min worst case.
- Active utilization of the second region's compute (not just
  paying for idle).

**Cons**:
- Async replication lag introduces read-after-write inconsistency
  for cross-region reads. A tenant whose request hits the secondary
  for a read 100ms after a write to the primary may see stale data.
- Worker queue (Redis Streams) becomes harder — workers in the
  secondary region either consume from a single global Redis (which
  has its own residency story) or maintain a per-region queue with
  rebalancing logic.
- Colyseus rooms have client affinity — moving a room mid-session
  isn't trivial. Players in a room need to all be talking to the
  same Colyseus instance.
- Higher cost (~80% premium over single-region) and higher
  operational complexity.

### 2.3 Option C — Active-active multi-master

Both regions accept writes; conflicts are resolved via CRDT,
last-write-wins, or app-layer reconciliation.

**Pros**: theoretically zero RTO; both regions fully usable for
all operations.

**Cons**: in a tenant-isolated system where each row has a single
owning tenant, the conflict-resolution problem is mostly self-
inflicted — there shouldn't be concurrent writes to the same row
from two regions in the first place. The complexity buys nothing
the application actually needs, while introducing the well-known
hazards of multi-master Postgres (split-brain, conflict-resolution
order-dependence, the BDR licensing question).

**Verdict**: rejected upfront. Not worth the complexity for our
workload shape. Tenants are region-pinned (RFC 0020); concurrent
cross-region writes shouldn't happen by design.

## 3. Selection — Active-passive for the next 12 months

Recommend **Option A (active-passive)** for the next 12 months,
with **Option B (active-active)** as the next-quarter goal once
regional infrastructure discipline is mature.

Rationale:

1. Option A delivers a measurable RTO/RPO improvement now, with a
   tractable engineering investment.
2. Option A's failover-by-runbook keeps the human in the loop for
   the high-stakes financial / outbound-email surface area —
   appropriate for the v2.2.x Selva that just shipped fail-closed
   webhook verification and the consent ledger.
3. Option B requires resolution of the queue-replication question,
   the Colyseus room-affinity question, and the read-after-write
   consistency question — none of which are blockers for the
   current customer base.
4. Option A's runbook discipline (§7) is a prerequisite for Option
   B regardless. We can't ship active-active before we've proven we
   can do active-passive.

The path: Q3 2026 ships Option A in MX + US regions. Q1 2027
revisits the upgrade to Option B once the runbook has been drilled
quarterly for two cycles.

## 4. Postgres replication strategy

Two viable approaches:

### 4.1 Streaming replication via WAL

Standard Postgres physical replication. Primary streams WAL records
to one or more standbys, which apply them in order. Selva's chosen
default for the active-passive model.

**Pros**:
- First-party Postgres feature; well-understood, well-tooled.
- Synchronous-replication option exists if RPO=0 is required for a
  specific region (recommended for SAT-bound regions where data
  loss is regulatorily expensive; see §10).
- Read-only access to the standby for backup offloading.
- pgvector + the consent ledger REVOKE pattern (CLAUDE.md
  §"Consent ledger integrity") replicate transparently — physical
  replication preserves all role grants.

**Cons**:
- Replica must be the same major version as primary; upgrades
  require a brief failover.
- Cannot replicate selectively — the entire cluster ships, including
  any cross-tenant data you'd rather not move. For RFC 0020
  Pattern A clusters this is fine because the cluster is already
  scoped to a residency boundary.

### 4.2 Logical replication via pglogical

Row-level logical replication. Subscribers can be different major
versions; can replicate selected tables only; can perform
transformations on the way out.

**Pros**:
- Cross-major-version replication enables zero-downtime Postgres
  upgrades.
- Selective replication — could exclude tables from cross-region
  replication if needed (e.g., per-region cache tables).
- Plays nicely with RFC 0019's CDC pipeline — Debezium is itself a
  logical-replication consumer.

**Cons**:
- DDL changes (Alembic migrations) are NOT replicated; must be
  applied to subscriber separately. This is operationally
  error-prone.
- Sequences require explicit handling — getting the sequence
  numbers in sync after a failover is non-trivial.
- pgvector + REVOKE patterns require explicit replication setup;
  not transparent.
- Maintenance overhead is higher.

### 4.3 Recommendation

**Streaming replication (4.1) for the active-passive failover
backbone**, because it's the lower-overhead path for the
"hot standby ready to take over" use case.

**Logical replication (4.2) deferred to RFC 0019 's CDC use case**,
where its selective + transformation capabilities are first-class
needs.

Replication mode for SAT-bound regions: **synchronous_commit =
remote_apply** for the secondary in the same residency zone. This
costs latency on every write (the primary waits for the secondary
to acknowledge) but achieves RPO=0 for the residency-scoped
failover pair. For US-region (no regulatory RPO requirement),
**asynchronous replication** is acceptable.

## 5. Redis HA

Redis backs (a) the worker queue (Redis Streams +
`autoswarm:task-stream`), (b) Colyseus state pub/sub, (c) the rate
limiter and circuit breaker state.

Two viable approaches:

### 5.1 Sentinel (per region)

Each region runs a Redis Sentinel cluster (3 sentinels + 1 master
+ 1+ replicas). Sentinel handles in-region failover automatically.
Cross-region: each region has its own independent Sentinel cluster;
the active-passive failover at the application layer also points
the workers / Colyseus at the new region's Redis.

**Pros**: simple in-region story; well-understood.
**Cons**: no built-in cross-region replication; relies on the
application-layer failover to switch Redis endpoints.

### 5.2 Redis Cluster (sharded)

Redis Cluster spans regions with sharding. Hash-slots distributed
across nodes; cross-region reads possible.

**Pros**: single global Redis namespace; data physically distributed.
**Cons**: cross-region writes have latency cost; residency story is
murky (which shard holds which tenant's data?); operationally
heavier.

### 5.3 Recommendation

**Sentinel per region (5.1)**. Each region has its own independent
Redis. On failover, the secondary region's Redis (which has been
running passively, not replicating from the primary) takes over.

The implication: any in-flight Redis state at the moment of
failover is lost. This is acceptable because:
- Worker queue: tasks not yet acknowledged are re-claimed by the
  XAUTOCLAIM pattern Selva already uses (CLAUDE.md §"Architecture
  Notes" → "Task queue"); residual loss is bounded by the queue
  visibility window.
- Colyseus state: rooms are ephemeral; clients reconnect and
  re-establish their state from the database snapshot.
- Rate limiter / circuit breaker: counters reset to zero on
  failover. Conservatively this opens a brief window where rate
  limits are not enforced; defense in depth (DB-level quotas in
  CLAUDE.md A2A §6) catches the worst case.

The decision NOT to replicate Redis cross-region is deliberate.
Redis state in Selva is recoverable / reconstructible; replication
overhead isn't justified.

## 6. Stateless services

Selva's six services (per CLAUDE.md §"Port Assignments") split:

| Service | Stateless? | Failover concern |
|---|---|---|
| nexus-api | Yes | Standard horizontal scale; HPA handles new region |
| office-ui | Yes | Same; Next.js SSR works in either region |
| admin | Yes | Same |
| colyseus | Sticky (room affinity) | See §6.1 |
| gateway | Yes (with a caveat — see §6.2) | Cron-based heartbeat means dual-region needs leader election |
| workers | Yes | Worker queue claim logic handles it |

### 6.1 Colyseus room affinity

A Colyseus room is hosted on a single Colyseus instance. Players in
a room are connected to that instance. On region failover, every
active room dies; players reconnect to the new region's Colyseus
and re-create rooms.

This is acceptable for the failover case (regional disaster); not
acceptable for routine maintenance (need a different mechanism for
zero-downtime Colyseus restarts, which is a separate concern).

### 6.2 Gateway leader election

The gateway's `HeartbeatService` (CLAUDE.md §"Architecture Notes")
runs cron-style work: scrape GitHub events, dispatch enemy waves.
Running it in BOTH regions simultaneously would double-dispatch every
event.

Two approaches:
1. **Active-passive at the gateway level**: only the primary region's
   gateway runs the heartbeat; the secondary's gateway runs in
   standby (deployed but with `HEARTBEAT_ENABLED=false`). Failover
   flips the env var in the secondary.
2. **Leader election via Redis lock**: both gateways try to acquire
   `autoswarm:gateway-leader` lock; only the holder runs the
   heartbeat.

Recommend (2) — it's a small amount of code, removes a manual step
from the failover runbook, and Redis locks with TTL are well-trodden
ground. The lock is region-local Redis (per §5), so on regional
failure the secondary's Redis lock is automatically uncontested.

### 6.3 Front-door routing

The DNS / load-balancer layer that decides which region serves a
request is the failover trigger.

Two viable products:

(a) **Cloudflare Load Balancer** with health checks. Cloudflare polls
   each region's health endpoint; on failure, traffic shifts to the
   healthy region. Configurable session affinity to keep a tenant
   sticky to one region during normal operation.

(b) **AWS Route 53** failover routing policy. Same pattern but in the
   AWS DNS layer.

Cloudflare is recommended because Selva already uses Cloudflare
tunnels for ingress (CLAUDE.md §"Operator actions pending"). One
fewer vendor.

The health-check probe needs to:
- Hit `/api/v1/health` on nexus-api.
- Hit `/health` on the worker pool.
- Hit Colyseus's `/health`.
- Confirm Postgres connectivity.
- Return 200 only if all four are healthy.

A nuance: Cloudflare's health check must NOT trigger a failover on a
brief blip (network hiccup, single-pod restart). Configure with
generous failure thresholds — e.g., 3 consecutive failures over 90
seconds — to avoid flapping.

## 7. Failover runbook

Concrete commands, who pages whom, expected RTO at each step.

### 7.1 Pre-conditions (continuous)

- [ ] Streaming replication healthy: `replication_lag_seconds < 30`
      monitored via Prometheus on both regions.
- [ ] Secondary region's K8s cluster is up; ArgoCD is sync'd; pods
      are at zero replica counts (passive).
- [ ] Cloudflare LB has both regions configured; secondary is in
      "drain" / zero-weight mode.
- [ ] Last successful drill was < 90 days ago.

### 7.2 Detection

| Signal | Source | Trigger |
|---|---|---|
| Cloudflare LB health-check failures (3 consecutive) | Cloudflare | Page on-call (PagerDuty) |
| Prometheus alerting on `up{cluster=primary}` zero | Grafana | Page on-call |
| Manual declaration by ops | Slack | Page on-call |

### 7.3 Decision (target: 5 min)

On-call confirms the region-down hypothesis (not just a partial
outage that auto-recovery will handle):

1. Check Cloudflare status page for primary region's upstream cloud.
2. Check the Prometheus dashboard for the service that triggered the
   alert — is it actually the cluster, or is it one service?
3. Open the failover Slack channel `#incident-failover`. Page the
   secondary on-call.

If the answer is "yes, primary region is gone," declare failover.

### 7.4 Execute (target: 20 min)

```bash
# 1. Promote the secondary Postgres to primary
kubectl --context=selva-secondary -n autoswarm \
    exec -it postgres-0 -- pg_ctl promote -D /var/lib/postgresql/data

# 2. Verify promotion
kubectl --context=selva-secondary -n autoswarm \
    exec -it postgres-0 -- psql -c "SELECT pg_is_in_recovery();"
# Expect: f (false — no longer in recovery, is now primary)

# 3. Scale up the stateless services
kubectl --context=selva-secondary -n autoswarm \
    scale deployment nexus-api --replicas=3
kubectl --context=selva-secondary -n autoswarm \
    scale deployment office-ui --replicas=2
kubectl --context=selva-secondary -n autoswarm \
    scale deployment colyseus --replicas=2
kubectl --context=selva-secondary -n autoswarm \
    scale deployment workers --replicas=3
kubectl --context=selva-secondary -n autoswarm \
    scale deployment gateway --replicas=1

# 4. Confirm pods are healthy
kubectl --context=selva-secondary -n autoswarm get pods
kubectl --context=selva-secondary -n autoswarm \
    exec deployment/nexus-api -- curl -sf http://localhost:4300/api/v1/health

# 5. Flip Cloudflare LB to route to secondary
# (via Cloudflare API or dashboard; runbook includes specific
#  curl invocation against the LB pool's `enabled` flag)

# 6. Verify external traffic is landing on the secondary
curl -sf https://api.selva.town/api/v1/health
# Expect: 200 OK with `region: secondary` in the response

# 7. Page customer-facing comms (status page update)
```

### 7.5 Post-failover (target: 60 min)

- [ ] Confirm worker queue is processing — DLQ depth not climbing.
- [ ] Confirm Colyseus rooms are reconnecting.
- [ ] Confirm Cloudflare LB is healthy.
- [ ] Update status page to "Recovered."
- [ ] Schedule post-mortem (within 5 business days).

### 7.6 Failback (when primary region is back)

This is INTENTIONALLY MANUAL. Failback is harder than failover —
we need to:
1. Snapshot the new primary (the former secondary).
2. Restore that snapshot to the old primary.
3. Configure replication in the OPPOSITE direction (old primary
   becomes the new secondary).
4. Verify replication lag.
5. Schedule a maintenance window.
6. Drain the new primary (former secondary), promote the old
   primary, swap Cloudflare back.

Failback target RTO: 4 hours, in a scheduled maintenance window.
Never an emergency.

### 7.7 Roles + paging

| Role | Who | Action |
|---|---|---|
| Primary on-call | rotation | Detection, decision, execution |
| Secondary on-call | rotation | Backup; takes over if primary on-call is unavailable |
| Comms lead | per-incident | Status page updates, customer notifications |
| Incident commander | on-call manager | Coordinates if more than 30 min into the incident |
| Post-mortem owner | primary on-call | Drives the 5-business-day post-mortem |

### 7.8 Expected RTO summary

| Step | Target | Aspirational |
|---|---|---|
| Detection | 2 min | 1 min |
| Decision | 5 min | 3 min |
| Execute | 20 min | 10 min |
| Post-failover validation | 5 min | 3 min |
| **Total RTO** | **~30 min** | **~15 min** |

The "aspirational" column is the post-drill target after 4
quarterly drills (§8). The "target" column is the v1 commitment.

## 8. Drill schedule

A failover capability that is never exercised is a failover
capability that doesn't exist when needed. Quarterly chaos
engineering drills are mandatory.

| Quarter | Drill | Success criteria |
|---|---|---|
| Q1 | Planned failover, US → secondary US-region (within-cloud) | RTO < 45 min; no data loss; clean failback |
| Q2 | Planned failover, MX → secondary MX-region | RTO < 45 min; SAT residency verified post-failover (data still in MX) |
| Q3 | Unplanned failover (network partition simulated via firewall rule) | RTO < 30 min; runbook followed without manual escalation |
| Q4 | Full region loss simulation (kill the primary cluster API server) | RTO < 30 min; failback drill completed within 4h window |

Each drill produces:
- Measured RTO from detection to first successful customer request.
- Measured RPO from last replicated WAL.
- Post-drill report identifying runbook gaps.
- Updated runbook reflecting lessons.

Drills happen during business hours with prior notice to
customers ("scheduled maintenance window"). Surprise drills are
NOT done — the goal is to test the runbook, not to surprise the
team.

## 9. Cost estimate

Per-region (over single-region baseline):

| Line | Active-passive (Option A) | Active-active (Option B) |
|---|---|---|
| Cluster compute (idle / active) | +50% (idle) | +80% (active) |
| Postgres replication network egress | +5% | +5% |
| Cross-region monitoring | +10% | +10% |
| Operational overhead (oncall, runbook, drills) | +1 oncall slot | +1 oncall slot + active-active complexity tax |
| **Total** | **~+50% over single-region** | **~+80% over single-region** |

Concrete starting numbers for a single-region cost of $X/mo:

- Active-passive in 2 regions: ~$1.5X/mo
- Active-passive in 3 regions (RFC 0020 MX + US + future EU):
  ~$2X/mo
- Active-active in 2 regions: ~$1.8X/mo

The cost premium is the price of "platform stays up when the cloud
provider doesn't." For a platform that processes Stripe events and
sends real customer email, this is a normal cost of doing business
above a certain customer-count threshold. RFC 0020 §10's
unit-economics analysis applies — the tipping point for "this is
worth it" is roughly the same point where MX-residency is worth it
(low double-digit production tenants).

Cost reduction levers if needed:
- The passive standby doesn't need symmetric capacity. A 50%-sized
  passive can be scaled up at failover time (with a cost in RTO —
  pod startup + HPA scale-up adds ~5-10 min).
- Read-replica hardware can double as the standby — instead of
  paying for a separate "passive" cluster, the existing read replica
  IS the passive standby.

## 10. Cross-RFC alignment

This section is non-optional. RFC 0020 (per-tenant data residency)
and RFC 0021 (this RFC) interact at every step.

### 10.1 Failover MUST honor residency boundaries

A SAT-bound tenant in MX-1 fails over to MX-2, never to US-1.
The failover topology is:

```
MX cluster pair: MX-primary  ⇄  MX-secondary
US cluster pair: US-primary  ⇄  US-secondary
EU cluster pair: EU-primary  ⇄  EU-secondary  (when EU exists)
```

Cross-region failover (MX → US) is not just operationally
inconvenient; it is a residency violation that creates federal
liability under LFPDPPP. The runbook (§7) must include the
explicit check: "What region am I failing over to? Is the source
region's residency-class compatible with the destination's
residency-class?" The check is also enforced in code — the
failover orchestration scripts refuse to scale up a deployment in
a wrong-jurisdiction region.

### 10.2 Each region needs its own standby

This means the cluster count from RFC 0020 doubles — MX-primary +
MX-secondary, US-primary + US-secondary, EU-primary + EU-secondary
when EU lands. The cost in RFC 0020 §10 understates this; the real
year-1 number for one MX-region pair is $1000-2000/mo, not the
$500-1000/mo that a single MX cluster costs.

### 10.3 Failover for the cross-region admin endpoints

The CROSS_REGION_ADMIN_ENABLED endpoints in RFC 0020 §6 (reap-stale,
billing rollups, fleet stats) need to keep working during a
single-region failover. Implementation: the admin namespace
deployment of nexus-api is itself active-passive across regions;
the surviving region's admin instance picks up the cross-region
work. This is a small extra concern but not a blocker.

### 10.4 Failover for the CDC audit topic

If RFC 0019's Kafka cluster is itself single-region, then a
regional outage takes the audit pipeline down. Recommendation:
RFC 0019's Kafka cluster should be multi-region from day one
(Confluent's MSK supports cross-AZ replication; cross-region is
configurable). This is captured in RFC 0019's open question Q1
(cluster ownership) and should be resolved in coordination with
this RFC.

### 10.5 Janua, Dhanam, Karafiel, Tezca, Enclii, PhyndCRM

Each ecosystem service needs its own failover story. The
cross-service contract for Selva: when Selva's primary region fails
over, Selva calls into the sibling services' regional endpoints
that match the new active region. If Janua doesn't have a regional
deployment story, a Selva failover that brings up the secondary
region but Janua is still in the old primary is half-failed-over.

This RFC doesn't solve the ecosystem-wide failover problem; it
flags it as a coordination concern. Recommend a sibling RFC per
service, anchored on the same regional topology this RFC
establishes.

---

*Sections written: §1–§10 complete. Less analytical-heavy than RFC*
*0020 because failover is a more constrained design space (the*
*active-passive vs active-active decision matrix is small and*
*well-trodden); more runbook-flavored as instructed. Open*
*coordination items live in §10 rather than a separate "open*
*questions" section because every multi-region failover question*
*is fundamentally a residency-coordination question with RFC 0020.*
