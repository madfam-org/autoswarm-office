# KEDA Queue-Depth Autoscaling for Workers

## Overview

Selva workers process tasks from a Redis Stream (`selva:task-stream`).
During peak load, the queue can grow faster than a fixed replica count can drain.
[KEDA](https://keda.sh) enables queue-depth-based horizontal pod autoscaling.

## Prerequisites

- KEDA v2.10+ installed in the Kubernetes cluster
- Workers deployed as a `Deployment` (not a `StatefulSet`)
- Redis accessible from the KEDA operator namespace

## How it works

1. KEDA polls the Redis Stream pending entry count (PEL) at a configurable
   interval (default: 30s).
2. When pending messages exceed `targetPendingMessages`, KEDA scales up the
   worker Deployment.
3. When the queue drains, KEDA scales back down (respecting `minReplicaCount`).
4. Workers use consumer groups with XAUTOCLAIM, so new replicas automatically
   pick up unprocessed messages.

## Configuration

See `infra/k8s/production/keda-scaledobject.yaml` for the manifest.

Key parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `minReplicaCount` | 1 | Minimum replicas (0 = scale to zero) |
| `maxReplicaCount` | 10 | Maximum replicas |
| `targetPendingMessages` | 5 | Target pending messages per replica |
| `pollingInterval` | 30 | Seconds between KEDA polls |
| `cooldownPeriod` | 300 | Seconds before scale-down |

## Monitoring

- `/health` endpoint on workers (port 4305) reports consumer group lag.
- `selva_queue_pending` Prometheus gauge (from worker `/metrics`).
- Grafana dashboard: alert on `pending > 50` for sustained 5 minutes.

## Limitations

- KEDA's Redis Stream scaler requires the consumer group to exist before
  the first poll. Workers create the group on startup via XGROUP CREATE.
- Scale-to-zero (`minReplicaCount: 0`) means the consumer group won't exist
  until the first replica starts. Use `minReplicaCount: 1` unless you have
  an init job that creates the group.

## Staging overlay constraint

Workers mount `selva-memory-pvc` (ReadWriteOnce). **Do not scale workers past
one replica in staging** unless the PVC is switched to ReadWriteMany or
per-pod storage. Staging applies `infra/k8s/overlays/staging/patch-keda-staging.yaml`
to pin `workers-keda` at `minReplicaCount: 1` / `maxReplicaCount: 1`.
