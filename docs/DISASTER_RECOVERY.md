# Disaster Recovery Plan -- AutoSwarm Office

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


## Overview

This document defines the disaster recovery (DR) procedures for the AutoSwarm
Office platform. It covers backup strategy, recovery procedures for common
failure scenarios, and verification steps to confirm successful recovery.

**Program gate:** Phase 0 item 0.5 in
[AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md) requires
a executed backup/restore drill with measured RTO/RPO before north-star Phase 1.

### Recovery Objectives

| Metric | Target | Notes |
|--------|--------|-------|
| **RTO** (Recovery Time Objective) | 1 hour | Time from incident detection to full service restoration |
| **RPO** (Recovery Point Objective) | 24 hours | Maximum acceptable data loss window |

### Service Inventory

| Service | Port | Stateful | Data Store |
|---------|------|----------|------------|
| nexus-api | 4300 | Yes | PostgreSQL (primary), Redis (queue) |
| office-ui | 4301 | No | N/A (static frontend) |
| admin | 4302 | No | Reads from nexus-api |
| colyseus | 4303 | Ephemeral | In-memory game state |
| gateway | 4304 | No | Reads/writes via nexus-api |
| workers | N/A | No | Reads from Redis queue, writes to PostgreSQL |

### Data Classification

| Data | Store | Criticality | Backup Required |
|------|-------|-------------|-----------------|
| Departments, agents, skills | PostgreSQL | High | Yes |
| Swarm tasks, approval requests | PostgreSQL | High | Yes |
| Compute token ledger | PostgreSQL | High | Yes |
| Alembic migration state | PostgreSQL | High | Yes (included in dump) |
| Task queue (in-flight) | Redis | Medium | No (reconstructable from DB) |
| Game state (player positions) | Colyseus memory | Low | No (ephemeral) |
| Chat messages | Colyseus memory | Low | No (ephemeral) |
| WebRTC sessions | Client-side | Low | No (ephemeral) |

---

## Backup Strategy

### Schedule

| Type | Schedule | Retention | Storage |
|------|----------|-----------|---------|
| Daily backup | 02:00 UTC every day | 30 days | Local PVC + S3 |
| Weekly backup | 02:00 UTC every Sunday | 12 weeks | S3 |
| Pre-migration backup | Before each Alembic migration | Until next successful backup | Local |

### Implementation

Backups are performed by a Kubernetes CronJob defined in
`infra/k8s/production/backup-cronjob.yaml`. The job uses `pg_dump` with
custom format (`--format=custom`) and maximum compression (`--compress=9`).

**Local scripts** (for development and manual operations):
- `scripts/backup-postgres.sh` -- Create a backup
- `scripts/restore-postgres.sh` -- Restore from a backup
- `scripts/verify-backup.sh` -- Validate backup integrity

### Backup Verification

Backups should be verified weekly. The `verify-backup.sh` script restores to a
temporary database, validates all expected tables are present, reports row
counts, and drops the temporary database on exit.

```bash
DATABASE_URL="postgresql://user:pass@localhost:5432/autoswarm" \
  ./scripts/verify-backup.sh ./backups/autoswarm_20260313_020000.dump
```

Expected output confirms these tables exist:
- `departments`
- `agents`
- `approval_requests`
- `swarm_tasks`
- `compute_token_ledger`
- `alembic_version`

---

## Recovery Scenarios

### Scenario 1: Database Loss

**Symptoms**: nexus-api returns 500 errors, database connection timeouts, data
queries fail.

**Impact**: All stateful operations fail. Workers cannot dequeue tasks. Gateway
cannot create SwarmTasks. UI shows stale or no data.

**Recovery Procedure**:

1. **Assess the failure**. Determine whether the PostgreSQL instance is
   recoverable or requires a full restore.

   ```bash
   # Check if Postgres is reachable
   psql "${DATABASE_URL}" -c "SELECT 1;"
   ```

2. **If the instance is recoverable** (e.g., crashed but storage intact):

   ```bash
   # Kubernetes: restart the pod
   kubectl -n autoswarm rollout restart deployment/postgres

   # Verify connectivity
   kubectl -n autoswarm exec -it deploy/nexus-api -- \
     python -c "from sqlalchemy import create_engine; e = create_engine('${DATABASE_URL}'); e.connect()"
   ```

3. **If data is lost**, restore from the most recent backup:

   ```bash
   # List available backups (local)
   ls -lt backups/autoswarm_*.dump | head -5

   # List available backups (S3)
   aws s3 ls "s3://${S3_BUCKET}/autoswarm/daily/" --recursive | sort -r | head -5

   # Download from S3 if needed
   aws s3 cp "s3://${S3_BUCKET}/autoswarm/daily/autoswarm_YYYYMMDD_HHMMSS.dump" ./restore.dump

   # Restore
   DATABASE_URL="postgresql://user:pass@host:5432/autoswarm" \
     ./scripts/restore-postgres.sh ./restore.dump
   ```

