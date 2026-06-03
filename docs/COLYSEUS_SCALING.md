# Colyseus Scaling Guide

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


This document covers the current capacity profile of the Selva Office Colyseus
server, explains why it runs as a single instance today, and outlines a progressive
scaling path for increasing concurrent user counts.

---

## Current Capacity

A single Colyseus process on port 4303 serves the `office` room.

| Resource | Value | Source |
|---|---|---|
| Departments | 4 (`engineering`, `research`, `crm`, `support`) | `OfficeRoom.DEFAULT_DEPARTMENTS` |
| Max agents per department | 4-6 (6 for engineering, 4 for others) | `DepartmentSchema.maxAgents` |
| Chat message buffer | 50 messages (FIFO eviction) | `chat.ts MAX_MESSAGES` |
| WebSocket max payload | 1 MB | `index.ts WebSocketTransport` |
| Proximity detection | 5 Hz loop, 200 px radius | `proximity.ts startProximityLoop` |
| Max WebRTC peers per player | 6 | `proximity.ts MAX_PEERS` |

### Practical Limits

- **50-100 concurrent players** per process before serialization latency becomes
  noticeable. Colyseus serializes the full `OfficeStateSchema` (departments, agents,
  players, chat) on every state patch. Larger player counts increase per-tick cost
  quadratically for the proximity loop (O(n^2) distance checks).
- **CPU-bound**: state serialization and proximity calculation are the main bottlenecks.
  Network bandwidth is rarely the constraint at this scale.
- **Memory**: each `TacticianSchema` instance is small (~200 bytes serialized). The
  state fits comfortably in memory even at 100+ players.

---

## Why Single Instance (Current State)

Colyseus rooms are **in-memory, single-process** constructs. The `OfficeRoom` holds:

1. **Department and agent state** synced from nexus-api at room creation, then updated
   in real time via a Redis `selva:agent-status` subscription.
2. **Player state** (`MapSchema<TacticianSchema>`) tracking position, direction, and
   avatar config for every connected client.
3. **Chat history** (`ArraySchema<ChatMessageSchema>`) with the last 50 messages.
4. **Pending approval count** incremented when agents enter `waiting_approval` status.

All connected players must see the same world state. This state is not replicated
across processes. Running a second Colyseus process would create a second, independent
room with its own state -- players in different processes would not see each other.

Splitting into multiple rooms requires explicit state synchronization infrastructure
that does not exist today.

---

## Scaling Options

### Option 1: Room-per-Organization (Recommended First Step)

**Concept**: each organization gets its own `OfficeRoom` instance within the same
Colyseus process. Organizations are naturally isolated -- agents, departments, and
tasks belong to a single `org_id`.

**How it works**:

1. The client extracts `org_id` from the Janua JWT (the `org_id` claim).
2. The client joins room `office-{org_id}` instead of a generic `office` room.
3. `OfficeRoom.onCreate` receives `org_id` in the room options and scopes its
   nexus-api fetch to that organization's departments and agents.
4. Redis subscription channel becomes `selva:agent-status:{org_id}`.

**Capacity**: ~50-100 concurrent users per organization, limited by the per-room
serialization cost. Total server capacity scales with the number of active orgs
because idle rooms consume negligible resources.

**Effort**: Low. Changes are limited to room creation/joining logic and the API
fetch filter. No new infrastructure required.

**Limitations**: all rooms still run on a single Node.js process. A very active org
with 100+ users will still hit the single-process ceiling.

### Option 2: Redis Presence (Medium Scale)

**Concept**: use `@colyseus/redis-presence` and `@colyseus/redis-driver` to distribute
rooms across multiple Colyseus processes. Redis acts as the coordination layer for
room discovery and matchmaking.

**How it works**:

1. Install `@colyseus/redis-presence` and configure it in `index.ts`:
   ```ts
   import { RedisPresence } from "@colyseus/redis-presence";
   import { RedisDriver } from "@colyseus/redis-driver";

   const server = new Server({
     presence: new RedisPresence({ url: process.env.REDIS_URL }),
     driver: new RedisDriver({ url: process.env.REDIS_URL }),
     transport: new WebSocketTransport({ ... }),
   });
   ```
2. Run multiple Colyseus processes (separate containers or PM2 instances).
3. Redis Presence ensures a client joining `office-{org_id}` is routed to the
   process that already hosts that room (or creates a new one if none exists).
4. Each room is still single-process, but different rooms can live on different
   processes.

**Capacity**: ~500-1,000 concurrent users total (across all orgs), depending on how
many processes you run and how users distribute across organizations.

**Effort**: Medium.
- Add the Redis presence/driver packages.
- Ensure the process does not store any room-external state (the current
  `agentIndex` Map and Redis subscriber are room-scoped, so this is already safe).
- Deploy multiple replicas behind a load balancer.
- Sticky sessions are required (see K8s configuration below).

**Limitations**: a single room is still bound to one process. If one organization has
500 concurrent users, that room alone exceeds single-process capacity.

### Option 3: Capacity-Based Sharding (Large Scale)

**Concept**: split a single organization's users across multiple room instances. Each
shard serves a subset of players, with cross-shard events relayed via Redis pub/sub.

**How it works**:

1. A matchmaker service assigns players to shards based on current occupancy.
   Example: `office-{org_id}-shard-{n}`, max 80 players per shard.
2. Cross-shard communication (chat, approval broadcasts, agent status) goes through
   a Redis pub/sub relay so players on shard-1 see events from shard-2.
3. The proximity loop and WebRTC signaling remain shard-local (players only see
   nearby players within the same shard).
