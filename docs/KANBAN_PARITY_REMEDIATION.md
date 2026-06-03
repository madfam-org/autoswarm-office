# Selva Kanban Parity Remediation

Status: in progress

Reference benchmark: Nous Hermes kanban feature guide.

## Objective

Make Selva's task system a first-class kanban work-management layer without weakening the existing swarm execution queue.

The compatibility rule is:

- `status` remains the worker/runtime execution state.
- `kanban_status` is the human/operator work-management state.

## Implemented P0 slice

- Added kanban metadata to `swarm_tasks`: title, kanban status, priority, labels, due date, creator, parent task, dependencies, and update timestamp.
- Added durable `task_comments` for per-task discussion.
- Added append-only `task_history` for task-management events.
- Added tenant RLS policies for the new comment/history tables.
- Added task API responses carrying kanban fields.
- Added focused endpoints for kanban updates, comments, and history.
- Added a benchmark-style task claim endpoint for agent/operator leasing.
- Updated the office task board to use `todo`, `in_progress`, `review`, `done`, and `blocked`.
- Added drag/drop status movement in the task board.
- Added title, priority, labels, and due date to task dispatch.
- Added tenant-bound Harness `/task ...` commands.
- Added SDK/CLI `kanban ...` commands.
- Added durable lifecycle notification policies for assigned, review-needed, completed, blocked, and overdue tasks.
- Added JSON/CSV kanban import/export endpoints and SDK/CLI commands.
- Added kanban metrics for WIP age, blocked count, dependency blockage, overdue count, cycle time, label throughput, and assignee workload.

## Next remediation slices

1. Add channel-specific renderers for Slack/Discord/Teams/email if the generic webhook payload is not sufficient.
2. Add transport-level delivery persistence/retry if webhook receivers are not allowed to be lossy.

## Operational note

Existing worker integrations should continue to write runtime status through `/api/v1/swarms/tasks/{task_id}`. Operator-facing board movement should use `/api/v1/swarms/tasks/{task_id}/kanban`.

Agents that need benchmark-style claiming should use `POST /api/v1/swarms/tasks/claim`.

Overdue scans should call `POST /api/v1/swarms/tasks/notify-overdue`. Provider-specific transports should subscribe to `task.notification.*` events instead of being called directly from task mutation paths.

Outbound notification fanout:

- Redis channel: `selva:task-notifications` by default.
- Override channel: `SELVA_TASK_NOTIFICATION_REDIS_CHANNEL`.
- Generic webhooks: comma-separated `SELVA_TASK_NOTIFICATION_WEBHOOK_URLS`.
- Webhook signing: optional `SELVA_TASK_NOTIFICATION_WEBHOOK_SECRET`, emitted as `X-Selva-Signature: sha256=<hmac>`.

Worker overdue scans:

- Worker loop calls `POST /api/v1/swarms/tasks/notify-overdue-all`.
- Cadence: `KANBAN_OVERDUE_SCAN_INTERVAL_SECONDS`, default `300`, set `0` to disable.

Kanban import/export:

- Export JSON: `GET /api/v1/swarms/tasks/export?format=json`
- Export CSV: `GET /api/v1/swarms/tasks/export?format=csv`
- Import JSON/CSV: `POST /api/v1/swarms/tasks/import?format=json|csv`
- CLI: `selva kanban export`, `selva kanban import`, `selva kanban metrics`

Imported tasks use runtime `status="backlog"` so they do not enter the worker execution queue or get mistaken for missed Redis publications. Dispatch-created tasks still use the execution queue.