4. **Verify the restore**:

   ```bash
   DATABASE_URL="postgresql://user:pass@host:5432/autoswarm" \
     ./scripts/verify-backup.sh ./restore.dump
   ```

5. **Restart dependent services** to clear stale connections:

   ```bash
   kubectl -n autoswarm rollout restart deployment/nexus-api
   kubectl -n autoswarm rollout restart deployment/workers
   kubectl -n autoswarm rollout restart deployment/gateway
   ```

6. **Verify service health**:

   ```bash
   curl -f http://nexus-api:4300/health
   ```

**Estimated Recovery Time**: 15-30 minutes.

---

### Scenario 2: Redis Loss

**Symptoms**: Workers idle despite pending tasks, task dispatch returns success
but tasks do not execute, WebSocket approval events not firing.

**Impact**: Task queue is lost. In-flight tasks that were dequeued but not
completed may need re-dispatch. No persistent data loss since task records exist
in PostgreSQL.

**Recovery Procedure**:

1. **Restart Redis**:

   ```bash
   # Kubernetes
   kubectl -n autoswarm rollout restart deployment/redis

   # Docker (development)
   docker compose restart redis
   ```

2. **Re-enqueue pending tasks** from the database. Tasks in `queued` or
   `in_progress` status should be re-enqueued:

   ```bash
   # Connect to nexus-api and re-enqueue
   kubectl -n autoswarm exec -it deploy/nexus-api -- python -c "
   import asyncio, redis.asyncio as redis, json
   from sqlalchemy import select, text

   async def reenqueue():
       r = redis.from_url('redis://redis:6379')
       # Fetch tasks that were queued or in_progress
       # Re-add to autoswarm:task-stream
       print('Re-enqueue via API or direct Redis XADD')

   asyncio.run(reenqueue())
   "
   ```

   Alternatively, re-dispatch tasks through the API:

   ```bash
   curl -X POST http://nexus-api:4300/api/v1/swarms/dispatch \
     -H "Content-Type: application/json" \
     -d '{"description": "...", "graph_type": "default"}'
   ```

3. **Restart workers** to reconnect to Redis:

   ```bash
   kubectl -n autoswarm rollout restart deployment/workers
   ```

4. **Verify the queue**:

   ```bash
   kubectl -n autoswarm exec -it deploy/redis -- redis-cli XLEN autoswarm:task-stream
   ```

**Estimated Recovery Time**: 5-15 minutes.

---

### Scenario 3: Full Cluster Failure

**Symptoms**: All services unreachable. Kubernetes cluster is down or destroyed.

**Impact**: Complete service outage.

**Recovery Procedure**:

1. **Provision infrastructure**. Use the existing IaC definitions:

   ```bash
   # Apply Kubernetes manifests
   kubectl apply -k infra/k8s/production/

   # Or use ArgoCD if configured
   argocd app sync autoswarm-office
   ```

2. **Verify secrets** are available. The `autoswarm-secrets` Secret must contain:
   - `database-url` -- PostgreSQL connection string
   - `redis-url` -- Redis connection string
   - `janua-issuer-url` -- Janua authentication issuer
   - `github-webhook-secret` -- GitHub webhook HMAC key

3. **Restore the database** from the most recent S3 backup:

   ```bash
   # Download the latest backup
   LATEST=$(aws s3 ls "s3://${S3_BUCKET}/autoswarm/daily/" | sort -r | head -1 | awk '{print $4}')
   aws s3 cp "s3://${S3_BUCKET}/autoswarm/daily/${LATEST}" ./restore.dump

   # Wait for PostgreSQL to be ready
   kubectl -n autoswarm wait --for=condition=ready pod -l app=postgres --timeout=300s

   # Restore
   DATABASE_URL="postgresql://..." ./scripts/restore-postgres.sh ./restore.dump --force
   ```

4. **Run database migrations** to ensure schema matches the deployed code:

   ```bash
   cd apps/nexus-api
   uv run alembic upgrade head
   ```

5. **Seed reference data** if the backup is empty or missing departments:

   ```bash
   cd apps/nexus-api
   uv run python ../../scripts/seed-agents.py
   ```

6. **Deploy all services**:

   ```bash
   kubectl -n autoswarm rollout status deployment/nexus-api --timeout=120s
   kubectl -n autoswarm rollout status deployment/office-ui --timeout=120s
   kubectl -n autoswarm rollout status deployment/colyseus --timeout=120s
   kubectl -n autoswarm rollout status deployment/admin --timeout=120s
   kubectl -n autoswarm rollout status deployment/gateway --timeout=120s
   kubectl -n autoswarm rollout status deployment/workers --timeout=120s
   ```

