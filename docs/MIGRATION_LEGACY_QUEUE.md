# Legacy Queue Migration Guide

## Background

Selva workers originally consumed tasks from a Redis LIST (`selva:tasks`
via LPUSH/BRPOP). In v0.2.0, task consumption was migrated to Redis Streams
(`selva:task-stream` with consumer groups). During the transition, the
nexus-api dual-wrote to both the Stream and the legacy LIST to allow gradual
rollout.

## What changed in v0.2.0

All LPUSH calls to `selva:tasks` have been removed. Only Redis Streams
(`selva:task-stream`) are used for task enqueueing.

## Impact

- **Workers v0.1.x**: If any workers are still running on the old BRPOP-based
  consumer, they will stop receiving tasks. Upgrade all workers to v0.2.0+.
- **Monitoring**: The `/api/v1/health/queue-stats` endpoint no longer reports
  `legacy_queue_depth`. Update any dashboards or alerts referencing this field.

## Cleanup

After verifying all workers are on v0.2.0+, you can safely delete the old key:

```bash
redis-cli DEL selva:tasks
```

## Rollback

If you need to revert to the legacy queue, restore the LPUSH calls from the
git history (commit prior to this change) and redeploy the nexus-api.