4. Sticky sessions are mandatory -- a WebSocket connection must stay on the same
   server for its entire lifetime.

**Capacity**: 5,000+ concurrent users. Each shard handles 50-80 players. Add shards
horizontally.

**Effort**: High.
- Build a matchmaker service or use Colyseus's built-in matchmaking with custom
  `filterBy` options.
- Implement a Redis pub/sub relay for cross-shard events (chat, agent status,
  approval count).
- Handle shard rebalancing when shards empty out or become uneven.
- Update the client to handle shard assignment and potential shard transfers.

---

## K8s Sticky Session Configuration

Options 2 and 3 require sticky sessions because WebSocket connections are stateful.
The initial HTTP upgrade must reach the same server for the lifetime of the connection.

### Service-Level Affinity

```yaml
apiVersion: v1
kind: Service
metadata:
  name: colyseus
  namespace: selva
spec:
  selector:
    app: colyseus
  ports:
    - port: 4303
      targetPort: 4303
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 3600
```

### Ingress-Level Sticky Cookies (nginx-ingress)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: colyseus
  namespace: selva
  annotations:
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "COLYSEUS_AFFINITY"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "3600"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  rules:
    - host: colyseus.selva.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: colyseus
                port:
                  number: 4303
```

Cookie-based affinity is more reliable than ClientIP when users share a NAT gateway
or CDN. The long proxy timeouts prevent nginx from closing idle WebSocket connections.

---

## Monitoring and When to Scale

### Key Metrics

| Metric | What it tells you | Action threshold |
|---|---|---|
| `ws_connections` | Active WebSocket connections per process | >80 connections |
| `state_serialization_ms` | Time to serialize state patches per tick | >15 ms |
| `proximity_loop_ms` | Time to run proximity calculation | >50 ms |
| Process CPU usage | Overall process CPU saturation | >70% sustained |
| Process memory (RSS) | Memory pressure indicator | >512 MB |

### Instrumenting Colyseus

Add a Prometheus-compatible metrics endpoint to the existing Express app in
`index.ts`. The room's `onMessage`, `onJoin`, `onLeave`, and proximity loop are
the key instrumentation points.

```ts
// Example: track connection gauge
import { Gauge } from "prom-client";

const wsConnections = new Gauge({
  name: "colyseus_ws_connections",
  help: "Number of active WebSocket connections",
});

// In OfficeRoom:
onJoin()  { wsConnections.inc(); }
onLeave() { wsConnections.dec(); }
```

### Decision Points

| Situation | Action |
|---|---|
| Single org approaching 80 users | Implement Option 1 (room-per-org) if not already done |
| Multiple orgs, total >200 users | Implement Option 2 (Redis Presence, multi-process) |
| Single org exceeding 200 users | Evaluate Option 3 (sharding) |
| Proximity loop >50 ms | Optimize to spatial hash grid before scaling out |

---

## Migration Path

1. **Now**: deploy as a single process with one `office` room. Sufficient for
   development and early production with fewer than 50 concurrent users.

2. **First scaling step**: implement room-per-organization (Option 1). This is a
   code-only change with no infrastructure requirements. It isolates organizations
   and multiplies effective capacity by the number of active orgs.

3. **Monitor for 2-4 weeks** after Option 1. Collect real usage data on connection
   counts, serialization latency, and CPU usage.

4. **If single-process capacity is reached**: add `@colyseus/redis-presence` and
   deploy multiple replicas (Option 2). This requires sticky session configuration
   and a Redis instance (already available for task queuing).

5. **Option 3 (sharding) only if** a single organization regularly exceeds 200
   concurrent users. This is a significant engineering investment and should be
   justified by real demand, not projected growth.

---

## Proximity Loop Optimization Note

The current proximity calculation is O(n^2) where n is the number of players. At 100
players this means 10,000 distance checks per tick (5 times per second = 50,000/s).
Before investing in multi-process scaling, consider upgrading to a spatial hash grid:

```
Grid cell size = PROXIMITY_RADIUS (200px)
Each player is assigned to a cell based on floor(x/200), floor(y/200)
Distance checks only between players in the same or adjacent cells (9 cells max)
```

This reduces per-tick cost from O(n^2) to approximately O(n * k) where k is the
average number of players per neighborhood -- typically 5-10 even at high density.
The optimization is independent of the scaling option chosen and benefits all
configurations.

---

## Quick Reference: Clustering Checklist

When you are ready to move from single-instance to multi-process Colyseus:

1. **Install packages**: `pnpm add @colyseus/redis-presence @colyseus/redis-driver`
2. **Update `index.ts`**:
   ```ts
   import { RedisPresence } from "@colyseus/redis-presence";
   import { RedisDriver } from "@colyseus/redis-driver";

   const server = new Server({
     presence: new RedisPresence({ url: process.env.REDIS_URL }),
     driver: new RedisDriver({ url: process.env.REDIS_URL }),
     transport: new WebSocketTransport({ ... }),
   });
   ```
3. **Configure sticky sessions** (see K8s configuration above)
4. **Scale replicas**: `kubectl scale deployment/colyseus --replicas=3`
5. **Verify**: each replica should appear in Redis presence and rooms should be
   correctly distributed

### Capacity Planning

| Users | Recommended Setup |
|-------|-------------------|
| < 50 | Single instance |
| 50-200 | Room-per-org (Option 1) |
| 200-1000 | Redis Presence + 3-5 replicas (Option 2) |
| 1000+ | Sharding with Redis relay (Option 3) |