7. **Verify all services**:

   ```bash
   # API health
   curl -f http://nexus-api:4300/health

   # UI loads
   curl -f -o /dev/null -w "%{http_code}" http://office-ui:4301/

   # Colyseus accepts WebSocket
   curl -f http://colyseus:4303/health

   # Redis queue accessible
   kubectl -n autoswarm exec -it deploy/redis -- redis-cli PING
   ```

8. **Verify end-to-end functionality**:
   - Log into the office-ui through Janua
   - Confirm agents appear on the map
   - Dispatch a test task and verify it completes
   - Verify GitHub webhook endpoint responds

**Estimated Recovery Time**: 30-60 minutes.

---

### Scenario 4: Single Service Failure

**Symptoms**: One service returns errors or is unreachable while others function.

**Recovery Procedure**:

1. **Identify the failing service**:

   ```bash
   kubectl -n autoswarm get pods
   kubectl -n autoswarm describe pod <failing-pod>
   kubectl -n autoswarm logs <failing-pod> --tail=100
   ```

2. **Restart the service**:

   ```bash
   kubectl -n autoswarm rollout restart deployment/<service-name>
   ```

3. **If the pod is in CrashLoopBackOff**, check for:
   - Missing environment variables or secrets
   - Database connectivity issues
   - Port conflicts (see port assignments in CLAUDE.md)
   - OOM kills (check `kubectl describe pod` for `OOMKilled`)

4. **Verify recovery**:

   ```bash
   kubectl -n autoswarm rollout status deployment/<service-name> --timeout=120s
   ```

**Estimated Recovery Time**: 5-10 minutes.

---

## Verification Checklist

After any recovery operation, confirm each item:

- [ ] PostgreSQL is accessible and contains expected tables
- [ ] `alembic_version` matches the latest migration (`0004_add_task_queue_tracking`)
- [ ] nexus-api `/health` returns 200
- [ ] office-ui loads in browser
- [ ] Colyseus accepts WebSocket connections
- [ ] Redis is accessible and `PING` returns `PONG`
- [ ] Workers are running and processing tasks from `autoswarm:task-stream`
- [ ] Gateway heartbeat service is operational
- [ ] Janua authentication flow works (login and token validation)
- [ ] A test task can be dispatched and completed end-to-end

---

## Preventive Measures

### Monitoring and Alerting

| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Backup CronJob success | Daily | Any failure triggers alert |
| Database disk usage | 5 min | > 80% capacity |
| Redis memory usage | 5 min | > 75% maxmemory |
| Pod restart count | 1 min | > 3 restarts in 10 min |
| API error rate | 1 min | > 5% of requests return 5xx |
| Task queue depth | 1 min | > 100 pending tasks |

### Regular Testing

| Activity | Frequency | Owner |
|----------|-----------|-------|
| Backup verification (`verify-backup.sh`) | Weekly | On-call engineer |
| Full restore drill | Quarterly | Platform team |
| Failover simulation | Semi-annually | Platform team |
| DR plan review and update | Annually | Engineering lead |

---

## Contact and Escalation

| Level | Condition | Action |
|-------|-----------|--------|
| L1 | Single service restart resolves | On-call engineer handles |
| L2 | Database restore required | Escalate to platform team lead |
| L3 | Full cluster recovery | Escalate to engineering lead + infrastructure team |

### Escalation Timeline

| Time Since Incident | Action |
|---------------------|--------|
| 0 min | On-call engineer notified via PagerDuty |
| 15 min | If not acknowledged, escalate to backup on-call |
| 30 min | If not resolved, escalate to platform team lead |
| 60 min | If RTO at risk, escalate to engineering lead |

---

## Appendix: File Locations

| File | Purpose |
|------|---------|
| `scripts/backup-postgres.sh` | Create PostgreSQL backup (local + S3) |
| `scripts/restore-postgres.sh` | Restore PostgreSQL from backup |
| `scripts/verify-backup.sh` | Validate backup integrity |
| `infra/k8s/production/backup-cronjob.yaml` | Kubernetes CronJob for automated daily backups |
| `apps/nexus-api/alembic/` | Database migration definitions |
| `scripts/seed-agents.py` | Seed departments and agents |

## Appendix: Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `DATABASE_URL` | All DB operations | PostgreSQL connection string |
| `S3_BUCKET` | Remote backups | S3 bucket name for backup storage |
| `BACKUP_DIR` | Local backups | Local directory for backup files (default: `./backups`) |
| `RETENTION_DAILY` | Rotation | Daily backups to keep (default: 30) |
| `RETENTION_WEEKLY` | Rotation | Weekly backups to keep (default: 12) |
