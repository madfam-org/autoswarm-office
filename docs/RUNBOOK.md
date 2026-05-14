# Operational Runbook -- AutoSwarm Office

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


**Audience**: On-call engineers, platform team, SREs
**Last updated**: 2026-03-13
**Related docs**: [ARCHITECTURE.md](./ARCHITECTURE.md) | [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) | [INTEGRATION.md](./INTEGRATION.md)

---

## Table of Contents

1. [Service Architecture](#service-architecture)
2. [Service Restart Procedures](#service-restart-procedures)
3. [Health Check Endpoints](#health-check-endpoints)
4. [Queue Depth Monitoring and Remediation](#queue-depth-monitoring-and-remediation)
5. [Worker Crash Recovery](#worker-crash-recovery)
6. [Redis Failover](#redis-failover)
7. [Database Failover](#database-failover)
8. [Approval Timeout Handling](#approval-timeout-handling)
9. [Scaling Procedures](#scaling-procedures)
10. [Alert Response Procedures](#alert-response-procedures)
11. [Useful Redis Commands](#useful-redis-commands)

---

## Service Architecture

AutoSwarm Office runs six application services backed by PostgreSQL and Redis.

```
                    +-----------------+
                    |   office-ui     |
                    | Next.js/Phaser  |
                    |    :4301        |
                    +--------+--------+
                             |
               +-------------+-------------+
               |                           |
        REST + WebSocket             Colyseus WS
               |                           |
      +--------v--------+       +---------v---------+
      |   nexus-api      |       |   colyseus        |
      |   FastAPI         |       |   Node.js         |
      |    :4300          |       |    :4303          |
      +--------+---------+       +-------------------+
               |
    +----------+----------+
    |                     |
+---v-------+      +-----v------+        +-------------+
| PostgreSQL |      |   Redis    | <----> |   workers   |
|   :5432    |      |   :6379    |        |  LangGraph  |
+------------+      +-----+------+        |  :4305      |
                          |               +-------------+
                    +-----v------+
                    |  gateway   |      +-------------+
                    |  OpenClaw  |      |   admin     |
                    |   :4304    |      |   :4302     |
                    +------------+      +-------------+
```

### Service Inventory

| Service | Port | Technology | Stateful | Purpose |
|---------|------|-----------|----------|---------|
| nexus-api | 4300 | FastAPI, SQLAlchemy | Yes (PostgreSQL, Redis) | Central REST API, WebSocket hub, task dispatch |
| office-ui | 4301 | Next.js 14, Phaser 3 | No | Landing page (`/`), demo mode (`/demo`), office (`/office`), approval UI |
| admin | 4302 | Next.js | No | Admin dashboard (reads from nexus-api) |
| colyseus | 4303 | Colyseus (Node.js) | Ephemeral (in-memory state) | Real-time game state synchronization |
| gateway | 4304 | Node.js (OpenClaw) | No | Cron-based heartbeat daemon, GitHub event scraper |
| workers | 4305 (health) | Python, LangGraph | No | Task execution with HITL interrupts |

### Infrastructure Dependencies

| Dependency | Port | Purpose | Configuration |
|-----------|------|---------|---------------|
| PostgreSQL 16 | 5432 | Persistent state (agents, tasks, approvals, ledger) | AOF enabled |
| Redis 7 | 6379 | Task stream, pub/sub, rate limiting, caching | `appendonly yes`, `maxmemory 256mb`, `allkeys-lru` |

### Data Flow

Tasks flow through the system as follows:

1. User dispatches a task via the UI, GitHub webhook, or Enclii deployment webhook triggers one
2. nexus-api creates a `SwarmTask` row in PostgreSQL (status: `queued`) and publishes to `autoswarm:task-stream` (Redis Streams)
3. A worker reads from the consumer group, PATCHes the task to `running`, and executes the LangGraph agent graph
4. For coding tasks: `plan()` creates a git worktree, `implement()` writes files (after permission check), `test()` runs pytest, `review()` self-reviews changes
5. If a tool invocation requires approval, `interrupt()` pauses execution and creates an `ApprovalRequest`
6. nexus-api broadcasts the approval request over WebSocket to connected clients
7. The tactician approves or denies via the Phaser UI
8. On approval: the worker commits and pushes to a feature branch (using `GITHUB_TOKEN` for credential auth), then creates a GitHub PR via `gh` CLI
9. For deployment tasks: `validate()` checks permissions, `deploy_gate()` requests HITL approval, `deploy()` triggers Enclii, `monitor()` checks deploy status
10. On completion: the worker PATCHes the task to `completed` or `failed` with result details
11. On timeout or exception: the worker PATCHes the task to `failed` with error details

---

## Service Restart Procedures

### Kubernetes (Production)

Restart a single service:

```bash
kubectl rollout restart deployment/<service> -n autoswarm
```

Restart all services:

```bash
for svc in nexus-api office-ui admin colyseus gateway workers; do
  kubectl rollout restart deployment/$svc -n autoswarm
done
```

Verify rollout completion:

```bash
kubectl rollout status deployment/<service> -n autoswarm --timeout=120s
```

### Docker Compose (Staging / CI)

Restart a single service:

```bash
docker compose -f infra/docker/docker-compose.yml restart <service>
```

Restart all application services:

```bash
docker compose -f infra/docker/docker-compose.yml restart nexus-api office-ui colyseus
```

Rebuild and restart (after code changes):

```bash
docker compose -f infra/docker/docker-compose.yml up -d --build <service>
```

### Local Development

Start all services:

```bash
make dev
```

Start only TypeScript services:

```bash
pnpm dev
```

Start only the worker process:

```bash
make worker
```

Start only infrastructure (PostgreSQL + Redis):

```bash
make docker-dev
```

### Restart Order

When restarting multiple services after an outage, follow this order to respect dependencies:

1. PostgreSQL (wait for healthcheck: `pg_isready`)
2. Redis (wait for healthcheck: `redis-cli ping`)
3. nexus-api (wait for `/api/v1/health/ready` to return 200)
4. colyseus, gateway, workers, admin, office-ui (can start in parallel)

---

## Health Check Endpoints

### Summary Table

| Service | Endpoint | Method | Expected | Purpose |
|---------|----------|--------|----------|---------|
| nexus-api | `/api/v1/health/health` | GET | 200 | Liveness probe |
| nexus-api | `/api/v1/health/ready` | GET | 200 (503 if degraded) | Readiness probe (checks DB + Redis) |
| nexus-api | `/api/v1/health/detail` | GET | 200 with pool metrics | Deep health (checks DB + Redis + Colyseus) |
| nexus-api | `/api/v1/health/queue-stats` | GET | 200 with queue statistics | Stream length, DLQ, consumer groups |
| nexus-api | `/metrics` | GET | 200 | Prometheus metrics (via `prometheus-fastapi-instrumentator`) |
| colyseus | `:4303/health` | GET | 200 `{"status":"healthy"}` | Liveness probe |
| gateway | `:4304/health` | GET | 200 with heartbeat stats | Liveness + heartbeat telemetry |
| gateway | `:4304/metrics` | GET | 200 | Prometheus metrics |
| workers | `:4305/health` | GET | 200 with task stats | Worker status, queue connection, task counts |
| workers | `:4305/metrics` | GET | 200 | Prometheus metrics (via `prometheus_client`) |

### Kubernetes Probe Configuration

nexus-api uses HTTP probes (defined in `infra/k8s/production/nexus-api.yaml`):

- **Liveness**: `GET /api/v1/health/health` every 30s, 5s timeout, 3 failures to restart
- **Readiness**: `GET /api/v1/health/health` every 15s, 5s timeout, 3 failures to remove from service

### Quick Health Verification

Check all services from inside the cluster:

```bash
# nexus-api
curl -sf http://nexus-api:4300/api/v1/health/ready | jq .

# colyseus
curl -sf http://colyseus:4303/health | jq .

# gateway
curl -sf http://gateway:4304/health | jq .

# workers (from within the pod or via port-forward)
kubectl port-forward deploy/workers 4305:4305 -n autoswarm &
curl -sf http://localhost:4305/health | jq .
```

### nexus-api `/ready` Response Interpretation

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

- `"status": "ready"` -- all dependencies healthy, 200 returned
- `"status": "degraded"` -- at least one dependency unavailable, 503 returned
- Check the `checks` object to identify which dependency is failing

### nexus-api `/detail` Response Interpretation

Extends `/ready` with Colyseus connectivity and Redis pool metrics:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "service": "nexus-api",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "colyseus": "ok"
  },
  "redis_pool": { ... }
}
```

### Workers `/health` Response Interpretation

```json
{
  "status": "healthy",
  "service": "worker",
  "current_task": null,
  "current_graph_type": null,
  "last_completed_at": 1710300000.0,
  "tasks_processed": 42,
  "tasks_failed": 1,
  "queue_connected": true,
  "uptime_seconds": 3600.0
}
```

- `current_task` is non-null when the worker is actively processing
- `queue_connected: false` indicates the worker lost its Redis connection
- Compare `tasks_failed` across checks to detect a rising error rate

---

## Queue Depth Monitoring and Remediation

### Checking Queue Depth

**Redis Streams (primary queue)**:

```bash
# Total messages in the stream (including delivered but unacknowledged)
redis-cli XLEN autoswarm:task-stream

# Pending messages by consumer group (unacknowledged)
redis-cli XPENDING autoswarm:task-stream autoswarm-workers

# Detailed pending per consumer (shows idle time)
redis-cli XPENDING autoswarm:task-stream autoswarm-workers - + 10

# Dead letter queue depth
redis-cli XLEN autoswarm:task-dlq
```

**API endpoint** (aggregated view):

```bash
curl -sf http://nexus-api:4300/api/v1/health/queue-stats | jq .
```

Example response:

```json
{
  "stream_length": 12,
  "dlq_depth": 0,
  "consumer_groups": [
    {
      "name": "autoswarm-workers",
      "consumers": 2,
      "pending": 3,
      "last_delivered_id": "1710300000000-0"
    }
  ],
  "redis_pool": { ... }
}
```

### Remediation Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| `stream_length` | > 25 | > 50 | Scale workers |
| `dlq_depth` | > 0 | > 10 | Inspect DLQ, fix root cause |
| `pending` per consumer | > 10 | > 25 | Check for stalled consumers |

### Scaling Workers for High Queue Depth

When `stream_length` exceeds 50 or is growing faster than workers can process:

```bash
# Manual scale (K8s)
kubectl scale deployment/workers --replicas=5 -n autoswarm

# Verify scale-up
kubectl get pods -l app.kubernetes.io/name=workers -n autoswarm

# Monitor queue draining
watch -n 5 'redis-cli XLEN autoswarm:task-stream'
```

The workers HPA (`infra/k8s/production/hpa.yaml`) scales from 1 to 5 replicas at 70% CPU. If the queue is deep but CPU is low (I/O-bound tasks waiting on LLM providers), manual scaling is necessary.

After the backlog clears, scale back down:

```bash
kubectl scale deployment/workers --replicas=1 -n autoswarm
```

---

## Worker Crash Recovery

### Automatic Recovery

Workers use Redis Streams consumer groups. When a worker crashes:

- Messages it was processing remain in the Pending Entries List (PEL)
- On startup, workers run `XAUTOCLAIM` to reclaim stalled messages from dead consumers
- No manual intervention is required for normal crash-recovery cycles

### Manual Stale Message Recovery

If messages are stuck (e.g., all workers crashed simultaneously and none have restarted):

```bash
# View stalled messages (idle > 60 seconds)
redis-cli XPENDING autoswarm:task-stream autoswarm-workers - + 10

# Manually claim stalled messages for a specific consumer
# 60000 = minimum idle time in milliseconds (60s)
redis-cli XAUTOCLAIM autoswarm:task-stream autoswarm-workers <consumer-name> 60000 0-0
```

Replace `<consumer-name>` with the name of a running worker consumer (typically the pod hostname).

### Finding Active Consumers

```bash
# List all consumers in the group
redis-cli XINFO CONSUMERS autoswarm:task-stream autoswarm-workers
```

This returns each consumer's name, pending count, and idle time. Consumers with very high idle times and pending messages are likely dead.

### Dead Consumer Cleanup

Remove a dead consumer that will not restart:

```bash
# First, claim its pending messages to another consumer
redis-cli XAUTOCLAIM autoswarm:task-stream autoswarm-workers <alive-consumer> 0 0-0

# Then delete the dead consumer
redis-cli XGROUP DELCONSUMER autoswarm:task-stream autoswarm-workers <dead-consumer>
```

### DLQ Inspection

Messages that fail repeatedly are moved to the dead letter queue:

```bash
# View DLQ entries
redis-cli XRANGE autoswarm:task-dlq - + COUNT 10

# View a specific DLQ entry's fields
redis-cli XRANGE autoswarm:task-dlq <message-id> <message-id>
```

To reprocess a DLQ entry, extract the task payload and re-dispatch via the API:

```bash
curl -X POST http://nexus-api:4300/api/v1/swarms/dispatch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"description": "...", "graph_type": "default"}'
```

To clear the DLQ after investigation:

```bash
# Remove specific entries
redis-cli XDEL autoswarm:task-dlq <message-id>

# Trim the entire DLQ (use with caution)
redis-cli XTRIM autoswarm:task-dlq MAXLEN 0
```

---

## Redis Failover

### Managed Redis (Recommended for Production)

When using AWS ElastiCache or GCP Memorystore:

- Failover is automatic with replica promotion
- Application reconnection is handled by the Redis client library
- No operator action required beyond monitoring for failover completion

### Self-Hosted Redis

Use Redis Sentinel or Redis Cluster for high availability:

- Sentinel monitors the primary and promotes a replica on failure
- Ensure `REDIS_URL` uses a Sentinel-aware connection string
- Workers and nexus-api will reconnect automatically after a brief interruption

### Impact of Redis Loss

| Capability | Impact | Recovery |
|-----------|--------|----------|
| Task stream | New tasks cannot be enqueued or dequeued | Tasks persist as `pending` in PostgreSQL; re-enqueue after Redis recovers |
| Pub/sub (approval events) | Real-time approval notifications stop | Workers fall back to polling PostgreSQL for approval status changes |
| Rate limiting | Rate limits not enforced | Middleware degrades gracefully; requests pass through |
| Caching | Cache misses; slightly higher DB load | Self-healing on reconnect |
| Colyseus (Redis DB 1) | Game state sync may degrade | Colyseus recovers on reconnect; ephemeral state rebuilt from API |

### Recovery Steps

```bash
# 1. Verify Redis is down
redis-cli -h <redis-host> PING

# 2. Restart Redis
kubectl rollout restart deployment/redis -n autoswarm
# or
docker compose -f infra/docker/docker-compose.yml restart redis

# 3. Wait for healthcheck
kubectl wait --for=condition=ready pod -l app=redis -n autoswarm --timeout=60s

# 4. Verify connectivity
redis-cli -h <redis-host> PING

# 5. Re-enqueue pending tasks from PostgreSQL
# Tasks with status 'queued' or 'in_progress' at the time of Redis failure
# need re-dispatch. Use the nexus-api endpoint or direct SQL:
psql "$DATABASE_URL" -c "
  SELECT id, description, graph_type
  FROM swarm_tasks
  WHERE status IN ('queued', 'in_progress')
  ORDER BY created_at;
"

# 6. Restart workers to reconnect
kubectl rollout restart deployment/workers -n autoswarm
```

---

## Database Failover

### Backup Operations

```bash
# Create a backup
make db-backup

# Restore from a backup
make db-restore BACKUP_FILE=./backups/autoswarm_20260313_020000.dump

# Verify a backup's integrity
make db-verify-backup BACKUP_FILE=./backups/autoswarm_20260313_020000.dump
```

Automated backups run daily at 02:00 UTC via a Kubernetes CronJob
(`infra/k8s/production/backup-cronjob.yaml`). Retention: 30 daily, 12 weekly.

### Check Migration State

```bash
uv run --directory apps/nexus-api alembic current
```

Expected output includes the latest migration revision. If the revision is behind
the codebase, run migrations:

```bash
uv run --directory apps/nexus-api alembic upgrade head
```

### Recovery Procedure

See [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) for full database loss scenarios.

Quick reference for single-database recovery:

```bash
# 1. Check if PostgreSQL is reachable
psql "$DATABASE_URL" -c "SELECT 1;"

# 2. If the instance is up but data is corrupt, restore from backup
make db-restore BACKUP_FILE=<path-to-dump>

# 3. Run migrations to ensure schema is current
make db-migrate

# 4. Verify table presence and row counts
make db-verify-backup BACKUP_FILE=<path-to-dump>

# 5. Restart services to clear stale connection pools
kubectl rollout restart deployment/nexus-api -n autoswarm
kubectl rollout restart deployment/workers -n autoswarm
kubectl rollout restart deployment/gateway -n autoswarm

# 6. Verify API health
curl -sf http://nexus-api:4300/api/v1/health/ready | jq .
```

### Connection Pool Exhaustion

Symptoms: nexus-api returns 500 errors, logs show `QueuePool limit reached` or
`connection pool exhausted`.

```bash
# Check for long-running transactions
psql "$DATABASE_URL" -c "
  SELECT pid, now() - xact_start AS duration, query
  FROM pg_stat_activity
  WHERE state = 'active' AND xact_start < now() - interval '5 minutes'
  ORDER BY duration DESC;
"

# Terminate long-running queries if necessary
psql "$DATABASE_URL" -c "SELECT pg_terminate_backend(<pid>);"

# Restart nexus-api to reset connection pools
kubectl rollout restart deployment/nexus-api -n autoswarm
```

---

## Approval Timeout Handling

Approval requests that remain in `pending` status indicate a tactician has not
responded. This can happen when no user is connected to the office UI or when
WebSocket delivery fails.

### Find Stale Approvals

```sql
SELECT id, agent_id, tool_name, created_at,
       now() - created_at AS age
FROM approval_requests
WHERE status = 'pending'
  AND created_at < now() - interval '1 hour'
ORDER BY created_at;
```

### Auto-Deny Stale Approvals

Apply a blanket timeout denial for approvals older than 1 hour:

```sql
UPDATE approval_requests
SET status = 'denied',
    feedback = 'Auto-denied: timeout (>1 hour without response)'
WHERE status = 'pending'
  AND created_at < now() - interval '1 hour';
```

After denying stale approvals, the corresponding workers (if still waiting) will
receive the denial and abort their current task. If the workers have already
timed out, the associated `swarm_tasks` rows may also need cleanup:

```sql
UPDATE swarm_tasks
SET status = 'failed',
    error_message = 'Approval timed out'
WHERE status = 'in_progress'
  AND id IN (
    SELECT DISTINCT task_id
    FROM approval_requests
    WHERE status = 'denied'
      AND feedback LIKE 'Auto-denied: timeout%'
  );
```

---

## Scaling Procedures

### When to Scale

| Trigger | Metric | Threshold | Action |
|---------|--------|-----------|--------|
| High CPU | CPU utilization | > 70% sustained (5 min) | HPA handles automatically |
| Deep queue | `stream_length` | > 50 | Scale workers manually if CPU-based HPA has not triggered |
| High latency | p95 response time | > 500ms | Scale nexus-api |
| Memory pressure | Memory utilization | > 85% | Investigate leaks, then scale |

### HPA Configuration

HPA definitions are in `infra/k8s/production/hpa.yaml`:

| Service | Min Replicas | Max Replicas | CPU Target |
|---------|-------------|-------------|------------|
| nexus-api | 2 | 6 | 70% |
| office-ui | 2 | 4 | 70% |
| workers | 1 | 5 | 70% |

### Manual Scaling

```bash
# Scale nexus-api
kubectl scale deployment/nexus-api --replicas=4 -n autoswarm

# Scale workers
kubectl scale deployment/workers --replicas=5 -n autoswarm

# Scale office-ui
kubectl scale deployment/office-ui --replicas=3 -n autoswarm

# Verify
kubectl get pods -n autoswarm -l app.kubernetes.io/part-of=autoswarm-office
```

### Colyseus Scaling

Colyseus is a stateful WebSocket server with in-memory game state. It runs as a
**single instance** and cannot be horizontally scaled without session affinity and
a shared state backend. See `docs/COLYSEUS_SCALING.md` for architectural options.

For now, the PodDisruptionBudget (`infra/k8s/production/pdb.yaml`) ensures at
least 1 colyseus pod remains available during rolling updates.

### Pod Disruption Budgets

| Service | `minAvailable` |
|---------|---------------|
| nexus-api | 1 |
| office-ui | 1 |
| colyseus | 1 |

---

## Alert Response Procedures

### High Queue Depth

**Alert**: `stream_length > 50` or `pending > 25`

1. Check worker health: `curl -sf http://workers:4305/health | jq .`
2. If `queue_connected: false`, workers lost Redis connection. Restart workers.
3. If workers are healthy but slow, check LLM provider latency and availability.
4. Scale workers: `kubectl scale deployment/workers --replicas=5 -n autoswarm`
5. Monitor queue drain: `watch -n 5 'redis-cli XLEN autoswarm:task-stream'`
6. Scale back down after the backlog clears.

### Redis Circuit Breaker Open

**Alert**: nexus-api logs `Redis readiness check failed` or `/ready` returns `"redis": "unavailable"`

1. Check Redis connectivity: `redis-cli -h <redis-host> PING`
2. Check Redis memory: `redis-cli INFO memory | grep used_memory_human`
3. If Redis is OOM (`maxmemory` reached), check for key bloat:
   `redis-cli INFO keyspace`
4. Restart Redis if unresponsive.
5. Restart nexus-api and workers after Redis recovers.

### Database Connection Pool Exhausted

**Alert**: nexus-api returns 503, logs show pool errors

1. Check for long-running transactions (see [Database Failover](#database-failover)).
2. Terminate stuck queries if safe.
3. Restart nexus-api to reset connection pools.
4. If recurring, increase pool size in nexus-api configuration.

### Worker Task Timeout

**Alert**: Worker health shows `current_task` with no change for > 10 minutes

1. Check LLM provider health (the provider URL is in worker environment variables).
2. Inspect the DLQ for repeated failures: `redis-cli XRANGE autoswarm:task-dlq - + COUNT 5`
3. Check worker logs: `kubectl logs deploy/workers -n autoswarm --tail=200`
4. If the worker is truly stuck, restart it:
   `kubectl rollout restart deployment/workers -n autoswarm`
5. Stalled messages will be auto-claimed by the restarted worker.

### Sentry Error Spike

**Alert**: Sentry reports elevated error rate for any service

1. Check the Sentry dashboard for the specific error and affected service.
2. Correlate with recent deployments:
   `kubectl rollout history deployment/<service> -n autoswarm`
3. If the error was introduced by a recent deployment, roll back:
   `kubectl rollout undo deployment/<service> -n autoswarm`
4. If not deployment-related, investigate the root cause using logs and traces.

### Colyseus Disconnection Cascade

**Alert**: Multiple clients report disconnection, office-ui shows no agents

1. Check colyseus health: `curl -sf http://colyseus:4303/health`
2. If unresponsive, restart: `kubectl rollout restart deployment/colyseus -n autoswarm`
3. Clients will automatically reconnect and rebuild state from the API.
4. Check for OOM: `kubectl describe pod -l app.kubernetes.io/name=colyseus -n autoswarm`
   (look for `OOMKilled` in last termination reason).

---

## Useful Redis Commands

### Connection and General

```bash
# Test connectivity
redis-cli PING

# Server info summary
redis-cli INFO server | grep -E "redis_version|uptime"

# Memory usage
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|mem_fragmentation_ratio"

# Keyspace summary
redis-cli INFO keyspace

# Connected clients
redis-cli INFO clients | grep connected_clients

# Slow log (last 10 slow commands)
redis-cli SLOWLOG GET 10
```

### Task Stream Operations

```bash
# Stream length (total messages)
redis-cli XLEN autoswarm:task-stream

# Stream info (first/last entry, groups)
redis-cli XINFO STREAM autoswarm:task-stream

# Consumer group info
redis-cli XINFO GROUPS autoswarm:task-stream

# Per-consumer details (name, pending, idle time)
redis-cli XINFO CONSUMERS autoswarm:task-stream autoswarm-workers

# Read the 5 most recent messages
redis-cli XREVRANGE autoswarm:task-stream + - COUNT 5

# Read the 5 oldest messages
redis-cli XRANGE autoswarm:task-stream - + COUNT 5

# Pending entry list summary
redis-cli XPENDING autoswarm:task-stream autoswarm-workers

# Detailed pending (with consumer name and idle time)
redis-cli XPENDING autoswarm:task-stream autoswarm-workers - + 10
```

### Dead Letter Queue

```bash
# DLQ depth
redis-cli XLEN autoswarm:task-dlq

# View DLQ entries
redis-cli XRANGE autoswarm:task-dlq - + COUNT 10

# Delete a specific DLQ entry after investigation
redis-cli XDEL autoswarm:task-dlq <message-id>

# Clear entire DLQ (use with caution)
redis-cli XTRIM autoswarm:task-dlq MAXLEN 0
```

### Pub/Sub Debugging

```bash
# List active pub/sub channels
redis-cli PUBSUB CHANNELS

# Subscribe to a channel for debugging (blocks terminal)
redis-cli SUBSCRIBE autoswarm:approvals

# Count subscribers on a channel
redis-cli PUBSUB NUMSUB autoswarm:approvals
```

### Rate Limiting Keys

```bash
# Find rate limit keys (pattern depends on middleware implementation)
redis-cli KEYS "ratelimit:*"

# Check TTL on a rate limit key
redis-cli TTL "ratelimit:<key>"

# Clear all rate limit state (use during incidents if rate limiting is blocking recovery)
redis-cli EVAL "for _,k in pairs(redis.call('KEYS','ratelimit:*')) do redis.call('DEL',k) end" 0
```

### Maintenance

```bash
# Trigger an AOF rewrite (reduces file size)
redis-cli BGREWRITEAOF

# Check AOF rewrite status
redis-cli INFO persistence | grep aof

# Flush a specific database (DB 0 = nexus-api, DB 1 = colyseus)
# WARNING: destroys all data in that database
redis-cli -n 0 FLUSHDB
redis-cli -n 1 FLUSHDB
```

---

## Running Multiple Workers

### How Consumer Group Sharing Works

All worker instances share the Redis Streams consumer group `autoswarm-workers`.
Each worker registers as a unique consumer (hostname + PID). Redis guarantees
that each stream message is delivered to exactly one consumer within the group,
providing automatic work distribution.

### Concurrency Within a Single Worker

Each worker process runs up to `MAX_CONCURRENT_TASKS` (default 3) tasks in
parallel using an `asyncio.Semaphore`. The worker reads `count=MAX_CONCURRENT_TASKS`
messages per stream read and processes them concurrently.

Set this via the `MAX_CONCURRENT_TASKS` environment variable:

```bash
MAX_CONCURRENT_TASKS=5  # Allow 5 concurrent tasks per worker
```

### Starting Multiple Workers

```bash
# K8s: scale the deployment
kubectl scale deployment/workers --replicas=3 -n autoswarm

# Local: run multiple processes
MAX_CONCURRENT_TASKS=3 uv run python -m autoswarm_workers &
MAX_CONCURRENT_TASKS=3 uv run python -m autoswarm_workers &
```

### Verifying Consumer Group Membership

```bash
# List all consumers and their status
redis-cli XINFO CONSUMERS autoswarm:task-stream autoswarm-workers
```

Each consumer entry shows:
- **name**: unique consumer ID (hostname + PID)
- **pending**: number of messages currently being processed
- **idle**: milliseconds since last interaction

### Graceful Shutdown

Workers drain active tasks on shutdown. When receiving SIGTERM or SIGINT:
1. The worker stops reading new messages from the stream.
2. Active tasks continue until completion (or graph timeout).
3. The process exits after all active tasks finish.

Unacknowledged messages from a killed worker (SIGKILL) are reclaimed by other
workers via `XAUTOCLAIM` on their next startup.

### Worktree Cleanup on Startup

Workers automatically clean up stale worktrees (older than `WORKTREE_STALE_HOURS`,
default 24h) from `REPO_BASE_PATH` on startup. This prevents disk exhaustion from
accumulated worktrees after crashes.

```bash
# Manual cleanup
make worktree-cleanup STALE_HOURS=12
```

### Stale Task Reaping

Workers periodically call `POST /api/v1/swarms/tasks/reap-stale` to auto-fail
tasks stuck in `queued` or `pending` status for more than 1 hour.

### DLQ Monitoring

Check the DLQ depth via the health endpoint:

```bash
curl -sf http://nexus-api:4300/api/v1/health/dlq-stats | jq .
```

A non-zero `depth` indicates tasks that failed after 3 retries. Investigate the
`recent` entries to determine root cause before re-dispatching.

---

## Appendix: Environment Variables

Key environment variables referenced in this runbook. Secrets are stored in the
`autoswarm-secrets` Kubernetes Secret. Non-secret configuration is in the
`autoswarm-config` ConfigMap (`infra/k8s/production/configmap.yaml`).

| Variable | Service | Description |
|----------|---------|-------------|
| `DATABASE_URL` | nexus-api, workers | PostgreSQL connection string |
| `REDIS_URL` | nexus-api, workers, colyseus | Redis connection string (DB 0 for nexus-api/workers, DB 1 for colyseus) |
| `NEXUS_API_PORT` | nexus-api | HTTP port (default: 4300) |
| `COLYSEUS_PORT` | colyseus | WebSocket port (default: 4303) |
| `GATEWAY_HEALTH_PORT` | gateway | Health server port (default: 4304) |
| `HEARTBEAT_CRON` | gateway | Cron schedule for heartbeat ticks (default: `*/30 * * * *`) |
| `SECRET_KEY` | nexus-api, workers | Application secret for token signing |
| `JANUA_ISSUER_URL` | nexus-api, office-ui | Janua authentication issuer URL |
| `GITHUB_WEBHOOK_SECRET` | nexus-api | HMAC key for verifying GitHub webhook signatures |
| `GITHUB_TOKEN` | workers | PAT for git push credential helper and PR creation via `gh` CLI |
| `ENCLII_WEBHOOK_SECRET` | nexus-api | Bearer token for verifying Enclii deployment webhooks |
| `ENCLII_API_URL` | workers | Base URL of the Enclii deployment API |
| `ENCLII_DEPLOY_TOKEN` | workers | Bearer token for authenticating with Enclii deploy API |
| `PORKBUN_API_KEY` | workers | Porkbun registrar API key used by Selva DNS tools for domain inventory and nameserver operations |
| `PORKBUN_SECRET_KEY` | workers | Porkbun registrar secret key paired with `PORKBUN_API_KEY`; stored only in `autoswarm-secrets` |
| `ENVIRONMENT` | all | `development` / `production` |

---

## Appendix: File Locations

| File | Purpose |
|------|---------|
| `infra/docker/docker-compose.yml` | Full Docker Compose stack |
| `infra/docker/docker-compose.dev.yml` | Development-only (PostgreSQL + Redis) |
| `infra/k8s/production/hpa.yaml` | HorizontalPodAutoscaler definitions |
| `infra/k8s/production/pdb.yaml` | PodDisruptionBudget definitions |
| `infra/k8s/production/service-monitors.yaml` | Prometheus ServiceMonitor definitions |
| `infra/k8s/production/configmap.yaml` | Non-secret configuration |
| `infra/k8s/production/backup-cronjob.yaml` | Automated daily backup CronJob |
| `scripts/backup-postgres.sh` | Manual backup script |
| `scripts/restore-postgres.sh` | Manual restore script |
| `scripts/verify-backup.sh` | Backup integrity verification |
| `apps/nexus-api/nexus_api/routers/health.py` | Health and readiness endpoints |
| `apps/workers/autoswarm_workers/health.py` | Worker health server |
| `apps/gateway/src/index.ts` | Gateway health server |
| `apps/colyseus/src/index.ts` | Colyseus health endpoint |
