/**
 * AUTO-GENERATED from nexus-api OpenAPI schema. DO NOT EDIT.
 *
 * Run `pnpm generate-types` to regenerate. CI (schema-drift.yml)
 * fails if this file is out of sync with the FastAPI routes.
 *
 * These are WIRE TYPES (snake_case, mirror the API). Hand-written
 * domain types in sibling files (camelCase) are still the source of
 * truth for React/Phaser; conversion happens at the fetch boundary.
 */

/* eslint-disable */
export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Root Health */
        get: operations["root_health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/sentry-probe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sentry Probe
         * @description Emit a tagged synthetic error to Sentry for Phase 0 wiring proof.
         *
         *     Requires ``Authorization: Bearer <WORKER_API_TOKEN>``. Returns 503 when
         *     ``SENTRY_DSN`` is unset so operators know capture is not yet live.
         */
        post: operations["sentry_probe_api_v1_health_sentry_probe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Liveness probe -- always returns 200 if the process is running.
         */
        get: operations["health_api_v1_health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Ready
         * @description Readiness probe -- validates database and Redis connectivity.
         *
         *     Returns 200 when all dependencies are reachable, 503 otherwise.
         */
        get: operations["ready_api_v1_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/detail": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Detail
         * @description Detailed health check including Colyseus connectivity and pool metrics.
         */
        get: operations["health_detail_api_v1_health_detail_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/pool-stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Pool Stats
         * @description Return database connection pool statistics.
         */
        get: operations["pool_stats_api_v1_health_pool_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/queue-stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Queue Stats
         * @description Return Redis task stream and queue statistics.
         */
        get: operations["queue_stats_api_v1_health_queue_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/dlq-stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dlq Stats
         * @description Return dead-letter queue statistics and recent entries.
         */
        get: operations["dlq_stats_api_v1_health_dlq_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/consent-ledger-grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Consent Ledger Grants
         * @description Verify the append-only invariant on `consent_ledger` is enforced at the DB level.
         *
         *     Migration 0018 REVOKEs UPDATE/DELETE on `consent_ledger` from the
         *     application role (default ``selva``). This endpoint exposes
         *     a runtime check so a re-applied migration, manual ``GRANT ALL``, or
         *     a superuser-mode test seed that silently re-mutates the grants will
         *     surface in monitoring.
         *
         *     Open endpoint (no auth) — matches the rest of `/health`. The role
         *     name is not echoed in the response to avoid disclosing internal
         *     config; it is logged when the invariant fails for ops triage.
         *
         *     Returns 503 when the invariant does not hold.
         */
        get: operations["consent_ledger_grants_api_v1_health_consent_ledger_grants_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health/rls-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Rls Status
         * @description Verify the RLS Phase 1.5 strict-mode migration has landed on this DB.
         *
         *     Returns the runtime RLS posture so ops can confirm migration 0028
         *     applied cleanly on a live cluster:
         *
         *         - ``strict_mode_enabled``: True iff every tenant table has FORCE
         *           ROW LEVEL SECURITY AND its policy lacks the Phase 1 ``IS NULL``
         *           escape-hatch leg. False means the cluster is still on Phase 1
         *           (migration 0025) policies, OR the rollout is partial.
         *         - ``policies``: per-table snapshot of the policy definition
         *           (name + USING clause). Lets ops eyeball that the strict form
         *           is in place.
         *         - ``force_rls_tables``: list of tables that have ``FORCE ROW
         *           LEVEL SECURITY`` enabled. Should equal the tenant-table list
         *           when strict mode is on.
         *         - ``app_admin_role_present``: True iff the ``app_admin``
         *           BYPASSRLS role exists. Required for ``admin_session()`` to
         *           actually bypass.
         *
         *     Open endpoint (no auth) -- matches the rest of `/health/*`.
         *
         *     Returns 503 when strict mode is NOT enabled, so the endpoint can
         *     drive a CI gate or ops dashboard alarm. SQLite test paths return a
         *     static "not_postgres" response with 200.
         */
        get: operations["rls_status_api_v1_health_rls_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Agents
         * @description List agents with pagination, optionally filtered by department.
         */
        get: operations["list_agents_api_v1_agents__get"];
        put?: never;
        /**
         * Create Agent
         * @description Draft a new agent.
         */
        post: operations["create_agent_api_v1_agents__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/{agent_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Agent
         * @description Retrieve a single agent by ID.
         */
        get: operations["get_agent_api_v1_agents__agent_id__get"];
        /**
         * Update Agent
         * @description Update mutable agent fields.
         */
        put: operations["update_agent_api_v1_agents__agent_id__put"];
        post?: never;
        /**
         * Delete Agent
         * @description Remove an agent permanently.
         */
        delete: operations["delete_agent_api_v1_agents__agent_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/{agent_id}/assign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Assign Agent
         * @description Assign an agent to a department.
         */
        post: operations["assign_agent_api_v1_agents__agent_id__assign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/{agent_id}/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Agent Stats
         * @description Apply delta increments to agent performance stats.
         *
         *     Worker-to-API endpoint — no user auth required (Bearer token only).
         *     Computes a running average for task duration.
         */
        patch: operations["update_agent_stats_api_v1_agents__agent_id__stats_patch"];
        trace?: never;
    };
    "/api/v1/departments/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Departments
         * @description List all departments with pagination.
         */
        get: operations["list_departments_api_v1_departments__get"];
        put?: never;
        /**
         * Create Department
         * @description Create a new department.
         */
        post: operations["create_department_api_v1_departments__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/departments/{dept_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Department
         * @description Retrieve a department with its agents.
         */
        get: operations["get_department_api_v1_departments__dept_id__get"];
        /**
         * Update Department
         * @description Update mutable department fields.
         */
        put: operations["update_department_api_v1_departments__dept_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Pending Approvals
         * @description List all pending approval requests for the caller's tenant.
         *
         *     Tenant-scoped: only requests with ``org_id == tenant.org_id`` are returned.
         */
        get: operations["list_pending_approvals_api_v1_approvals__get"];
        put?: never;
        /**
         * Create Approval Request
         * @description Create a new approval request.
         *
         *     Called by workers when an agent hits a HITL interrupt. Requires Bearer
         *     authentication (worker shared-secret token, with ``X-Selva-Tenant-Org``
         *     header declaring the tenant). The persisted request's ``org_id`` is
         *     derived server-side from the authenticated caller -- callers cannot
         *     target an arbitrary tenant.
         *
         *     Only the worker/service role is permitted; user-initiated approval
         *     creation is not a supported flow.
         */
        post: operations["create_approval_request_api_v1_approvals__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{request_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Approval Request
         * @description Retrieve a single approval request by ID. Tenant-scoped.
         *
         *     Used by workers for polling approval status and by tacticians for the
         *     detail view. Cross-tenant lookups return 404 (not 403) to avoid leaking
         *     the existence of approval IDs across tenants.
         */
        get: operations["get_approval_request_api_v1_approvals__request_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{request_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Approve Request
         * @description Approve a pending request (the Tactician presses 'A').
         *
         *     Idempotency: when the caller sends ``Idempotency-Key`` header, a
         *     successful approval response is cached for 24h scoped by (org_id,
         *     POST, /api/v1/approvals/{id}/approve, key). Retries with the same
         *     key replay the cached response. Only the success path is cached —
         *     a 404 (not found) or 409 (already resolved) leaves the cache empty
         *     so the next retry can re-evaluate.
         */
        post: operations["approve_request_api_v1_approvals__request_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/{request_id}/deny": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Deny Request
         * @description Deny a pending request with optional feedback (the Tactician presses 'B').
         *
         *     Idempotency: same contract as ``approve_request``. Only the success
         *     path is cached — a 404 (not found) or 409 (already resolved) leaves
         *     the cache empty so the next retry can re-evaluate.
         */
        post: operations["deny_request_api_v1_approvals__request_id__deny_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/approvals/bulk-expire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Bulk Expire
         * @description Mark long-pending approval requests as ``expired`` (cross-tenant ops).
         *
         *     Mirrors the ``swarms.reap-stale`` reaper for approvals: any approval
         *     that has stayed in ``pending`` for more than ``older_than_hours``
         *     (default 24 h) is flipped to ``expired``. Same access-control gate
         *     as ``reap-stale`` — only ``service`` / ``worker`` / ``platform`` /
         *     ``admin`` roles may invoke it.
         *
         *     Audit trail: a single ``approval.bulk_expired`` summary event is
         *     emitted (NOT one event per row — see PR description) carrying the
         *     ``affected_count`` and the list of expired approval IDs. The event
         *     is recorded under the caller's JWT-derived ``org_id`` (or
         *     ``"platform"`` when the caller is the cross-tenant worker token)
         *     rather than each tenant's org_id, because the operation itself is a
         *     platform-level sweep.
         */
        post: operations["bulk_expire_api_v1_approvals_bulk_expire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/dispatch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Dispatch Task
         * @description Dispatch a new swarm task.
         *
         *     Validates compute token budget, persists the task, and publishes a
         *     message to the Redis task queue for worker consumption.
         *
         *     Idempotency: when the caller sends ``Idempotency-Key`` header, a
         *     successful response is cached for 24h scoped by (org_id, POST,
         *     /api/v1/swarms/dispatch, key). Retries with the same key replay the
         *     cached response instead of dispatching a duplicate task. Header
         *     absent → endpoint behaves exactly as before (no caching).
         */
        post: operations["dispatch_task_api_v1_swarms_dispatch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/dispatch/ecosystem-app": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Dispatch Ecosystem App Manifest
         * @description Dispatch an EcosystemApp manifest as a canonical deployment task.
         */
        post: operations["dispatch_ecosystem_app_manifest_api_v1_swarms_dispatch_ecosystem_app_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/dispatch/ecosystem-app/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Verify Ecosystem App Manifest
         * @description Read-only EcosystemApp/AppSpec verification; never dispatches or mutates.
         */
        post: operations["verify_ecosystem_app_manifest_api_v1_swarms_dispatch_ecosystem_app_verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Active Tasks
         * @description List tasks that are currently queued or in progress.
         */
        get: operations["list_active_tasks_api_v1_swarms_tasks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/board": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Task Board
         * @description Return tasks grouped by status column with aggregated event data.
         */
        get: operations["get_task_board_api_v1_swarms_tasks_board_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Kanban Tasks
         * @description Export kanban tasks as JSON or CSV.
         */
        get: operations["export_kanban_tasks_api_v1_swarms_tasks_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Kanban Tasks
         * @description Import kanban tasks from JSON or CSV without enqueuing execution.
         */
        post: operations["import_kanban_tasks_api_v1_swarms_tasks_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/kanban-metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Kanban Metrics
         * @description Return kanban-specific throughput, WIP, blocked, and overdue metrics.
         */
        get: operations["get_kanban_metrics_api_v1_swarms_tasks_kanban_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/claim": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Claim Available Task
         * @description Claim the next available kanban task for an agent/operator.
         *
         *     This is the benchmark-style worker claiming primitive. It updates only
         *     kanban ownership/progress state; runtime workers still drive execution
         *     through the existing status PATCH endpoint.
         */
        post: operations["claim_available_task_api_v1_swarms_tasks_claim_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/notify-overdue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Notify Overdue Tasks
         * @description Emit lifecycle notifications for overdue active kanban tasks.
         */
        post: operations["notify_overdue_tasks_api_v1_swarms_tasks_notify_overdue_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/notify-overdue-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Notify Overdue Tasks All
         * @description Emit overdue notifications across all tenants for worker/platform callers.
         */
        post: operations["notify_overdue_tasks_all_api_v1_swarms_tasks_notify_overdue_all_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Task
         * @description Retrieve a single task by ID.
         */
        get: operations["get_task_api_v1_swarms_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Task Status
         * @description Update a task's status.
         *
         *     When the status transitions to ``completed`` or ``failed`` the
         *     ``completed_at`` timestamp is set automatically.
         */
        patch: operations["update_task_status_api_v1_swarms_tasks__task_id__patch"];
        trace?: never;
    };
    "/api/v1/swarms/tasks/{task_id}/kanban": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Task Kanban
         * @description Update first-class kanban metadata for a task.
         */
        patch: operations["update_task_kanban_api_v1_swarms_tasks__task_id__kanban_patch"];
        trace?: never;
    };
    "/api/v1/swarms/tasks/{task_id}/comments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Task Comments */
        get: operations["list_task_comments_api_v1_swarms_tasks__task_id__comments_get"];
        put?: never;
        /** Create Task Comment */
        post: operations["create_task_comment_api_v1_swarms_tasks__task_id__comments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/{task_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Task History */
        get: operations["list_task_history_api_v1_swarms_tasks__task_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Deployment Evidence Records
         * @description List deployment evidence records, newest first. Tenant-scoped.
         */
        get: operations["list_deployment_evidence_records_api_v1_swarms_evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/evidence/{evidence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Deployment Evidence Record
         * @description Retrieve one deployment evidence record by ID. Tenant-scoped.
         */
        get: operations["get_deployment_evidence_record_api_v1_swarms_evidence__evidence_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/swarms/tasks/reap-stale": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reap Stale Tasks
         * @description Auto-fail queued/pending tasks older than 1 hour (cross-tenant ops).
         *
         *     This is a platform health endpoint that operators or a cron job call
         *     to clean up stuck tasks across **all tenants**. The role gate is the
         *     access control: only callers carrying ``service``, ``worker``,
         *     ``platform``, or ``admin`` roles may invoke it.
         *
         *     Tenancy bypass (Phase 1.5 -- migration 0028):
         *         Uses ``admin_session()`` which opens a session against the
         *         ``app_admin`` BYPASSRLS connection pool. This is the canonical
         *         way to express "I genuinely need to read/mutate rows belonging
         *         to multiple tenants in one query" under the strict RLS policies
         *         installed by migration 0028.
         *
         *         Pre-migration-0028 this endpoint relied on the Phase 1 permissive
         *         policy (``IS NULL OR = '' OR = $org``) and manually reset the
         *         session var to ``""`` to fall through to the IS NULL leg. That
         *         leg no longer exists -- under the strict policies a reset
         *         session var would return zero rows. ``admin_session()`` logs at
         *         WARNING on every entry, so the cross-tenant access is visible in
         *         structured logs without needing to parse pg_stat_activity.
         *
         *         See ``docs/RLS_PHASE_1_5_AUDIT.md`` §2.C and §3 for the full
         *         rationale.
         */
        post: operations["reap_stale_tasks_api_v1_swarms_tasks_reap_stale_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Billing Status
         * @description Proxy to the Dhanam billing API to retrieve subscription status.
         *
         *     Falls back to a local stub when the Dhanam API is unreachable so the
         *     office UI can still render a meaningful state.
         */
        get: operations["billing_status_api_v1_billing_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Compute Usage
         * @description Return compute token usage aggregated from the ledger.
         *
         *     Groups usage by action type for the current UTC day.
         */
        get: operations["compute_usage_api_v1_billing_usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/tokens": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Compute Token Status
         * @description Return the current compute token bucket status.
         *
         *     The daily limit is sourced from the subscription tier; usage is
         *     summed from the ledger for today.
         */
        get: operations["compute_token_status_api_v1_billing_tokens_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/portal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Billing Portal
         * @description Create a Dhanam billing portal session for self-service management.
         */
        post: operations["create_billing_portal_api_v1_billing_portal_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/agent-hours": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Agent Hours Usage
         * @description Metered agent-hours consumed by the caller's org this calendar month.
         *
         *     This is the consumption surface for Selva's Tulana hourly packs
         *     (Maker/Studio/Enterprise). Dhanam reads accrued hours at invoice time;
         *     this endpoint surfaces the running total for the UI and reporting.
         */
        get: operations["agent_hours_usage_api_v1_billing_agent_hours_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/tiers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Subscription Tiers
         * @description Return the purchasable subscription tiers for the pricing page.
         *
         *     Source of truth is ``infra/pricing/selva-tiers.json`` via
         *     ``billing_tiers.get_subscription_tiers`` — the CI drift gate keeps this
         *     from diverging from the canonical numbers.
         */
        get: operations["list_subscription_tiers_api_v1_billing_tiers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/checkout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Checkout
         * @description Start a subscription checkout for the caller's org.
         *
         *     Selva holds no Stripe keys — Dhanam is the sole payment surface (RFC 0011
         *     / monetization north star). We validate the tier, resolve the caller's
         *     Dhanam space, and ask Dhanam to create the hosted checkout; the resulting
         *     ``subscription.created`` webhook flows back through the Dhanam webhook
         *     handler. Returns ``{"url": ...}`` for the browser to redirect to.
         *
         *     While Dhanam's checkout API is not yet live (its endpoint 404s / the
         *     ``DHANAM_API_URL`` is unset), this returns HTTP 501 with a clear
         *     ``status: "not_configured"`` body rather than a 500 — the full contract
         *     is wired and flips on the moment Dhanam ships the endpoint.
         */
        post: operations["create_checkout_api_v1_billing_checkout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/record": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record Usage
         * @description Record a compute token debit from a worker (authenticated, RFC 0034 P0).
         *
         *     Org scope comes from the authenticated caller (worker tokens declare it
         *     via ``X-Selva-Tenant-Org``), never from the request body — a caller must
         *     not be able to debit another tenant's bucket.
         */
        post: operations["record_usage_api_v1_billing_record_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/billing/check-budget": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Check Budget
         * @description Check the caller's remaining compute token budget for today (authenticated, RFC 0034 P0).
         *
         *     Scope is the authenticated org — one tenant must not be able to read
         *     another tenant's spend position.
         */
        post: operations["check_budget_api_v1_billing_check_budget_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Skills
         * @description Return all discovered skills, optionally filtered by tier.
         */
        get: operations["list_skills_api_v1_skills__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/community/enable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Enable Community
         * @description Enable community skills at runtime.
         */
        post: operations["enable_community_api_v1_skills_community_enable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/community/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Disable Community
         * @description Disable community skills at runtime.
         */
        post: operations["disable_community_api_v1_skills_community_disable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/community/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Community Status
         * @description Return whether community skills are currently enabled.
         */
        get: operations["community_status_api_v1_skills_community_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/compact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Skills Compact
         * @description Level 0: Compact skill index.
         *
         *     Returns [{name, description, category}] for all SKILL.md skills.
         *     Approximately 3,000 tokens for a 50-skill catalogue.
         *     Intended for LLM context injection before a phase loads full skill content.
         */
        get: operations["list_skills_compact_api_v1_skills_compact_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/md/{skill_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Skill Full
         * @description Level 1: Full SKILL.md content for a named skill.
         *
         *     Returns the complete SKILL.md text. Use this when the agent decides
         *     it needs full instructions for a specific skill.
         */
        get: operations["get_skill_full_api_v1_skills_md__skill_name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/md/{skill_name}/refs/{ref_path}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Skill Reference
         * @description Level 2: Specific reference file within a skill directory.
         *
         *     Useful for loading supplementary docs, API references, or example code
         *     without loading the entire skill context.
         */
        get: operations["get_skill_reference_api_v1_skills_md__skill_name__refs__ref_path__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/refiner/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Refiner Metrics
         * @description Return accumulated metrics from the most recent SkillRefiner run.
         *
         *     Useful for monitoring the health of the skill self-improvement loop.
         */
        get: operations["refiner_metrics_api_v1_skills_refiner_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/telegram/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Telegram Webhook
         * @description Harness communication gateway — Telegram.
         *
         *     Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (set when
         *     registering the webhook via ``setWebhook?secret_token=...``) and routes
         *     the ``/initiate_acp <url>`` slash command to a Celery ACP task.
         */
        post: operations["telegram_webhook_api_v1_gateway_telegram_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/discord/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Discord Webhook
         * @description Harness communication gateway — Discord.
         *
         *     Validates HMAC-SHA256 signature and handles:
         *     - ``/status``: returns recent swarm transcript hits from EdgeMemoryDB.
         *     - ``/initiate_acp <url>``: same trigger as Telegram.
         *
         *     Requires ``DISCORD_WEBHOOK_SECRET`` env var. Endpoint refuses requests
         *     when the secret is unset (no fail-open).
         */
        post: operations["discord_webhook_api_v1_gateway_discord_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/slack/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Slack Webhook
         * @description Harness communication gateway — Slack.
         *
         *     Validates Slack's v0 HMAC-SHA256 signature with timestamp replay protection
         *     (rejects requests older than 5 minutes), then routes slash commands.
         */
        post: operations["slack_webhook_api_v1_gateway_slack_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/email/inbound": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Email Inbound
         * @description Accepts inbound email parse payloads from SendGrid or Postmark.
         *     Routes commands from allow-listed sender addresses.
         *
         *     SECURITY (Phase 1 hardening): Unlike the other 14 webhook handlers,
         *     this endpoint does NOT use a shared HMAC secret -- inbound-email
         *     parse providers don't share a common signing contract. The trust
         *     signal is the ``From:`` address that the upstream provider has
         *     already validated via SPF/DKIM/DMARC at MX time, checked against
         *     the operator-controlled ``GATEWAY_EMAIL_WHITELIST`` allow-list.
         *
         *     Fail-closed contract:
         *     - 503 when ``GATEWAY_EMAIL_WHITELIST`` is unset (endpoint disabled).
         *       Pre-hardening this would 200 and dispatch an ACP task with an
         *       attacker-supplied URL because empty allow-list short-circuited
         *       the membership check.
         *     - 401 when the parsed ``From:`` address is not on the allow-list.
         *     - 200 + ``status: ignored`` when the body has no ``initiate_acp:``
         *       command (so spam / out-of-band mail from allow-listed senders
         *       doesn't error-loop the upstream provider).
         *
         *     See ``_require_inbound_allowlist`` for the full threat model.
         */
        post: operations["email_inbound_api_v1_gateway_email_inbound_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/whatsapp/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Whatsapp Webhook Verify
         * @description Responds to the Meta webhook verification challenge (GET request).
         *     Required during webhook registration in Meta Developer Portal.
         */
        get: operations["whatsapp_webhook_verify_api_v1_gateway_whatsapp_webhook_get"];
        put?: never;
        /**
         * Whatsapp Inbound
         * @description Receive inbound WhatsApp messages via Meta Cloud API webhook.
         *     Validates X-Hub-Signature-256 and routes /acp commands.
         *
         *     Requires ``WHATSAPP_ACCESS_TOKEN`` env var (used as the HMAC secret).
         *     Endpoint refuses requests when the secret is unset.
         */
        post: operations["whatsapp_inbound_api_v1_gateway_whatsapp_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/matrix/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Matrix Inbound
         * @description Receive events from a Matrix appservice registration.
         *     Validates the Authorization: Bearer <token> header.
         */
        put: operations["matrix_inbound_api_v1_gateway_matrix_webhook_put"];
        /**
         * Matrix Inbound
         * @description Receive events from a Matrix appservice registration.
         *     Validates the Authorization: Bearer <token> header.
         */
        post: operations["matrix_inbound_api_v1_gateway_matrix_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/mattermost/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Mattermost Inbound
         * @description Receive Mattermost slash command: /initiate_acp <url>.
         *     Validates the shared mattermost_token from the request body.
         */
        post: operations["mattermost_inbound_api_v1_gateway_mattermost_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/signal/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Signal Inbound
         * @description Receive inbound Signal messages via signal-cli REST API envelope format.
         *     Validates source number against the configured whitelist.
         */
        post: operations["signal_inbound_api_v1_gateway_signal_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/sms/inbound": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sms Inbound
         * @description Accepts Twilio SMS webhook payloads.
         *     Validates the X-Twilio-Signature HMAC and routes commands.
         */
        post: operations["sms_inbound_api_v1_gateway_sms_inbound_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/dingtalk/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Dingtalk Webhook
         * @description DingTalk inbound webhook — HMAC-SHA256 validated.
         */
        post: operations["dingtalk_webhook_api_v1_gateway_dingtalk_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/feishu/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Feishu Webhook
         * @description Feishu (Lark) event webhook — challenge verification + ACP routing.
         */
        post: operations["feishu_webhook_api_v1_gateway_feishu_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/wecom/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Wecom Webhook
         * @description WeCom outgoing webhook — token-validated.
         */
        post: operations["wecom_webhook_api_v1_gateway_wecom_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/wecom/callback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Wecom Callback
         * @description WeCom server-mode callback — echoes challenge, logs encrypted messages.
         */
        post: operations["wecom_callback_api_v1_gateway_wecom_callback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/weixin/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Weixin Webhook
         * @description Weixin via WxPusher — appToken validated.
         */
        post: operations["weixin_webhook_api_v1_gateway_weixin_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/bluebubbles/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Bluebubbles Webhook
         * @description BlueBubbles iMessage bridge webhook — password validated.
         */
        post: operations["bluebubbles_webhook_api_v1_gateway_bluebubbles_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/teams/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Teams Webhook
         * @description Microsoft Teams inbound webhook or bridge relay — signed and command-routed.
         */
        post: operations["teams_webhook_api_v1_gateway_teams_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/irc/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Irc Webhook
         * @description IRC bridge relay — signed and routed into the Harness command surface.
         */
        post: operations["irc_webhook_api_v1_gateway_irc_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/qq/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Qq Webhook
         * @description QQ Bot bridge relay — signed and routed into the Harness command surface.
         */
        post: operations["qq_webhook_api_v1_gateway_qq_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/yuanbao/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Yuanbao Webhook
         * @description Yuanbao bridge relay — signed and routed into the Harness command surface.
         */
        post: operations["yuanbao_webhook_api_v1_gateway_yuanbao_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/homeassistant/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Homeassistant Webhook
         * @description Home Assistant webhook — Bearer long-lived token validated.
         */
        post: operations["homeassistant_webhook_api_v1_gateway_homeassistant_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/webhook/{channel_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generic Webhook
         * @description Generic HMAC-signed webhook. channel_id used for routing/logging.
         *
         *     Requires ``SELVA_WEBHOOK_SECRET`` env var. Endpoint refuses requests
         *     when the secret is unset OR when the X-Webhook-Signature header is missing
         *     (no fail-open).
         */
        post: operations["generic_webhook_api_v1_gateway_webhook__channel_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/gateway/api/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Api Complete
         * @description Direct API completion — fire-and-forget ACP dispatch for Harness API mode.
         */
        post: operations["api_complete_api_v1_gateway_api_complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Workflows
         * @description List all workflows for the current tenant with pagination.
         */
        get: operations["list_workflows_api_v1_workflows_get"];
        put?: never;
        /**
         * Create Workflow
         * @description Create a new workflow definition.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. A retried
         *     create should NOT produce a duplicate Workflow row.
         */
        post: operations["create_workflow_api_v1_workflows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Templates
         * @description List available workflow templates from data/workflow-templates/.
         */
        get: operations["list_templates_api_v1_workflows_templates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/from-template": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create From Template
         * @description Create a new workflow from a built-in template.
         */
        post: operations["create_from_template_api_v1_workflows_from_template_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/{workflow_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Workflow
         * @description Get a single workflow by ID.
         */
        get: operations["get_workflow_api_v1_workflows__workflow_id__get"];
        /**
         * Update Workflow
         * @description Update an existing workflow definition.
         */
        put: operations["update_workflow_api_v1_workflows__workflow_id__put"];
        post?: never;
        /**
         * Delete Workflow
         * @description Delete a workflow definition.
         */
        delete: operations["delete_workflow_api_v1_workflows__workflow_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Validate Workflow
         * @description Validate a workflow YAML without persisting it.
         */
        post: operations["validate_workflow_api_v1_workflows_validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Workflow
         * @description Import a workflow from YAML content.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. A retried
         *     upload should NOT produce a duplicate Workflow row.
         */
        post: operations["import_workflow_api_v1_workflows_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workflows/{workflow_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Workflow
         * @description Export a workflow as YAML content.
         */
        get: operations["export_workflow_api_v1_workflows__workflow_id__export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Artifacts
         * @description List artifacts with pagination, optionally filtered by task_id.
         */
        get: operations["list_artifacts_api_v1_artifacts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Artifact
         * @description Get artifact metadata by ID.
         */
        get: operations["get_artifact_api_v1_artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Artifact
         * @description Delete an artifact by ID.
         */
        delete: operations["delete_artifact_api_v1_artifacts__artifact_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/artifacts/{artifact_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Artifact
         * @description Stream artifact content.
         */
        get: operations["download_artifact_api_v1_artifacts__artifact_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/marketplace/skills": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Marketplace Skills
         * @description List marketplace skill entries with pagination, search, category filter, and sorting.
         */
        get: operations["list_marketplace_skills_api_v1_marketplace_skills_get"];
        put?: never;
        /**
         * Publish Skill
         * @description Publish a new skill to the marketplace.
         *
         *     The ``yaml_content`` field must contain valid SKILL.md content with
         *     YAML frontmatter delimited by ``---`` fences.
         */
        post: operations["publish_skill_api_v1_marketplace_skills_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/marketplace/skills/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Marketplace Skill
         * @description Get a single marketplace entry with full details including ratings.
         */
        get: operations["get_marketplace_skill_api_v1_marketplace_skills__entry_id__get"];
        put?: never;
        post?: never;
        /**
         * Unpublish Skill
         * @description Unpublish a marketplace skill. Only the original author may delete.
         */
        delete: operations["unpublish_skill_api_v1_marketplace_skills__entry_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/marketplace/skills/{entry_id}/rate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rate Skill
         * @description Rate a marketplace skill. Upserts if the user already rated this entry.
         */
        post: operations["rate_skill_api_v1_marketplace_skills__entry_id__rate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/marketplace/skills/{entry_id}/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Install Skill
         * @description Install a marketplace skill into the community-skills directory.
         *
         *     Writes the YAML content as ``SKILL.md`` into
         *     ``packages/skills/community-skills/{name}/`` and increments the download
         *     counter.  After writing, the skill registry is refreshed so the new skill
         *     becomes discoverable immediately.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. The cache is
         *     populated ONLY AFTER the SKILL.md file has been successfully written —
         *     if a replay arrives but the install file was deleted out-of-band, the
         *     cached InstallResponse may point to a missing file. We accept that
         *     trade-off rather than re-running ``write_text`` on every replay
         *     (which would silently re-install). Operators that want strict
         *     file-presence guarantees should not delete community-skills/<name>/
         *     behind the API's back.
         */
        post: operations["install_skill_api_v1_marketplace_skills__entry_id__install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/maps": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Maps
         * @description List all maps for the current tenant with pagination.
         */
        get: operations["list_maps_api_v1_maps_get"];
        put?: never;
        /**
         * Create Map
         * @description Create a new map definition.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. A retry
         *     after a network blip should NOT produce a second Map row with the
         *     same content. The cached response (containing the original map id)
         *     is returned on replay.
         */
        post: operations["create_map_api_v1_maps_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/maps/{map_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Map
         * @description Get a single map by ID.
         */
        get: operations["get_map_api_v1_maps__map_id__get"];
        /**
         * Update Map
         * @description Update an existing map definition.
         */
        put: operations["update_map_api_v1_maps__map_id__put"];
        post?: never;
        /**
         * Delete Map
         * @description Delete a map definition.
         */
        delete: operations["delete_map_api_v1_maps__map_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/maps/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Export Map
         * @description Validate TMJ content and return it (for download).
         */
        post: operations["export_map_api_v1_maps_export_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/maps/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Map
         * @description Import a TMJ file as a new map.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. A retried
         *     upload should NOT produce a duplicate Map row.
         */
        post: operations["import_map_api_v1_maps_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calendar/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Events
         * @description List upcoming calendar events for the current user.
         *
         *     Returns events in the next *hours* hours (default 8) and a ``is_busy``
         *     flag indicating whether the user is currently in a meeting.
         */
        get: operations["list_events_api_v1_calendar_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calendar/connect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Connect Calendar
         * @description Store a calendar connection for the current user.
         *
         *     If a connection already exists it is updated with the new tokens.
         *
         *     Idempotency: replay-safe via the ``Idempotency-Key`` header. A retry
         *     after a network blip should NOT re-store the same OAuth tokens twice
         *     (which would emit a duplicate ``calendar.connected`` audit event and
         *     potentially trigger downstream re-syncs). The cached response is
         *     returned without touching the DB on replay.
         */
        post: operations["connect_calendar_api_v1_calendar_connect_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calendar/disconnect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Disconnect Calendar
         * @description Remove the current user's calendar connection.
         */
        delete: operations["disconnect_calendar_api_v1_calendar_disconnect_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calendar/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Calendar Status
         * @description Check the current user's calendar connection status.
         */
        get: operations["calendar_status_api_v1_calendar_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intelligence/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Intelligence Config
         * @description Return org-level inference config (providers, model assignments, priorities).
         *
         *     API keys are NEVER included in the response.
         */
        get: operations["get_intelligence_config_api_v1_intelligence_config_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/invoices/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Invoice
         * @description Dispatch a billing graph to generate and stamp a CFDI 4.0 invoice.
         *
         *     Creates a ``SwarmTask`` with ``graph_type="billing"`` and enqueues it
         *     on the Redis task stream for worker consumption.
         */
        post: operations["generate_invoice_api_v1_invoices_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/invoices/{uuid}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Invoice Status
         * @description Check CFDI status via Karafiel.
         *
         *     Queries the Karafiel compliance API for the stamping status of a
         *     given CFDI UUID.  Returns a placeholder when Karafiel is unavailable.
         */
        get: operations["invoice_status_api_v1_invoices__uuid__status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chat/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Chat History
         * @description Return recent chat messages for a room with pagination, newest first.
         *
         *     Pagination: use ``limit`` and ``offset`` for standard pagination, or pass
         *     ``before`` with the ``created_at`` of the oldest message in your current
         *     batch to fetch the next page (cursor-based).
         *
         *     Tenant-scoped: only messages with ``org_id == tenant.org_id`` are returned.
         */
        get: operations["get_chat_history_api_v1_chat_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chat/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Chat Message
         * @description Persist a chat message.
         *
         *     Requires Bearer-token authentication. The persisted message's ``org_id``
         *     is derived server-side from the authenticated caller (``user['org_id']``)
         *     -- the request body does not carry an ``org_id`` field.
         *
         *     Called by Colyseus (fire-and-forget) using the worker shared-secret token
         *     plus the ``X-Selva-Tenant-Org`` header to declare the tenant scope.
         */
        post: operations["create_chat_message_api_v1_chat_messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Events
         * @description List events with optional filters, newest first. Tenant-scoped.
         */
        get: operations["list_events_api_v1_events__get"];
        put?: never;
        /**
         * Create Event
         * @description Create a new task event.
         *
         *     Requires Bearer token authentication (worker token or JWT). The event's
         *     ``org_id`` is derived server-side from the authenticated caller -- callers
         *     cannot specify a target ``org_id`` in the body. Workers declare their
         *     tenant via the ``X-Selva-Tenant-Org`` header (resolved by ``auth.py``).
         *
         *     Uses ``tenant_session(org_id)`` instead of ``get_db`` so RLS sees the
         *     worker/JWT tenant before insert (``get_db`` would run before ``user``).
         *
         *     Broadcasts only to WebSocket clients in the same tenant.
         */
        post: operations["create_event_api_v1_events__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events/tasks/{task_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Task Timeline
         * @description Full execution timeline for a single task. Tenant-scoped.
         *
         *     Returns only events with ``org_id == tenant.org_id``. A task that
         *     belongs to another tenant (or does not exist at all) yields an empty
         *     timeline rather than 404 -- this matches the response shape callers
         *     expect for newly-dispatched tasks before any events have landed,
         *     while still preventing cross-tenant data leak.
         */
        get: operations["get_task_timeline_api_v1_events_tasks__task_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/metrics/dashboard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Metrics Dashboard
         * @description Return aggregated ops metrics for the dashboard.
         */
        get: operations["get_metrics_dashboard_api_v1_metrics_dashboard_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/metrics/roi": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Roi Dashboard
         * @description ROI dashboard: per-agent revenue vs cost.
         *
         *     Currently returns cost-side data from ComputeTokenLedger.
         *     Revenue attribution (Phase 4 RevenueAttribution model) will be
         *     added when the model and webhook wiring are complete.
         */
        get: operations["get_roi_dashboard_api_v1_metrics_roi_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/convergence/ai-tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Ai Tasks
         * @description AI-task metrics for the executive convergence dashboard (converge-dash).
         */
        get: operations["list_ai_tasks_api_v1_convergence_ai_tasks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Connected Users
         * @description List currently connected users via Redis.
         *
         *     The Colyseus server publishes player state to Redis. We read the
         *     latest snapshot here. Returns an empty list if Redis is unavailable.
         */
        get: operations["list_connected_users_api_v1_admin_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/kick": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Kick User
         * @description Publish a kick action to Redis for the Colyseus server to execute.
         */
        post: operations["kick_user_api_v1_admin_kick_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/room-config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Update Room Config
         * @description Update room configuration via Redis pub/sub.
         */
        post: operations["update_room_config_api_v1_admin_room_config_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/consent-ledger/promote-key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Promote Signing Key
         * @description Promote a new HMAC key for the consent ledger (atomic rotation).
         *
         *     Flow inside a single transaction:
         *
         *     1. Find the currently-active key row (``is_current=true``). May be
         *        NULL on a fresh install where the bootstrap inserted a
         *        placeholder. That's OK — we just promote without a retiring step.
         *     2. Mark it ``is_current=false`` + ``retired_at=NOW()``.
         *     3. Insert a new row with ``is_current=true`` and the next
         *        ``key_version`` (max + 1; falls back to 2 when only the v1
         *        bootstrap exists, which is the common case).
         *     4. Emit a ``consent_ledger.key_promoted`` audit event. The new
         *        version is in the payload; the key value is NEVER.
         *
         *     The Postgres partial unique index would catch step 3 attempting to
         *     insert while step 2's flip hasn't committed (would raise
         *     IntegrityError). On SQLite (test backend) the index is skipped
         *     and the test relies on the in-transaction ordering instead.
         *
         *     Returns 503 when the registry is in an unexpected state (e.g. >1
         *     current row before the flip — shouldn't happen with the partial
         *     unique index, but we surface it rather than silently overwrite).
         */
        post: operations["promote_signing_key_api_v1_admin_consent_ledger_promote_key_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Audit Logs
         * @description List audit logs with pagination and optional filters. Admin only.
         */
        get: operations["list_audit_logs_api_v1_audit__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Audit Logs
         * @description Export audit logs as CSV. Admin only. Max 10,000 rows.
         */
        get: operations["export_audit_logs_api_v1_audit_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/unified/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Unified Audit
         * @description Return a merged, timestamp-DESC-ordered stream across the 4 Selva ledgers.
         *
         *     Query strategy: we fetch ``limit + 1`` rows from each requested source,
         *     merge in Python, sort, then slice to ``limit``. For ``limit=500`` and four
         *     sources that's up to 2004 rows materialized per request, which is bounded
         *     and cheap given the ``ix_*_audit_created`` indexes. If we ever need
         *     > 500-row pages we'll switch to an async heap-merge iterator.
         *
         *     The ``next_cursor`` is the oldest timestamp we returned; the client passes
         *     it back as ``cursor`` on the next call to page strictly older.
         */
        get: operations["list_unified_audit_api_v1_audit_unified__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/unified": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Unified Audit
         * @description Return a merged, timestamp-DESC-ordered stream across the 4 Selva ledgers.
         *
         *     Query strategy: we fetch ``limit + 1`` rows from each requested source,
         *     merge in Python, sort, then slice to ``limit``. For ``limit=500`` and four
         *     sources that's up to 2004 rows materialized per request, which is bounded
         *     and cheap given the ``ix_*_audit_created`` indexes. If we ever need
         *     > 500-row pages we'll switch to an async heap-merge iterator.
         *
         *     The ``next_cursor`` is the oldest timestamp we returned; the client passes
         *     it back as ``cursor`` on the next call to page strictly older.
         */
        get: operations["list_unified_audit_api_v1_audit_unified_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/sales": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sales Pipeline Metrics
         * @description Sales pipeline metrics: task counts and average duration for sales graph.
         */
        get: operations["sales_pipeline_metrics_api_v1_analytics_sales_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/accounting": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Accounting Close Status
         * @description Accounting monthly close status: task progress for accounting graph.
         */
        get: operations["accounting_close_status_api_v1_analytics_accounting_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/intelligence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Intelligence Summary
         * @description Intelligence briefing summary: count of briefings and data points.
         */
        get: operations["intelligence_summary_api_v1_analytics_intelligence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Tenant
         * @description Provision a new tenant org with Mexican business defaults.
         *
         *     Creates the TenantConfig record and auto-generates Mexican department
         *     structure (Direccion General, Administracion, Contabilidad, Ventas,
         *     Operaciones, Legal).
         *
         *     If an RFC is provided it is validated structurally and optionally via
         *     Karafiel when configured.
         */
        post: operations["create_tenant_api_v1_tenants__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get My Tenant
         * @description Get the current user's tenant config.
         */
        get: operations["get_my_tenant_api_v1_tenants_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update My Tenant
         * @description Update tenant settings (locale, timezone, currency, feature flags, limits).
         *
         *     Business identity fields (rfc, razon_social, regimen_fiscal) are
         *     immutable after creation to ensure audit trail integrity.
         */
        patch: operations["update_my_tenant_api_v1_tenants_me_patch"];
        trace?: never;
    };
    "/api/v1/tenants/me/usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Tenant Usage
         * @description Get current tenant usage stats against configured limits.
         *
         *     Returns agent count, daily task count, and department count alongside
         *     the configured limits from TenantConfig.
         */
        get: operations["tenant_usage_api_v1_tenants_me_usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/me/sso": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Configure Sso
         * @description Configure enterprise SSO connection for this tenant.
         *
         *     Stores the Janua connection ID so that users in this org are redirected
         *     to the correct IdP during authentication.  Requires admin role.
         */
        patch: operations["configure_sso_api_v1_tenants_me_sso_patch"];
        trace?: never;
    };
    "/api/v1/tenants/me/branding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Branding
         * @description Get tenant branding config for white-label UI.
         *
         *     Returns sensible defaults when the tenant has no custom branding.
         */
        get: operations["get_branding_api_v1_tenants_me_branding_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Branding
         * @description Update white-label branding for this tenant.
         *
         *     Only non-null fields in the request body are applied.  Requires admin role.
         */
        patch: operations["update_branding_api_v1_tenants_me_branding_patch"];
        trace?: never;
    };
    "/api/v1/tenant-identities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Tenant Identity
         * @description Create a tenant_identities row — call at end of onboarding.
         */
        post: operations["create_tenant_identity_api_v1_tenant_identities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenant-identities/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Resolve Tenant Identity
         * @description Resolve a tenant by any per-service id.
         */
        get: operations["resolve_tenant_identity_api_v1_tenant_identities_resolve_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenant-identities/{canonical_id}/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Validate Tenant Consistency
         * @description Run consistency checks between tenant-identity and tenant-config rows.
         *
         *     Current implementation validates:
         *
         *     - The tenant row exists in both tenant_identities and tenant_configs.
         *     - Per-service canonical IDs remain in sync with tenant_configs.
         *     - PII and metadata fields are never echoed (only service-id drift
         *       summaries are returned).
         *
         *     Additional external service probes (Janua/Dhanam/PhyndCRM/Karafiel/Resend)
         *     are tracked separately in the operator backlog.
         */
        post: operations["validate_tenant_consistency_api_v1_tenant_identities__canonical_id__validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice/transcribe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Transcribe Audio
         * @description Transcribe uploaded audio via the OpenAI Whisper API.
         *
         *     Accepts common audio formats (webm, wav, mp3, ogg, flac, m4a).
         *     Returns the transcription text and requested language.
         */
        post: operations["transcribe_audio_api_v1_voice_transcribe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice/dispatch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Voice Dispatch
         * @description Create a SwarmTask from transcribed voice input.
         *
         *     This endpoint accepts text (typically from a prior ``/transcribe`` call)
         *     and dispatches it as a new task via the swarms subsystem.
         */
        post: operations["voice_dispatch_api_v1_voice_dispatch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/onboarding/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Onboarding Status
         * @description Return whether the org has chosen a voice mode yet.
         *
         *     Used by the UI to decide between routing the user to `/onboarding`
         *     or letting them into `/office`.
         */
        get: operations["onboarding_status_api_v1_onboarding_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/onboarding/office-size": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Office Size
         * @description Return the tenant's chosen office-size band (NULL until chosen).
         */
        get: operations["get_office_size_api_v1_onboarding_office_size_get"];
        /**
         * Set Office Size
         * @description Persist the tenant's office-size band. Advisory — never gates access.
         *
         *     Upserts the ``tenant_configs`` row for the caller's org so onboarding
         *     works before any other tenant config exists.
         */
        put: operations["set_office_size_api_v1_onboarding_office_size_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/onboarding/voice-mode/preview/{mode}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Voice Mode Preview
         * @description Return the clause text + heads-up for a single mode (read-only).
         */
        get: operations["voice_mode_preview_api_v1_onboarding_voice_mode_preview__mode__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/onboarding/tenant-identity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Tenant Identity
         * @description Return the server-controlled outbound identity for the caller's tenant.
         *
         *     Used by ``SendEmailTool`` and ``SendMarketingEmailTool`` to populate
         *     the ``From:`` header without trusting LLM-supplied kwargs. The LLM
         *     has no input on what address goes into the From header — sender
         *     identity is exclusively a server concern, sourced from the tenant's
         *     own configuration.
         *
         *     Returns 403 for the unscoped ``platform`` org (worker tokens calling
         *     without ``X-Selva-Tenant-Org``). Returns 404 when the tenant has no
         *     ``tenant_configs`` row at all (i.e. truly unprovisioned). Returns
         *     200 with nullable fields when the tenant exists but has not yet
         *     populated the relevant fields — callers are expected to fail-closed
         *     on missing fields rather than substituting LLM-supplied defaults.
         */
        get: operations["tenant_identity_api_v1_onboarding_tenant_identity_get"];
        /**
         * Update Tenant Identity
         * @description Tenant-side update of outbound identity columns on tenant_configs.
         *
         *     Lets tenants configure From: header inputs from the office settings
         *     UI without requiring MADFAM ops to populate tenant_identities. The
         *     ``org_id`` is forced from the JWT (matching every other tenant-
         *     scoped mutation) — request bodies cannot specify it.
         *
         *     Submitting ``null`` for a field clears it (the legacy fallback
         *     chain takes over on the next email send). Omitting a field leaves
         *     the existing value untouched (uses ``exclude_unset=True``).
         *
         *     Validation:
         *
         *     - ``outbound_user_email``: must match ``[^@\s]+@[^@\s]+\.[^@\s]+``.
         *     - ``outbound_agent_slug``: must be in the 5-entry email-tool
         *       allow-list (sales/support/growth/ops/research).
         *     - ``outbound_user_name``: trimmed; max 255 chars (Pydantic).
         *
         *     Audit: emits ``tenant_identity.updated`` to ``task_events`` with
         *     ``event_category="onboarding"`` so the change is in the audit
         *     trail. Payload includes the keys that changed but not the values
         *     (avoid leaking PII into the event log).
         */
        put: operations["update_tenant_identity_api_v1_onboarding_tenant_identity_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/onboarding/voice-mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Select Voice Mode
         * @description First-run voice-mode selection during onboarding.
         *
         *     Fails with 409 if the tenant has already chosen a mode — use
         *     PUT /settings/outbound-voice to change it.
         *
         *     Idempotency: when the caller sends ``Idempotency-Key`` header, a
         *     successful first-run selection is cached for 24h scoped by (org_id,
         *     POST, /api/v1/onboarding/voice-mode, key). Without this, a network
         *     blip on the first call would have the second call hit the 409
         *     "already selected" branch (because the first call did persist the
         *     consent ledger row + tenant_config update before the response was
         *     lost). Only the success path is cached — a 400 (typed-confirmation
         *     mismatch) or 409 (already resolved) leaves the cache empty.
         */
        post: operations["select_voice_mode_api_v1_onboarding_voice_mode_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings/outbound-voice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Change Voice Mode
         * @description Change the tenant's voice mode from the /office modal.
         *
         *     Appends a new `voice_mode.changed` row to the consent ledger (never
         *     overwrites the previous selection — the ledger is append-only).
         */
        put: operations["change_voice_mode_api_v1_settings_outbound_voice_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/schedules/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Schedules
         * @description Return all schedules owned by the authenticated user.
         */
        get: operations["list_schedules_api_v1_schedules__get"];
        put?: never;
        /**
         * Create Schedule
         * @description Create a recurring schedule.  The Celery Beat scheduler dynamically
         *     picks up new entries via the ``schedules`` Postgres table.
         */
        post: operations["create_schedule_api_v1_schedules__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/schedules/{schedule_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Cancel Schedule
         * @description Cancel (delete) a schedule. Users may only cancel their own; admins may cancel any.
         */
        delete: operations["cancel_schedule_api_v1_schedules__schedule_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/scheduled-actions/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Scheduled Actions */
        get: operations["list_scheduled_actions_api_v1_scheduled_actions__get"];
        put?: never;
        /**
         * Create Scheduled Action
         * @description Enqueue a single due-row for the worker social_post executor.
         */
        post: operations["create_scheduled_action_api_v1_scheduled_actions__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/scheduled-actions/batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Scheduled Action Batch */
        post: operations["create_scheduled_action_batch_api_v1_scheduled_actions_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/scheduled-actions/{action_id}/hitl": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Hitl Status
         * @description Approve or deny a playbook-gated scheduled social post.
         */
        patch: operations["update_hitl_status_api_v1_scheduled_actions__action_id__hitl_patch"];
        trace?: never;
    };
    "/api/v1/scheduled-actions/campaign-social": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Schedule Campaign Social Posts
         * @description Schedule a Tulana campaign social cadence (Phase 2.5).
         */
        post: operations["schedule_campaign_social_posts_api_v1_scheduled_actions_campaign_social_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dragon-eggs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Eggs
         * @description List eggs, optionally filtered by status / platform / owner_org_id.
         */
        get: operations["list_eggs_api_v1_dragon_eggs_get"];
        put?: never;
        /**
         * Lay Egg
         * @description Lay a new egg + generate its 7-day warmup action plan.
         *
         *     Returns the full egg detail (egg + actions) so the UI doesn't
         *     need a follow-up GET to render the timeline.
         */
        post: operations["lay_egg_api_v1_dragon_eggs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dragon-eggs/{egg_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Egg
         * @description Show a single egg with its full action timeline + computed progress.
         */
        get: operations["get_egg_api_v1_dragon_eggs__egg_id__get"];
        put?: never;
        post?: never;
        /**
         * Release Egg
         * @description Release the egg — either force-promote to a status or delete entirely.
         */
        delete: operations["release_egg_api_v1_dragon_eggs__egg_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dragon-eggs/{egg_id}/transition": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Transition Egg
         * @description Manually advance the egg's status based on completed actions.
         *
         *     Useful when the worker is paused or when the operator wants to
         *     sanity-check the state machine after a manual action update.
         */
        post: operations["transition_egg_api_v1_dragon_eggs__egg_id__transition_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dragon-eggs/{egg_id}/actions/{action_id}/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Execute Action
         * @description Mark an action ready for immediate worker dispatch.
         *
         *     Phase 1 semantics: this flips ``status`` from
         *     ``planned``/``pending_human`` → ``in_flight`` and updates
         *     ``scheduled_for`` to NOW. The worker's drain query picks it up
         *     on the next tick and dispatches the matching social tool. The
         *     response is the *pre-dispatch* row state — the operator polls
         *     ``GET /{egg_id}`` to watch the action complete.
         *
         *     HITL action types (``profile_setup``, ``follow_curated``,
         *     ``boost_high_signal``, ``reply_substantive``) are documented as
         *     Phase 1.5 — calling execute on them flips them to ``in_flight``
         *     but the worker will currently NOT dispatch them; ops marks them
         *     completed by hand. Phase 1.5 wires the HITL-approval queue at
         *     that step.
         */
        post: operations["execute_action_api_v1_dragon_eggs__egg_id__actions__action_id__execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dragon-eggs/{egg_id}/actions/{action_id}/skip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Skip Action
         * @description Operator override: mark an action ``skipped`` (counts toward progress).
         */
        post: operations["skip_action_api_v1_dragon_eggs__egg_id__actions__action_id__skip_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/command-approvals/pending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Pending
         * @description List all pending dangerous command approval requests.
         */
        get: operations["list_pending_api_v1_command_approvals_pending_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/command-approvals/{request_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Approve Command
         * @description Approve a pending dangerous command.
         */
        post: operations["approve_command_api_v1_command_approvals__request_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/command-approvals/{request_id}/deny": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Deny Command
         * @description Deny a pending dangerous command.
         */
        post: operations["deny_command_api_v1_command_approvals__request_id__deny_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trajectories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Trajectories
         * @description List all exportable ACP run IDs.
         */
        get: operations["list_trajectories_api_v1_trajectories_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trajectories/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Trajectory
         * @description Return a single ShareGPT-format trajectory for *run_id*.
         */
        get: operations["get_trajectory_api_v1_trajectories__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trajectories/batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Export Batch
         * @description Export multiple trajectories as a JSONL file download.
         *
         *     Body: {"run_ids": ["abc", "def"], "format": "sharegpt"}
         */
        post: operations["export_batch_api_v1_trajectories_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/checkpoints/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Checkpoints
         * @description List all phase checkpoints for an ACP run.
         */
        get: operations["list_checkpoints_api_v1_checkpoints__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/checkpoints/{run_id}/{phase}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Checkpoint
         * @description Retrieve the state snapshot for a specific phase of a run.
         */
        get: operations["get_checkpoint_api_v1_checkpoints__run_id___phase__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/checkpoints/{run_id}/{phase}/rollback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rollback To Phase
         * @description Restore the ACP run state to a previous phase checkpoint and re-queue
         *     the workflow from that phase.
         */
        post: operations["rollback_to_phase_api_v1_checkpoints__run_id___phase__rollback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/hub/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Browse Hub
         * @description Browse community skills on agentskills.io.
         */
        get: operations["browse_hub_api_v1_skills_hub__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/hub/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search Hub
         * @description Full-text search the agentskills.io hub.
         */
        get: operations["search_hub_api_v1_skills_hub_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/skills/hub/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Install Skill
         * @description Download and install a skill from agentskills.io.
         */
        post: operations["install_skill_api_v1_skills_hub_install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/playbooks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Playbooks
         * @description List all playbooks.
         */
        get: operations["list_playbooks_api_v1_playbooks_get"];
        put?: never;
        /**
         * Create Playbook
         * @description Create a new playbook.
         */
        post: operations["create_playbook_api_v1_playbooks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/playbooks/match": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Match Playbook
         * @description Find a matching enabled playbook for a trigger event.
         *
         *     Used by HeartbeatService and webhook handlers to resolve which
         *     playbook (if any) should gate an auto-dispatched task.
         */
        get: operations["match_playbook_api_v1_playbooks_match_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/playbooks/{playbook_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Playbook
         * @description Get a playbook by ID.
         */
        get: operations["get_playbook_api_v1_playbooks__playbook_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Playbook
         * @description Delete a playbook.
         */
        delete: operations["delete_playbook_api_v1_playbooks__playbook_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Playbook
         * @description Update a playbook.
         */
        patch: operations["update_playbook_api_v1_playbooks__playbook_id__patch"];
        trace?: never;
    };
    "/api/v1/gateway/phynd-crm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Phynd Crm Webhook
         * @description Receive webhook events from PhyndCRM and auto-dispatch agent tasks.
         *
         *     Flow:
         *     1. Verify HMAC signature
         *     2. Map CRM event to internal event key
         *     3. Look up matching playbook via /api/v1/playbooks/match
         *     4. If playbook found and enabled → dispatch SwarmTask with playbook_id
         *     5. If no playbook → acknowledge but don't dispatch
         */
        post: operations["phynd_crm_webhook_api_v1_gateway_phynd_crm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/import-tulana-pack": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Tulana Pack
         * @description Validate and rank Tulana SKU campaign packs; optionally enqueue planning tasks.
         */
        post: operations["import_tulana_pack_api_v1_campaigns_import_tulana_pack_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/crm-handoff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Crm Campaign Handoff
         * @description Stage human-approved campaign drafts for Phynd CRM handoff (Phase 2.4).
         */
        post: operations["crm_campaign_handoff_api_v1_campaigns_crm_handoff_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/generate-copy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Campaign Generate Copy
         * @description Generate governed campaign copy variants from a Tulana SKU pack.
         *
         *     Campaign-copy skill (Phase 2.7): copy is grounded ONLY in claims marked
         *     ``campaign_safe`` in the pack's claims register; packs without any
         *     campaign-permitted claims are refused with a structured 422
         *     (``no_campaign_safe_claims``). Each variant reports the claim keys it
         *     used for auditability. Output defaults to es-MX; English is opt-in.
         *
         *     Channels: ``email`` (subject + preheader + body + cta) and
         *     ``social_post`` (body + cta only, for schedule-social → Mastodon /
         *     Bluesky / Reddit). Social bodies must fit ``max_chars`` (default 300 =
         *     Bluesky; Mastodon allows 500); an over-length body is re-prompted once
         *     and then dropped with a reason in ``dropped_variants`` — same claims
         *     discipline on every channel.
         */
        post: operations["campaign_generate_copy_api_v1_campaigns_generate_copy_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/schedule-social": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Campaign Schedule Social
         * @description Schedule campaign social posts for worker drain (Phase 2.5).
         */
        post: operations["campaign_schedule_social_api_v1_campaigns_schedule_social_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/tulana-feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Tulana Campaign Feedback
         * @description Push validated campaign outcomes to Tulana buyer-signal API (Phase 2.6).
         */
        post: operations["tulana_campaign_feedback_api_v1_campaigns_tulana_feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/authorizations/pending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Pending */
        get: operations["pending_api_v1_campaigns_authorizations_pending_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/authorizations/{authorization_id}/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Preview */
        get: operations["preview_api_v1_campaigns_authorizations__authorization_id__preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/authorizations/{authorization_id}/decide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide */
        post: operations["decide_api_v1_campaigns_authorizations__authorization_id__decide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campaigns/authorizations/request": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Request Fresh */
        post: operations["request_fresh_api_v1_campaigns_authorizations_request_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/stripe/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Stripe Webhook
         * @description Verify Stripe signature; dispatch event to per-type handlers.
         */
        post: operations["stripe_webhook_api_v1_stripe_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/probe/draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Probe Draft
         * @description Dry-run drafter. Never calls the real LLM.
         *
         *     Returns a deterministic, non-sentinel draft body so the probe's
         *     "didn't return ``[LLM unavailable``" check passes. Under ``dry_run=False``
         *     the implementation would route through the ModelRouter; keeping dry-run
         *     as the only path here means this endpoint cannot accidentally bill.
         */
        post: operations["probe_draft_api_v1_probe_draft_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/probe/email/send": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Probe Email Send
         * @description Dry-run email-send contract validator.
         *
         *     Sanitises the HTML, returns the full shape the probe asserts on, and
         *     never dispatches to Resend. The CLAUDE.md v2.1.1 contract requires
         *     list-unsubscribe + sanitised HTML + fixed ``from_address``; this
         *     endpoint is where the probe catches any regression.
         */
        post: operations["probe_email_send_api_v1_probe_email_send_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/probe/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Probe Run
         * @description Persist a freshly-run probe report for the status page.
         *
         *     The probe CronJob POSTs its final ``ProbeReport.to_dict()`` here. We
         *     stash the latest run in a single Redis key + append to a capped
         *     history list. Redis failures are logged but do not surface to the
         *     probe (the probe's health is defined by its own stages, not by
         *     whether Nexus can persist its report).
         */
        post: operations["upload_probe_run_api_v1_probe_runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/probe/latest-run": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Latest Probe Run
         * @description Public read of the most recent probe run.
         *
         *     Intentionally unauthenticated: selva.town ``/status`` server-renders
         *     this on every page load (with a short ``revalidate``) so the token
         *     never needs to reach the browser. Returns ``null`` when no run has
         *     been uploaded yet — the page handles the empty state client-side.
         */
        get: operations["get_latest_probe_run_api_v1_probe_latest_run_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/probe/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Probe History
         * @description Recent probe runs, newest first. Public (same rationale as latest-run).
         *
         *     Capped at ``HISTORY_MAX_LEN`` rows. The status page uses this for a
         *     mini sparkline showing the ok/fail pattern across recent hours.
         */
        get: operations["get_probe_history_api_v1_probe_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Provider Balances
         * @description Return the most recent cached balance for every known LLM provider.
         *
         *     The cache is populated by the 15-min cron at
         *     ``apps/workers/selva_workers/jobs/provider_balance_probe.py``.
         *
         *     Behaviour when the cache is empty / Redis is unreachable:
         *     - Returns one entry per provider in ``KNOWN_PROVIDERS`` with
         *       ``source='unknown'`` and ``alert='critical'``.
         *     - 200 OK, never 5xx — the goal is to surface the missing signal,
         *       not hide it behind a server error.
         */
        get: operations["get_provider_balances_api_v1_providers_balance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/hitl/decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Decisions
         * @description Recent HITL decisions with filters. Observe-only; no mutation path.
         */
        get: operations["list_decisions_api_v1_hitl_decisions_get"];
        put?: never;
        /**
         * Record Decision
         * @description Record a HITL decision into the append-only log + roll the bucket.
         */
        post: operations["record_decision_api_v1_hitl_decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/hitl/confidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Confidence
         * @description Admin dashboard over all buckets. Filterable, capped.
         */
        get: operations["list_confidence_api_v1_hitl_confidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/a2a/.well-known/agent.json": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Agent Card
         * @description Return the agent discovery card.
         */
        get: operations["agent_card_api_v1_a2a__well_known_agent_json_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/a2a/tasks/send": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Send Task
         * @description Accept a task from an external agent (one-shot).
         */
        post: operations["send_task_api_v1_a2a_tasks_send_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/a2a/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Task
         * @description Poll the status of an A2A task.
         */
        get: operations["get_task_api_v1_a2a_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/a2a/tasks/sendSubscribe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Send Subscribe
         * @description Accept a task and stream status updates via SSE.
         */
        post: operations["send_subscribe_api_v1_a2a_tasks_sendSubscribe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccountingCloseStatus */
        AccountingCloseStatus: {
            /**
             * Period
             * @default
             */
            period: string;
            /**
             * Total Accounting Tasks
             * @default 0
             */
            total_accounting_tasks: number;
            /**
             * Completed
             * @default 0
             */
            completed: number;
            /**
             * Pending
             * @default 0
             */
            pending: number;
            /**
             * Failed
             * @default 0
             */
            failed: number;
            /** Last Completed At */
            last_completed_at?: string | null;
        };
        /** AgentAssign */
        AgentAssign: {
            /** Department Id */
            department_id: string;
        };
        /**
         * AgentCard
         * @description Agent discovery metadata served at ``/.well-known/agent.json``.
         *
         *     External frameworks (CrewAI, LangGraph, MS Agent Framework) use this
         *     to discover what this agent can do and how to call it.
         */
        AgentCard: {
            /**
             * Name
             * @default Selva Office
             */
            name: string;
            /**
             * Description
             * @default AI-powered virtual office with autonomous agent swarms
             */
            description: string;
            /**
             * Url
             * @default
             */
            url: string;
            /**
             * Version
             * @default 0.7.0
             */
            version: string;
            /** Capabilities */
            capabilities?: string[];
            /** Skills */
            skills?: components["schemas"]["AgentSkill"][];
            /** Authentication */
            authentication?: {
                [key: string]: unknown;
            };
        };
        /** AgentCreate */
        AgentCreate: {
            /** Name */
            name: string;
            /**
             * Role
             * @default coder
             */
            role: string;
            /**
             * Level
             * @default 1
             */
            level: number;
            /** Department Id */
            department_id?: string | null;
            /** Skill Ids */
            skill_ids?: string[] | null;
        };
        /** AgentListResponse */
        AgentListResponse: {
            /** Items */
            items: components["schemas"]["AgentResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** AgentResponse */
        AgentResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Role */
            role: string;
            /** Status */
            status: string;
            /** Level */
            level: number;
            /** Department Id */
            department_id: string | null;
            /** Current Task Id */
            current_task_id: string | null;
            /** Skill Ids */
            skill_ids: string[] | null;
            /** Effective Skills */
            effective_skills: string[];
            /** Synergy Data */
            synergy_data: {
                [key: string]: unknown;
            } | null;
            /**
             * Tasks Completed
             * @default 0
             */
            tasks_completed: number;
            /**
             * Tasks Failed
             * @default 0
             */
            tasks_failed: number;
            /**
             * Approval Success Count
             * @default 0
             */
            approval_success_count: number;
            /**
             * Approval Denial Count
             * @default 0
             */
            approval_denial_count: number;
            /** Avg Task Duration Seconds */
            avg_task_duration_seconds?: number | null;
            /** Last Task At */
            last_task_at?: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * AgentSkill
         * @description A single capability advertised by an agent.
         */
        AgentSkill: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Tags */
            tags?: string[];
        };
        /**
         * AgentStatsUpdate
         * @description Delta increments for agent performance stats. Worker-to-API.
         */
        AgentStatsUpdate: {
            /**
             * Tasks Completed Delta
             * @default 0
             */
            tasks_completed_delta: number;
            /**
             * Tasks Failed Delta
             * @default 0
             */
            tasks_failed_delta: number;
            /**
             * Approval Success Delta
             * @default 0
             */
            approval_success_delta: number;
            /**
             * Approval Denial Delta
             * @default 0
             */
            approval_denial_delta: number;
            /** Task Duration Seconds */
            task_duration_seconds?: number | null;
        };
        /** AgentSummary */
        AgentSummary: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Role */
            role: string;
            /** Status */
            status: string;
            /** Level */
            level: number;
            /** Current Task Id */
            current_task_id?: string | null;
            /**
             * Effective Skills
             * @default []
             */
            effective_skills: string[];
        };
        /** AgentUpdate */
        AgentUpdate: {
            /** Name */
            name?: string | null;
            /** Role */
            role?: string | null;
            /** Status */
            status?: string | null;
            /** Level */
            level?: number | null;
            /** Skill Ids */
            skill_ids?: string[] | null;
        };
        /** ApprovalAction */
        ApprovalAction: {
            /** Feedback */
            feedback?: string | null;
        };
        /** ApprovalListResponse */
        ApprovalListResponse: {
            /** Items */
            items: components["schemas"]["nexus_api__routers__approvals__ApprovalRequestResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /**
         * ApprovalStatus
         * @description Status for dangerous-command approval requests.
         * @enum {string}
         */
        ApprovalStatus: "pending" | "approved" | "denied" | "expired";
        /** ArtifactListResponse */
        ArtifactListResponse: {
            /** Artifacts */
            artifacts: components["schemas"]["ArtifactResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** ArtifactResponse */
        ArtifactResponse: {
            /** Id */
            id: string;
            /** Task Id */
            task_id: string | null;
            /** Agent Id */
            agent_id: string | null;
            /** Name */
            name: string;
            /** Content Type */
            content_type: string;
            /** Content Hash */
            content_hash: string;
            /** Size Bytes */
            size_bytes: number;
            /** Metadata */
            metadata: {
                [key: string]: unknown;
            } | null;
            /** Created At */
            created_at: string;
        };
        /** AuditLogListResponse */
        AuditLogListResponse: {
            /** Items */
            items: components["schemas"]["AuditLogResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** AuditLogResponse */
        AuditLogResponse: {
            /** Id */
            id: string;
            /** Org Id */
            org_id: string;
            /** User Id */
            user_id: string;
            /** Action */
            action: string;
            /** Resource Type */
            resource_type: string;
            /** Resource Id */
            resource_id: string | null;
            /** Details */
            details: {
                [key: string]: unknown;
            } | null;
            /** Ip Address */
            ip_address: string | null;
            /** Created At */
            created_at: string;
        };
        /** BatchExportRequest */
        BatchExportRequest: {
            /** Run Ids */
            run_ids: string[];
            /**
             * Format
             * @default sharegpt
             */
            format: string;
        };
        /** Body_transcribe_audio_api_v1_voice_transcribe_post */
        Body_transcribe_audio_api_v1_voice_transcribe_post: {
            /** File */
            file: string;
        };
        /**
         * BrandingConfig
         * @description White-label branding settings for the office UI.
         */
        BrandingConfig: {
            /** Brand Name */
            brand_name?: string | null;
            /** Brand Logo Url */
            brand_logo_url?: string | null;
            /** Brand Primary Color */
            brand_primary_color?: string | null;
        };
        /** BucketView */
        BucketView: {
            /** Bucket Key */
            bucket_key: string;
            /** Agent Id */
            agent_id: string | null;
            /** Action Category */
            action_category: string;
            /** Org Id */
            org_id: string;
            /** Context Signature */
            context_signature: string;
            /** N Observed */
            n_observed: number;
            /** N Approved Clean */
            n_approved_clean: number;
            /** N Approved Modified */
            n_approved_modified: number;
            /** N Rejected */
            n_rejected: number;
            /** N Timeout */
            n_timeout: number;
            /** N Reverted */
            n_reverted: number;
            /** Confidence */
            confidence: number;
            tier: components["schemas"]["HitlConfidenceTier"];
            /** Last Decision At */
            last_decision_at: string | null;
        };
        /** BudgetResponse */
        BudgetResponse: {
            /** Daily Limit */
            daily_limit: number;
            /** Used */
            used: number;
            /** Remaining */
            remaining: number;
            /** Over Budget */
            over_budget: boolean;
        };
        /**
         * BulkExpireResponse
         * @description Response from the bulk-expire endpoint.
         */
        BulkExpireResponse: {
            /**
             * Expired
             * @description Number of approvals marked expired
             * @default 0
             */
            expired: number;
        };
        /**
         * CalendarEventResponse
         * @description Public representation of a calendar event.
         */
        CalendarEventResponse: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Start */
            start: string;
            /** End */
            end: string;
            /** Is All Day */
            is_all_day: boolean;
            /** Meeting Url */
            meeting_url: string | null;
            /** Organizer */
            organizer: string;
            /** Attendees */
            attendees: string[];
            /** Provider */
            provider: string;
        };
        /**
         * CalendarEventsListResponse
         * @description List of calendar events.
         */
        CalendarEventsListResponse: {
            /** Events */
            events: components["schemas"]["CalendarEventResponse"][];
            /** Is Busy */
            is_busy: boolean;
        };
        /**
         * CalendarProvider
         * @description Supported calendar providers.
         * @enum {string}
         */
        CalendarProvider: "google" | "microsoft";
        /**
         * CalendarStatusResponse
         * @description Response for calendar connection status.
         */
        CalendarStatusResponse: {
            /** Connected */
            connected: boolean;
            /** Provider */
            provider?: string | null;
            /** Connected At */
            connected_at?: string | null;
        };
        /** CampaignCopyRequest */
        CampaignCopyRequest: {
            tulana_pack: components["schemas"]["TulanaSkuCampaignPack"];
            /**
             * Audience
             * @description Audience descriptor (segment, persona, or list description).
             */
            audience: string;
            /**
             * Channel
             * @description Delivery channel. ``email`` for campaign emails; ``social_post`` for short posts destined for schedule-social (Mastodon, Bluesky, Reddit). SMS/WhatsApp are follow-ups.
             * @default email
             * @enum {string}
             */
            channel: "email" | "social_post";
            /**
             * Language
             * @description Output language. es-MX is the MADFAM primary; en is optional.
             * @default es-MX
             * @enum {string}
             */
            language: "es-MX" | "en";
            /**
             * Variant Count
             * @default 3
             */
            variant_count: number;
            /**
             * Tone
             * @description Optional tone hint (e.g. 'directo y profesional').
             */
            tone?: string | null;
            /**
             * Max Chars
             * @description social_post only: hard ceiling for each post body. Default 300 (Bluesky, the strictest supported target); Mastodon-only batches may raise to 500. Ignored for the email channel.
             * @default 300
             */
            max_chars: number;
        };
        /** CampaignCopyResponse */
        CampaignCopyResponse: {
            /** Sku Key */
            sku_key: string;
            /**
             * Channel
             * @enum {string}
             */
            channel: "email" | "social_post";
            /**
             * Language
             * @enum {string}
             */
            language: "es-MX" | "en";
            /** Audience */
            audience: string;
            /** Variants */
            variants: components["schemas"]["CampaignCopyVariant"][];
            /**
             * Campaign Safe Claim Keys
             * @description Claim keys the generator was permitted to use.
             */
            campaign_safe_claim_keys?: string[];
            /**
             * Excluded Claim Keys
             * @description Claim keys present in the pack but NOT campaign-safe (never used).
             */
            excluded_claim_keys?: string[];
            /**
             * Dropped Variants
             * @description Reasons for generated variants rejected by claims enforcement (non-permitted claim keys, scrub-emptied copy, or over-length social bodies).
             */
            dropped_variants?: string[];
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
        };
        /** CampaignCopyVariant */
        CampaignCopyVariant: {
            /** Variant Id */
            variant_id: string;
            /**
             * Language
             * @enum {string}
             */
            language: "es-MX" | "en";
            /**
             * Subject
             * @description Email subject line. Always set for email; None for social_post.
             */
            subject?: string | null;
            /**
             * Preheader
             * @description Email preheader. Email-only; None for social_post.
             */
            preheader?: string | null;
            /** Body */
            body: string;
            /** Cta */
            cta: string;
            /**
             * Claim Keys Used
             * @description Campaign-safe claim feature_keys grounding this variant (audit trail).
             */
            claim_keys_used?: string[];
            /**
             * Guardrail Violations
             * @description do_not_claim phrases that were scrubbed from this variant.
             */
            guardrail_violations?: string[];
        };
        /** CampaignSocialPostItem */
        CampaignSocialPostItem: {
            /**
             * Scheduled For
             * Format: date-time
             */
            scheduled_for: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
        };
        /** CampaignSocialScheduleRequest */
        CampaignSocialScheduleRequest: {
            /** Sku Key */
            sku_key: string;
            /**
             * Platform
             * @enum {string}
             */
            platform: "mastodon" | "bluesky" | "reddit" | "x" | "linkedin" | "email";
            /** Posts */
            posts: components["schemas"]["CampaignSocialPostItem"][];
            /** Playbook Id */
            playbook_id?: string | null;
            /** Persona Id */
            persona_id?: string | null;
            /** Campaign Id */
            campaign_id?: string | null;
            /**
             * Require Hitl
             * @default true
             */
            require_hitl: boolean;
        };
        /** ChatHistoryResponse */
        ChatHistoryResponse: {
            /** Items */
            items: components["schemas"]["ChatMessageResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** ChatMessageCreate */
        ChatMessageCreate: {
            /** Room Id */
            room_id: string;
            /**
             * Sender Session Id
             * @default
             */
            sender_session_id: string;
            /** Sender Name */
            sender_name: string;
            /** Content */
            content: string;
            /**
             * Is System
             * @default false
             */
            is_system: boolean;
        };
        /** ChatMessageResponse */
        ChatMessageResponse: {
            /** Id */
            id: string;
            /** Room Id */
            room_id: string;
            /** Sender Session Id */
            sender_session_id: string;
            /** Sender Name */
            sender_name: string;
            /** Content */
            content: string;
            /** Is System */
            is_system: boolean;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** CheckoutRequest */
        CheckoutRequest: {
            /** Tier */
            tier: string;
            /**
             * Success Path
             * @default /office?upgraded=1
             */
            success_path: string;
            /**
             * Cancel Path
             * @default /pricing?checkout=cancelled
             */
            cancel_path: string;
        };
        /** CheckpointListItem */
        CheckpointListItem: {
            /** Id */
            id: string;
            /** Phase */
            phase: string;
            /** Phase Index */
            phase_index: number;
            /** Created At */
            created_at: string;
        };
        /** CheckpointState */
        CheckpointState: {
            /** Run Id */
            run_id: string;
            /** Phase */
            phase: string;
            /** State */
            state: {
                [key: string]: unknown;
            };
        };
        /** ConfidenceDashboard */
        ConfidenceDashboard: {
            /** Total Buckets */
            total_buckets: number;
            /** Total Decisions */
            total_decisions: number;
            /** Buckets */
            buckets: components["schemas"]["BucketView"][];
        };
        /**
         * ConnectCalendarRequest
         * @description Request body for connecting a calendar provider.
         */
        ConnectCalendarRequest: {
            provider: components["schemas"]["CalendarProvider"];
            /** Access Token */
            access_token: string;
            /** Refresh Token */
            refresh_token?: string | null;
        };
        /**
         * ConnectResponse
         * @description Response after connecting a calendar.
         */
        ConnectResponse: {
            /**
             * Connected
             * @default true
             */
            connected: boolean;
            /** Provider */
            provider: string;
        };
        /** ConnectedUser */
        ConnectedUser: {
            /** Session Id */
            session_id: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
        };
        /** ConvergenceAiTask */
        ConvergenceAiTask: {
            /** Task Id */
            task_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Agent Name */
            agent_name?: string | null;
            /** Status */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Cost Usd */
            cost_usd?: number | null;
            /** Tokens In */
            tokens_in?: number | null;
            /** Tokens Out */
            tokens_out?: number | null;
            /** Tool Call Count */
            tool_call_count?: number | null;
            /** Human Interventions */
            human_interventions?: number | null;
            /** Error Class */
            error_class?: string | null;
        };
        /** CreateApprovalRequest */
        CreateApprovalRequest: {
            /** Agent Id */
            agent_id: string;
            /** Action Category */
            action_category: string;
            /** Action Type */
            action_type: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /**
             * Reasoning
             * @default
             */
            reasoning: string;
            /**
             * Urgency
             * @default medium
             */
            urgency: string;
            /** Diff */
            diff?: string | null;
        };
        /** CreateEventRequest */
        CreateEventRequest: {
            /** Event Type */
            event_type: string;
            /** Event Category */
            event_category: string;
            /** Task Id */
            task_id?: string | null;
            /** Agent Id */
            agent_id?: string | null;
            /** Node Id */
            node_id?: string | null;
            /** Graph Type */
            graph_type?: string | null;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            } | null;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Provider */
            provider?: string | null;
            /** Model */
            model?: string | null;
            /** Token Count */
            token_count?: number | null;
            /** Error Message */
            error_message?: string | null;
            /** Request Id */
            request_id?: string | null;
        };
        /** CreateFromTemplateRequest */
        CreateFromTemplateRequest: {
            /** Template Filename */
            template_filename: string;
            /** Name */
            name?: string | null;
        };
        /** CrmCampaignHandoffRequest */
        CrmCampaignHandoffRequest: {
            /** Sku Key */
            sku_key: string;
            /** Audience */
            audience: string;
            /** Draft Variants */
            draft_variants: string[];
            tulana_pack: components["schemas"]["TulanaSkuCampaignPack"];
            /** Campaign Name */
            campaign_name?: string | null;
            /** Phynd List Id */
            phynd_list_id?: string | null;
        };
        /** CrmCampaignHandoffResponse */
        CrmCampaignHandoffResponse: {
            /** Handoff Id */
            handoff_id: string;
            /** Task Id */
            task_id: string;
            /**
             * Status
             * @default queued
             */
            status: string;
            /** Message */
            message: string;
        };
        /** DecideRequest */
        DecideRequest: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "authorized" | "rejected";
            /** Note */
            note?: string | null;
        };
        /** DecisionList */
        DecisionList: {
            /** Total */
            total: number;
            /** Decisions */
            decisions: components["schemas"]["DecisionView"][];
        };
        /**
         * DecisionOutcome
         * @description Mirror of `HitlOutcome` — see `confidence.py` docstring rationale.
         * @enum {string}
         */
        DecisionOutcome: "approved_clean" | "approved_modified" | "rejected" | "timeout" | "downstream_reverted";
        /** DecisionView */
        DecisionView: {
            /** Id */
            id: string;
            /** Decided At */
            decided_at: string;
            /** Agent Id */
            agent_id: string | null;
            /** Action Category */
            action_category: string;
            /** Org Id */
            org_id: string;
            /** Bucket Key */
            bucket_key: string;
            outcome: components["schemas"]["HitlOutcome"];
            /** Approver Id */
            approver_id: string | null;
            /** Latency Ms */
            latency_ms: number | null;
            /** Notes */
            notes: string | null;
        };
        /** DepartmentCreate */
        DepartmentCreate: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Max Agents
             * @default 5
             */
            max_agents: number;
            /**
             * Position X
             * @default 0
             */
            position_x: number;
            /**
             * Position Y
             * @default 0
             */
            position_y: number;
        };
        /** DepartmentDetailResponse */
        DepartmentDetailResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /** Description */
            description: string;
            /** Max Agents */
            max_agents: number;
            /** Position X */
            position_x: number;
            /** Position Y */
            position_y: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Agents */
            agents: components["schemas"]["AgentSummary"][];
        };
        /** DepartmentListResponse */
        DepartmentListResponse: {
            /** Items */
            items: components["schemas"]["DepartmentResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** DepartmentResponse */
        DepartmentResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /** Description */
            description: string;
            /** Max Agents */
            max_agents: number;
            /** Position X */
            position_x: number;
            /** Position Y */
            position_y: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** DepartmentUpdate */
        DepartmentUpdate: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
            /** Max Agents */
            max_agents?: number | null;
            /** Position X */
            position_x?: number | null;
            /** Position Y */
            position_y?: number | null;
        };
        /** DeploymentEvidenceRecordListResponse */
        DeploymentEvidenceRecordListResponse: {
            /** Evidence Records */
            evidence_records: components["schemas"]["DeploymentEvidenceRecordResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** DeploymentEvidenceRecordResponse */
        DeploymentEvidenceRecordResponse: {
            /** Id */
            id: string;
            /** Task Id */
            task_id: string;
            /** Graph Type */
            graph_type: string;
            /** Deployment Status */
            deployment_status: string;
            /** Evidence */
            evidence: {
                [key: string]: unknown;
            };
            /** Created At */
            created_at: string;
        };
        /**
         * DisconnectResponse
         * @description Response after disconnecting a calendar.
         */
        DisconnectResponse: {
            /**
             * Disconnected
             * @default true
             */
            disconnected: boolean;
        };
        /** DispatchRequest */
        DispatchRequest: {
            /** Title */
            title?: string | null;
            /** Description */
            description: string;
            /**
             * Graph Type
             * @default sequential
             */
            graph_type: string;
            /** Assigned Agent Ids */
            assigned_agent_ids?: string[];
            /** Required Skills */
            required_skills?: string[];
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /**
             * Kanban Status
             * @default todo
             */
            kanban_status: string;
            /**
             * Priority
             * @default medium
             */
            priority: string;
            /** Labels */
            labels?: string[];
            /** Due Date */
            due_date?: string | null;
            /** Parent Task Id */
            parent_task_id?: string | null;
            /** Depends On */
            depends_on?: string[];
            /**
             * Workflow Id
             * @description UUID of a custom workflow definition (required for graph_type='custom')
             */
            workflow_id?: string | null;
            /**
             * Source
             * @description Canonical task source such as api, webhook, scheduler, or selva-recursive.
             * @default api
             */
            source: string;
            /**
             * Idempotency Key
             * @description Consumer-supplied idempotency key copied into the canonical task envelope.
             */
            idempotency_key?: string | null;
            /**
             * Desired State Hash
             * @description Optional desired-state hash for provisioning/deployment tasks.
             */
            desired_state_hash?: string | null;
        };
        /** DraftRequest */
        DraftRequest: {
            /** Correlation Id */
            correlation_id: string;
            /** Lead Id */
            lead_id: string;
            /**
             * Dry Run
             * @default true
             */
            dry_run: boolean;
        };
        /** DraftResponse */
        DraftResponse: {
            /** Draft */
            draft: string;
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /** Token Count */
            token_count: number;
        };
        /**
         * EggDetailResponse
         * @description Egg + its full action timeline.
         */
        EggDetailResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Persona Id */
            persona_id: string;
            /** Platform */
            platform: string;
            /** Display Name */
            display_name: string;
            /** Handle */
            handle: string;
            /** Instance Url */
            instance_url: string | null;
            /** Status */
            status: string;
            /** Progress */
            progress: number;
            /** Laid At */
            laid_at: string;
            /** Hatched At */
            hatched_at: string | null;
            /** Matured At */
            matured_at: string | null;
            /** Owner Org Id */
            owner_org_id: string;
            /** Created By */
            created_by: string;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
            /** Actions */
            actions?: components["schemas"]["WarmupActionResponse"][];
        };
        /** EggResponse */
        EggResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Persona Id */
            persona_id: string;
            /** Platform */
            platform: string;
            /** Display Name */
            display_name: string;
            /** Handle */
            handle: string;
            /** Instance Url */
            instance_url: string | null;
            /** Status */
            status: string;
            /** Progress */
            progress: number;
            /** Laid At */
            laid_at: string;
            /** Hatched At */
            hatched_at: string | null;
            /** Matured At */
            matured_at: string | null;
            /** Owner Org Id */
            owner_org_id: string;
            /** Created By */
            created_by: string;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
        };
        /** EmailSendRequest */
        EmailSendRequest: {
            /** Correlation Id */
            correlation_id: string;
            /** Lead Id */
            lead_id: string;
            /** Body */
            body: string;
            /**
             * Dry Run
             * @default true
             */
            dry_run: boolean;
        };
        /** EmailSendResponse */
        EmailSendResponse: {
            /** Message Id */
            message_id: string;
            /** From Address */
            from_address: string;
            /** Provider */
            provider: string;
            /** List Unsubscribe Header Present */
            list_unsubscribe_header_present: boolean;
            /** Sanitized Html */
            sanitized_html: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * HitlConfidenceTier
         * @description Promotion ladder. Sprint 1 only ever assigns ASK.
         * @enum {string}
         */
        HitlConfidenceTier: "ask" | "ask_quiet" | "allow_shadow" | "allow";
        /**
         * HitlOutcome
         * @description Terminal outcomes for a HITL decision.
         *
         *     Order matters for the Beta posterior update:
         *         approved_clean      → α += 1.0  (full trust signal)
         *         approved_modified   → α += 0.3, β += 0.7  (partial rejection)
         *         rejected            → β += 1.0
         *         timeout             → β += 0.5  (silence ≠ approval)
         *         downstream_reverted → β += 2.0  (loud negative; demotes buckets)
         * @enum {string}
         */
        HitlOutcome: "approved_clean" | "approved_modified" | "rejected" | "timeout" | "downstream_reverted";
        /** HubSkillResponse */
        HubSkillResponse: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Author */
            author: string;
            /** Version */
            version: string;
            /** Category */
            category: string;
            /** Downloads */
            downloads: number;
            /** Url */
            url: string;
            /** Tags */
            tags: string[];
        };
        /** InstallRequest */
        InstallRequest: {
            /** Skill Name */
            skill_name: string;
            /** Target Dir */
            target_dir?: string | null;
        };
        /**
         * InstallResponse
         * @description Response after installing a skill from the marketplace.
         */
        InstallResponse: {
            /**
             * Installed
             * @default true
             */
            installed: boolean;
            /** Skill Name */
            skill_name: string;
            /** Install Path */
            install_path: string;
        };
        /** IntelligenceSummary */
        IntelligenceSummary: {
            /**
             * Total Briefings
             * @default 0
             */
            total_briefings: number;
            /** Last Briefing At */
            last_briefing_at?: string | null;
            /**
             * Dof Entries Scanned
             * @default 0
             */
            dof_entries_scanned: number;
            /**
             * Indicators Fetched
             * @default 0
             */
            indicators_fetched: number;
            /**
             * Period
             * @default
             */
            period: string;
        };
        /**
         * InvoiceDispatchResponse
         * @description Response after dispatching a billing graph task.
         */
        InvoiceDispatchResponse: {
            /** Task Id */
            task_id: string;
            /** Status */
            status: string;
        };
        /**
         * InvoiceRequest
         * @description Payload for generating a CFDI 4.0 invoice via the billing graph.
         */
        InvoiceRequest: {
            /**
             * Receptor Rfc
             * @description Receptor RFC (12 or 13 chars)
             */
            receptor_rfc: string;
            /**
             * Conceptos
             * @description Line items (clave_prod_serv, descripcion, importe, ...)
             */
            conceptos: {
                [key: string]: unknown;
            }[];
            /**
             * Forma Pago
             * @description SAT forma de pago code
             * @default 01
             */
            forma_pago: string;
            /**
             * Metodo Pago
             * @description PUE or PPD
             * @default PUE
             */
            metodo_pago: string;
            /**
             * Moneda
             * @description Currency code
             * @default MXN
             */
            moneda: string;
            /**
             * Emisor Rfc
             * @description Override emisor RFC (defaults to org config)
             */
            emisor_rfc?: string | null;
            /**
             * Customer Email
             * @description Email for invoice delivery
             */
            customer_email?: string | null;
            /**
             * Customer Phone
             * @description Phone for WhatsApp delivery
             */
            customer_phone?: string | null;
        };
        /**
         * InvoiceStatusResponse
         * @description CFDI status lookup result.
         */
        InvoiceStatusResponse: {
            /** Uuid */
            uuid: string;
            /** Status */
            status: string;
            /** Detail */
            detail?: {
                [key: string]: unknown;
            } | null;
        };
        /** KanbanMetricsResponse */
        KanbanMetricsResponse: {
            /** Total */
            total: number;
            /** Status Counts */
            status_counts: {
                [key: string]: number;
            };
            /** Blocked Count */
            blocked_count: number;
            /** Dependency Blocked Count */
            dependency_blocked_count: number;
            /** Overdue Count */
            overdue_count: number;
            /** Wip Count */
            wip_count: number;
            /** Avg Wip Age Seconds */
            avg_wip_age_seconds: number | null;
            /** Avg Cycle Time Seconds */
            avg_cycle_time_seconds: number | null;
            /** Throughput By Label */
            throughput_by_label: {
                [key: string]: number;
            };
            /** Workload By Assignee */
            workload_by_assignee: {
                [key: string]: number;
            };
        };
        /** KanbanTaskImportResponse */
        KanbanTaskImportResponse: {
            /** Created */
            created: number;
            /** Tasks */
            tasks: components["schemas"]["SwarmTaskResponse"][];
        };
        /** KanbanTaskUpdate */
        KanbanTaskUpdate: {
            /** Title */
            title?: string | null;
            /** Kanban Status */
            kanban_status?: string | null;
            /** Priority */
            priority?: string | null;
            /** Labels */
            labels?: string[] | null;
            /** Due Date */
            due_date?: string | null;
            /** Parent Task Id */
            parent_task_id?: string | null;
            /** Depends On */
            depends_on?: string[] | null;
        };
        /** KickRequest */
        KickRequest: {
            /** Session Id */
            session_id: string;
            /**
             * Reason
             * @default
             */
            reason: string;
        };
        /**
         * LayEggRequest
         * @description Lay a new egg (create a social-account warmup plan).
         */
        LayEggRequest: {
            /**
             * Persona Id
             * @description Selva persona id; matches the existing MASTODON_ACCESS_TOKEN_<PERSONA_ID> env-var convention.
             */
            persona_id: string;
            /**
             * Platform
             * @description One of 'mastodon' | 'bluesky' | 'reddit' (Phase 1 scope).
             */
            platform: string;
            /** Handle */
            handle: string;
            /** Display Name */
            display_name: string;
            /**
             * Instance Url
             * @description Required for Mastodon-style federated platforms; ignored otherwise.
             */
            instance_url?: string | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
        };
        /** ManifestVerifyResponse */
        ManifestVerifyResponse: {
            /** Ok */
            ok: boolean;
            /** Kind */
            kind: string | null;
            /** Api Version */
            api_version: string | null;
            /** Manifest Hash */
            manifest_hash: string | null;
            /** Derived */
            derived: {
                [key: string]: unknown;
            };
            /** Gaps */
            gaps: string[];
            /** Unsupported Placeholders */
            unsupported_placeholders: string[];
        };
        /** MapCreateRequest */
        MapCreateRequest: {
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** Tmj Content */
            tmj_content: string;
        };
        /** MapImportRequest */
        MapImportRequest: {
            /** Tmj Content */
            tmj_content: string;
        };
        /** MapListResponse */
        MapListResponse: {
            /** Items */
            items: components["schemas"]["MapResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** MapResponse */
        MapResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Tmj Content */
            tmj_content: string;
            /** Org Id */
            org_id: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
        };
        /** MapUpdateRequest */
        MapUpdateRequest: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
            /** Tmj Content */
            tmj_content?: string | null;
        };
        /**
         * MarketplaceEntryDetailResponse
         * @description Detailed representation including individual ratings.
         */
        MarketplaceEntryDetailResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Author */
            author: string;
            /** Version */
            version: string;
            /** Readme */
            readme: string | null;
            /** Download Url */
            download_url: string | null;
            /** Category */
            category: string | null;
            /** Tags */
            tags: string[];
            /** Downloads */
            downloads: number;
            /** Avg Rating */
            avg_rating: number | null;
            /** Rating Count */
            rating_count: number;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /** Yaml Content */
            yaml_content: string;
            /** Ratings */
            ratings: components["schemas"]["SkillRatingResponse"][];
        };
        /**
         * MarketplaceEntryResponse
         * @description Public representation of a marketplace skill entry.
         */
        MarketplaceEntryResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Author */
            author: string;
            /** Version */
            version: string;
            /** Readme */
            readme: string | null;
            /** Download Url */
            download_url: string | null;
            /** Category */
            category: string | null;
            /** Tags */
            tags: string[];
            /** Downloads */
            downloads: number;
            /** Avg Rating */
            avg_rating: number | null;
            /** Rating Count */
            rating_count: number;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
        };
        /**
         * MarketplaceListResponse
         * @description Paginated list of marketplace entries.
         */
        MarketplaceListResponse: {
            /** Entries */
            entries: components["schemas"]["MarketplaceEntryResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** MetricsDashboardResponse */
        MetricsDashboardResponse: {
            /** Period */
            period: string;
            /** Agent Utilization Pct */
            agent_utilization_pct: number;
            /** Task Throughput */
            task_throughput: {
                [key: string]: unknown;
            };
            /** Approval Latency */
            approval_latency: {
                [key: string]: unknown;
            };
            /** Cost Breakdown */
            cost_breakdown: {
                [key: string]: unknown;
            }[];
            /** Error Rate */
            error_rate: number;
            /** Trends */
            trends: {
                [key: string]: components["schemas"]["TrendPoint"][];
            };
            /** Recent Errors */
            recent_errors: {
                [key: string]: unknown;
            }[];
        };
        /**
         * ModelAssignmentResponse
         * @description Model assignment without sensitive fields.
         */
        ModelAssignmentResponse: {
            /** Provider */
            provider: string;
            /** Model */
            model: string;
            /**
             * Max Tokens
             * @default 4096
             */
            max_tokens: number;
            /**
             * Temperature
             * @default 0.7
             */
            temperature: number;
        };
        /**
         * OfficeSizeResponse
         * @description The tenant's chosen office-size band (advisory).
         */
        OfficeSizeResponse: {
            /** Office Size */
            office_size: string | null;
        };
        /**
         * OfficeSizeSelection
         * @description Payload for PUT /onboarding/office-size.
         */
        OfficeSizeSelection: {
            /**
             * Office Size
             * @description One of the office-size bands.
             */
            office_size: string;
        };
        /**
         * OnboardingStatus
         * @description Whether the tenant has completed voice-mode onboarding.
         */
        OnboardingStatus: {
            /** Voice Mode */
            voice_mode: string | null;
            /** Onboarding Complete */
            onboarding_complete: boolean;
            /** Clause Version */
            clause_version: string;
        };
        /**
         * OrgConfigResponse
         * @description Org-level inference config — safe for API consumers.
         *
         *     API keys and agent templates are intentionally excluded.
         */
        OrgConfigResponse: {
            /**
             * Providers
             * @default {}
             */
            providers: {
                [key: string]: components["schemas"]["ProviderSummary"];
            };
            /**
             * Model Assignments
             * @default {}
             */
            model_assignments: {
                [key: string]: components["schemas"]["ModelAssignmentResponse"];
            };
            /** Cloud Priority */
            cloud_priority?: string[] | null;
            /** Cheapest Priority */
            cheapest_priority?: string[] | null;
            /**
             * Embedding Provider
             * @default openai
             */
            embedding_provider: string;
            /**
             * Embedding Model
             * @default text-embedding-3-small
             */
            embedding_model: string;
        };
        /**
         * OutboundIdentityUpdate
         * @description Payload for PUT /api/v1/onboarding/tenant-identity.
         *
         *     All three fields are optional. Submitting a field as ``None`` clears
         *     it (falls back to the legacy resolver chain on the next email send);
         *     omitting a field leaves the existing value untouched. To distinguish
         *     "omit" from "explicit null", the router uses ``model_dump(exclude_unset=True)``.
         */
        OutboundIdentityUpdate: {
            /**
             * Outbound User Email
             * @description Outbound mailbox for the From: address in user_direct + dyad modes (and Reply-To across all modes). Validated against _EMAIL_RE if non-null + non-empty.
             */
            outbound_user_email?: string | null;
            /**
             * Outbound User Name
             * @description Display name shown in the From: header.
             */
            outbound_user_name?: string | null;
            /**
             * Outbound Agent Slug
             * @description Tenant-pinned agent slug for agent_identified mode. Must be one of: sales, support, growth, ops, research.
             */
            outbound_agent_slug?: string | null;
        };
        /** OverdueNotificationResponse */
        OverdueNotificationResponse: {
            /** Scanned */
            scanned: number;
            /** Notified */
            notified: number;
        };
        /** PlaybookCreate */
        PlaybookCreate: {
            /** Name */
            name: string;
            /**
             * Trigger Event
             * @description Event key (e.g., 'crm:hot_lead')
             */
            trigger_event: string;
            /**
             * Allowed Actions
             * @description ActionCategory values allowed without HITL
             */
            allowed_actions: string[];
            /**
             * Token Budget
             * @description Max compute tokens per execution
             * @default 50
             */
            token_budget: number;
            /**
             * Financial Cap Cents
             * @description Max USD cents exposure per execution
             * @default 0
             */
            financial_cap_cents: number;
            /**
             * Require Approval
             * @description If True, playbook still requires HITL
             * @default false
             */
            require_approval: boolean;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
        };
        /** PlaybookResponse */
        PlaybookResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Trigger Event */
            trigger_event: string;
            /** Allowed Actions */
            allowed_actions: string[];
            /** Token Budget */
            token_budget: number;
            /** Financial Cap Cents */
            financial_cap_cents: number;
            /** Require Approval */
            require_approval: boolean;
            /** Enabled */
            enabled: boolean;
            /** Org Id */
            org_id: string;
            /** Created At */
            created_at: string;
        };
        /** PlaybookUpdate */
        PlaybookUpdate: {
            /** Name */
            name?: string | null;
            /** Allowed Actions */
            allowed_actions?: string[] | null;
            /** Token Budget */
            token_budget?: number | null;
            /** Financial Cap Cents */
            financial_cap_cents?: number | null;
            /** Require Approval */
            require_approval?: boolean | null;
            /** Enabled */
            enabled?: boolean | null;
        };
        /** ProbeRunReport */
        ProbeRunReport: {
            /** Correlation Id */
            correlation_id: string;
            /** Dry Run */
            dry_run: boolean;
            /** Started At */
            started_at: number;
            /** Finished At */
            finished_at: number;
            /** Duration Ms */
            duration_ms: number;
            /** Ok */
            ok: boolean;
            /** Fail Count */
            fail_count: number;
            /** Stages */
            stages: components["schemas"]["StageReport"][];
        };
        /**
         * PromoteKeyRequest
         * @description Body for POST /admin/consent-ledger/promote-key.
         */
        PromoteKeyRequest: {
            /**
             * New Key Value
             * @description New HMAC key value. Recommended shape: 64 hex chars (32 random bytes from `openssl rand -hex 32`). Must be at least 16 chars to reject obvious typos.
             */
            new_key_value: string;
        };
        /**
         * PromoteKeyResponse
         * @description Result of a successful key promotion.
         */
        PromoteKeyResponse: {
            /**
             * New Key Version
             * @description Version assigned to the new key.
             */
            new_key_version: number;
            /**
             * Previous Key Version
             * @description The version that was active before promotion. NULL if no previous key was current (placeholder-bootstrap state).
             */
            previous_key_version?: number | null;
            /**
             * Promoted At
             * Format: date-time
             * @description UTC timestamp of the promotion.
             */
            promoted_at: string;
        };
        /**
         * ProviderBalance
         * @description Cached balance state for a single provider.
         */
        ProviderBalance: {
            /**
             * Balance Usd
             * @description Estimated USD balance / remaining quota. -1 when unknown (degraded path: no API + no PostHog history).
             */
            balance_usd: number;
            /**
             * Currency
             * @description Always USD at MVP.
             * @default USD
             */
            currency: string;
            /**
             * Source
             * @description How the value was derived: 'api' (direct provider balance API), 'estimated' (max_known_balance - PostHog usage sum), or 'unknown' (no signal — treat as critical for alerting).
             */
            source: string;
            /**
             * Updated At
             * @description ISO-8601 UTC timestamp when the probe last refreshed this entry.
             */
            updated_at: string;
            /**
             * Alert
             * @description One of 'ok' / 'low' / 'critical' / 'unknown'.
             */
            alert: string;
        };
        /**
         * ProviderSummary
         * @description Provider info with api_key_env redacted.
         */
        ProviderSummary: {
            /** Base Url */
            base_url: string;
            /**
             * Vision
             * @default true
             */
            vision: boolean;
            /**
             * Timeout
             * @default 120
             */
            timeout: number;
        };
        /**
         * PublishSkillRequest
         * @description Request body for publishing a new skill to the marketplace.
         */
        PublishSkillRequest: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Yaml Content */
            yaml_content: string;
            /** Readme */
            readme?: string | null;
            /** Category */
            category?: string | null;
            /** Tags */
            tags?: string[];
        };
        /**
         * RateSkillRequest
         * @description Request body for rating a marketplace skill.
         */
        RateSkillRequest: {
            /** Rating */
            rating: number;
            /** Review */
            review?: string | null;
        };
        /**
         * RecordDecisionRequest
         * @description Payload a caller POSTs when a HITL gate resolves.
         */
        RecordDecisionRequest: {
            /** Agent Id */
            agent_id?: string | null;
            /** Action Category */
            action_category: string;
            /** Org Id */
            org_id: string;
            /** Context */
            context?: {
                [key: string]: unknown;
            };
            outcome: components["schemas"]["DecisionOutcome"];
            /** Approver Id */
            approver_id?: string | null;
            /** Latency Ms */
            latency_ms?: number | null;
            /** Payload Hash */
            payload_hash?: string | null;
            /** Diff Hash */
            diff_hash?: string | null;
            /** Parent Decision Id */
            parent_decision_id?: string | null;
            /** Notes */
            notes?: string | null;
        };
        /** RecordDecisionResponse */
        RecordDecisionResponse: {
            /** Decision Id */
            decision_id: string;
            /** Bucket Key */
            bucket_key: string;
            /** Context Signature */
            context_signature: string;
            /** Confidence */
            confidence: number;
            /** N Observed */
            n_observed: number;
            tier: components["schemas"]["HitlConfidenceTier"];
        };
        /** RecordRequest */
        RecordRequest: {
            /** Action */
            action: string;
            /** Amount */
            amount: number;
            /** Provider */
            provider?: string | null;
            /** Model */
            model?: string | null;
            /** Agent Id */
            agent_id?: string | null;
            /** Task Id */
            task_id?: string | null;
            /** Org Id */
            org_id?: string | null;
        };
        /** RequestFreshRequest */
        RequestFreshRequest: {
            /** Campaign Id */
            campaign_id: string;
        };
        /** RoomConfigUpdate */
        RoomConfigUpdate: {
            /** Max Players */
            max_players?: number | null;
            /** Motd */
            motd?: string | null;
        };
        /**
         * SSOConfig
         * @description Enterprise SSO connection configuration.
         */
        SSOConfig: {
            /** Janua Connection Id */
            janua_connection_id: string;
        };
        /** SalesPipelineMetrics */
        SalesPipelineMetrics: {
            /**
             * Total Leads
             * @default 0
             */
            total_leads: number;
            /**
             * Active Tasks
             * @default 0
             */
            active_tasks: number;
            /**
             * Completed Tasks
             * @default 0
             */
            completed_tasks: number;
            /**
             * Failed Tasks
             * @default 0
             */
            failed_tasks: number;
            /** Avg Duration Seconds */
            avg_duration_seconds?: number | null;
            /**
             * Period
             * @default
             */
            period: string;
        };
        /** ScheduleCreate */
        ScheduleCreate: {
            /**
             * Cron Expr
             * @description Standard 5-field crontab expression
             * @example 0 9 * * 1
             */
            cron_expr: string;
            action: components["schemas"]["ScheduledAction"];
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /** Description */
            description?: string | null;
        };
        /** ScheduleResponse */
        ScheduleResponse: {
            /** Id */
            id: string;
            /** User Id */
            user_id: string;
            /** Cron Expr */
            cron_expr: string;
            action: components["schemas"]["ScheduledAction"];
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Enabled */
            enabled: boolean;
            /** Description */
            description: string | null;
            /** Created At */
            created_at: string;
            /** Last Run At */
            last_run_at: string | null;
        };
        /**
         * ScheduledAction
         * @description Actions that can be scheduled via cron expressions.
         * @enum {string}
         */
        ScheduledAction: "acp_initiate" | "skill_refine" | "memory_compact" | "social_post";
        /** ScheduledActionBatchCreate */
        ScheduledActionBatchCreate: {
            /** Actions */
            actions: components["schemas"]["ScheduledActionCreate"][];
        };
        /** ScheduledActionBatchResponse */
        ScheduledActionBatchResponse: {
            /** Created */
            created: components["schemas"]["ScheduledActionResponse"][];
            /** Count */
            count: number;
        };
        /** ScheduledActionCreate */
        ScheduledActionCreate: {
            /**
             * Action Type
             * @default social_post
             */
            action_type: string;
            /**
             * Scheduled For
             * Format: date-time
             */
            scheduled_for: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /** Playbook Id */
            playbook_id?: string | null;
            /** Hitl Status */
            hitl_status?: ("approved" | "denied" | "pending") | null;
            /** Persona Id */
            persona_id?: string | null;
            /**
             * Max Retries
             * @default 3
             */
            max_retries: number;
        };
        /** ScheduledActionHitlUpdate */
        ScheduledActionHitlUpdate: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "denied";
        };
        /** ScheduledActionResponse */
        ScheduledActionResponse: {
            /** Id */
            id: string;
            /** Action Type */
            action_type: string;
            /**
             * Scheduled For
             * Format: date-time
             */
            scheduled_for: string;
            /** Status */
            status: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Playbook Id */
            playbook_id: string | null;
            /** Hitl Status */
            hitl_status: string | null;
            /** Persona Id */
            persona_id: string | null;
            /** Org Id */
            org_id: string;
            /** Retry Count */
            retry_count: number;
            /** Max Retries */
            max_retries: number;
            /** Last Error */
            last_error: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * SkillCompactResponse
         * @description Level-0: compact skill metadata (~3k tokens for full catalogue).
         */
        SkillCompactResponse: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Category */
            category: string;
        };
        /**
         * SkillRatingResponse
         * @description Public representation of a skill rating.
         */
        SkillRatingResponse: {
            /** Id */
            id: string;
            /** User Id */
            user_id: string;
            /** Rating */
            rating: number;
            /** Review */
            review: string | null;
            /** Created At */
            created_at: string;
        };
        /**
         * SkillResponse
         * @description Public representation of a skill.
         */
        SkillResponse: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Tier */
            tier: string;
            /** Allowed Tools */
            allowed_tools: string[];
        };
        /** SkipActionRequest */
        SkipActionRequest: {
            /**
             * Notes
             * @description Operator note explaining the skip.
             */
            notes?: string | null;
        };
        /** StageReport */
        StageReport: {
            /** Name */
            name: string;
            /** Status */
            status: string;
            /** Duration Ms */
            duration_ms: number;
            /** Detail */
            detail?: string | null;
            /** Facts */
            facts?: {
                [key: string]: unknown;
            };
        };
        /** StoredProbeRun */
        StoredProbeRun: {
            /** Correlation Id */
            correlation_id: string;
            /** Dry Run */
            dry_run: boolean;
            /** Started At */
            started_at: number;
            /** Finished At */
            finished_at: number;
            /** Duration Ms */
            duration_ms: number;
            /** Ok */
            ok: boolean;
            /** Fail Count */
            fail_count: number;
            /** Stages */
            stages: components["schemas"]["StageReport"][];
            /** Received At */
            received_at: number;
        };
        /** SwarmTaskResponse */
        SwarmTaskResponse: {
            /** Id */
            id: string;
            /** Title */
            title: string | null;
            /** Description */
            description: string;
            /** Graph Type */
            graph_type: string;
            /** Assigned Agent Ids */
            assigned_agent_ids: string[];
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Status */
            status: string;
            /** Kanban Status */
            kanban_status: string;
            /** Priority */
            priority: string;
            /** Labels */
            labels: string[];
            /** Due Date */
            due_date: string | null;
            /** Creator Id */
            creator_id: string | null;
            /** Parent Task Id */
            parent_task_id: string | null;
            /** Depends On */
            depends_on: string[];
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string | null;
            /** Completed At */
            completed_at: string | null;
        };
        /** TaskBoardItem */
        TaskBoardItem: {
            /** Id */
            id: string;
            /** Title */
            title: string | null;
            /** Description */
            description: string;
            /** Graph Type */
            graph_type: string;
            /** Status */
            status: string;
            /** Kanban Status */
            kanban_status: string;
            /** Priority */
            priority: string;
            /** Labels */
            labels: string[];
            /** Due Date */
            due_date: string | null;
            /** Parent Task Id */
            parent_task_id: string | null;
            /** Depends On */
            depends_on: string[];
            /** Agent Names */
            agent_names: string[];
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string | null;
            /** Started At */
            started_at: string | null;
            /** Completed At */
            completed_at: string | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Total Tokens */
            total_tokens: number | null;
            /** Event Count */
            event_count: number;
            /** Comment Count */
            comment_count: number;
        };
        /** TaskBoardResponse */
        TaskBoardResponse: {
            /** Columns */
            columns: {
                [key: string]: components["schemas"]["TaskBoardItem"][];
            };
            /** Totals */
            totals: {
                [key: string]: number;
            };
        };
        /** TaskClaimRequest */
        TaskClaimRequest: {
            /** Agent Id */
            agent_id?: string | null;
            /** Graph Type */
            graph_type?: string | null;
            /** Labels */
            labels?: string[];
        };
        /** TaskClaimResponse */
        TaskClaimResponse: {
            /** Claimed */
            claimed: boolean;
            task?: components["schemas"]["SwarmTaskResponse"] | null;
        };
        /** TaskCommentCreate */
        TaskCommentCreate: {
            /** Body */
            body: string;
        };
        /** TaskCommentResponse */
        TaskCommentResponse: {
            /** Id */
            id: string;
            /** Task Id */
            task_id: string;
            /** Author Id */
            author_id: string | null;
            /** Body */
            body: string;
            /** Created At */
            created_at: string;
        };
        /** TaskEventResponse */
        TaskEventResponse: {
            /** Id */
            id: string;
            /** Task Id */
            task_id: string | null;
            /** Agent Id */
            agent_id: string | null;
            /** Event Type */
            event_type: string;
            /** Event Category */
            event_category: string;
            /** Node Id */
            node_id: string | null;
            /** Graph Type */
            graph_type: string | null;
            /** Payload */
            payload: {
                [key: string]: unknown;
            } | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Provider */
            provider: string | null;
            /** Model */
            model: string | null;
            /** Token Count */
            token_count: number | null;
            /** Error Message */
            error_message: string | null;
            /** Request Id */
            request_id: string | null;
            /** Org Id */
            org_id: string;
            /** Created At */
            created_at: string;
        };
        /** TaskHistoryResponse */
        TaskHistoryResponse: {
            /** Id */
            id: string;
            /** Task Id */
            task_id: string;
            /** Event Type */
            event_type: string;
            /** Actor Id */
            actor_id: string | null;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Created At */
            created_at: string;
        };
        /**
         * TaskRequest
         * @description Inbound task request from an external agent.
         */
        TaskRequest: {
            /** Description */
            description: string;
            /**
             * Graph Type
             * @default coding
             */
            graph_type: string;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
        };
        /**
         * TaskResponse
         * @description Response returned after submitting or querying an A2A task.
         */
        TaskResponse: {
            /** Task Id */
            task_id: string;
            status: components["schemas"]["TaskStatus"];
            /** Result */
            result?: {
                [key: string]: unknown;
            } | null;
            /** Error */
            error?: string | null;
        };
        /**
         * TaskStatus
         * @description Lifecycle status of an A2A task.
         * @enum {string}
         */
        TaskStatus: "pending" | "running" | "completed" | "failed";
        /** TaskStatusUpdate */
        TaskStatusUpdate: {
            /** Status */
            status: string;
            /** Result */
            result?: {
                [key: string]: unknown;
            } | null;
            /** Started At */
            started_at?: string | null;
            /** Error Message */
            error_message?: string | null;
            /** Deployment Evidence */
            deployment_evidence?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * TenantCreate
         * @description Create a new tenant org with optional Mexican business identity.
         */
        TenantCreate: {
            /**
             * Org Name
             * @description Display name
             */
            org_name: string;
            /**
             * Rfc
             * @description RFC fiscal identifier (Mexican tax ID)
             */
            rfc?: string | null;
            /**
             * Razon Social
             * @description Legal business name
             */
            razon_social?: string | null;
            /**
             * Regimen Fiscal
             * @description SAT regime code
             */
            regimen_fiscal?: string | null;
            /**
             * Locale
             * @default es-MX
             */
            locale: string;
            /**
             * Timezone
             * @default America/Mexico_City
             */
            timezone: string;
            /**
             * Currency
             * @default MXN
             */
            currency: string;
        };
        /** TenantIdentityCreate */
        TenantIdentityCreate: {
            /** Canonical Id */
            canonical_id: string;
            /** Legal Name */
            legal_name: string;
            /** Primary Contact Email */
            primary_contact_email?: string | null;
            /** Janua Org Id */
            janua_org_id?: string | null;
            /** Dhanam Space Id */
            dhanam_space_id?: string | null;
            /** Phyndcrm Tenant Id */
            phyndcrm_tenant_id?: string | null;
            /** Karafiel Org Id */
            karafiel_org_id?: string | null;
            /** Resend Domain Ids */
            resend_domain_ids?: string[] | null;
            /** Cloudflare Zone Ids */
            cloudflare_zone_ids?: string[] | null;
            /** Selva Office Seat Ids */
            selva_office_seat_ids?: string[] | null;
            /** R2 Bucket Names */
            r2_bucket_names?: string[] | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * TenantResponse
         * @description Tenant configuration response.
         */
        TenantResponse: {
            /** Id */
            id: string;
            /** Org Id */
            org_id: string;
            /** Rfc */
            rfc?: string | null;
            /** Razon Social */
            razon_social?: string | null;
            /** Regimen Fiscal */
            regimen_fiscal?: string | null;
            /** Locale */
            locale: string;
            /** Timezone */
            timezone: string;
            /** Currency */
            currency: string;
            /** Karafiel Org Id */
            karafiel_org_id?: string | null;
            /** Dhanam Space Id */
            dhanam_space_id?: string | null;
            /** Phynd Tenant Id */
            phynd_tenant_id?: string | null;
            /** Cfdi Enabled */
            cfdi_enabled: boolean;
            /** Intelligence Enabled */
            intelligence_enabled: boolean;
            /** Max Agents */
            max_agents: number;
            /** Max Daily Tasks */
            max_daily_tasks: number;
            /** Janua Connection Id */
            janua_connection_id?: string | null;
            /** Brand Name */
            brand_name?: string | null;
            /** Brand Logo Url */
            brand_logo_url?: string | null;
            /** Brand Primary Color */
            brand_primary_color?: string | null;
            /** Voice Mode */
            voice_mode?: string | null;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at?: string | null;
        };
        /**
         * TenantUpdate
         * @description Partial update for tenant settings (non-identity fields).
         */
        TenantUpdate: {
            /** Locale */
            locale?: string | null;
            /** Timezone */
            timezone?: string | null;
            /** Currency */
            currency?: string | null;
            /** Cfdi Enabled */
            cfdi_enabled?: boolean | null;
            /** Intelligence Enabled */
            intelligence_enabled?: boolean | null;
            /** Max Agents */
            max_agents?: number | null;
            /** Max Daily Tasks */
            max_daily_tasks?: number | null;
        };
        /**
         * TenantUsageResponse
         * @description Current usage stats against tenant limits.
         */
        TenantUsageResponse: {
            /** Org Id */
            org_id: string;
            /** Agent Count */
            agent_count: number;
            /** Agent Limit */
            agent_limit: number;
            /** Tasks Today */
            tasks_today: number;
            /** Task Daily Limit */
            task_daily_limit: number;
            /** Department Count */
            department_count: number;
        };
        /** TimelineResponse */
        TimelineResponse: {
            /** Task Id */
            task_id: string;
            /** Events */
            events: components["schemas"]["TaskEventResponse"][];
            /** Total Duration Ms */
            total_duration_ms: number | null;
            /** Total Tokens */
            total_tokens: number | null;
        };
        /** TrajectoryResponse */
        TrajectoryResponse: {
            /** Id */
            id: string;
            /** Conversations */
            conversations: {
                [key: string]: unknown;
            }[];
        };
        /** TranscribeResponse */
        TranscribeResponse: {
            /** Text */
            text: string;
            /** Language */
            language: string;
        };
        /** TransitionResponse */
        TransitionResponse: {
            egg: components["schemas"]["EggResponse"];
            /**
             * Transitioned
             * @description True when status changed; false when already at target.
             */
            transitioned: boolean;
        };
        /** TrendPoint */
        TrendPoint: {
            /** Timestamp */
            timestamp: string;
            /** Value */
            value: number;
        };
        /** TulanaBuyerSignal */
        TulanaBuyerSignal: {
            /** Metric */
            metric: string;
            /** Value */
            value: string | number;
            /**
             * Source
             * @default selva_campaign
             */
            source: string;
        };
        /**
         * TulanaCampaignClaim
         * @description Row from Tulana's campaign claims register (feature-matrix export).
         *
         *     Mirrors the wire shape emitted by Tulana's
         *     ``tulana_campaign_claims_register --json`` command
         *     (``madfam_catalog.feature_matrix.build_campaign_claims_register``).
         *     ``extra="ignore"`` lets Tulana pass full register rows straight through;
         *     ``campaign_safe`` defaults to ``False`` so unmarked claims fail closed.
         */
        TulanaCampaignClaim: {
            /** Feature Key */
            feature_key: string;
            /**
             * Feature Label
             * @default
             */
            feature_label: string;
            /**
             * Claim Class
             * @default feature
             */
            claim_class: string;
            /**
             * Campaign Safe
             * @default false
             */
            campaign_safe: boolean;
            /** Blocking Reasons */
            blocking_reasons?: string[];
            /** Claim Evidence Url */
            claim_evidence_url?: string | null;
            /**
             * Notes
             * @default
             */
            notes: string;
        };
        /** TulanaFeedbackRequest */
        TulanaFeedbackRequest: {
            /** Sku Key */
            sku_key: string;
            /** Summary */
            summary: string;
            /** Outcomes */
            outcomes: components["schemas"]["TulanaBuyerSignal"][];
            /** Campaign Name */
            campaign_name?: string | null;
            /** Handoff Id */
            handoff_id?: string | null;
            /** Task Id */
            task_id?: string | null;
            /** Evidence Urls */
            evidence_urls?: string[];
        };
        /** TulanaFeedbackResponse */
        TulanaFeedbackResponse: {
            /** Status */
            status: string;
            /** Tulana Event Id */
            tulana_event_id?: string | null;
            /** Message */
            message: string;
        };
        /** TulanaImportRequest */
        TulanaImportRequest: {
            /** Packs */
            packs: components["schemas"]["TulanaSkuCampaignPack"][];
            /**
             * Allow Blocked
             * @description When true, blocked SKUs are accepted for waitlist/discovery lanes.
             * @default false
             */
            allow_blocked: boolean;
            /**
             * Dispatch Tasks
             * @description When true, enqueue one intelligence graph task per accepted SKU.
             * @default false
             */
            dispatch_tasks: boolean;
        };
        /** TulanaImportResponse */
        TulanaImportResponse: {
            /** Accepted */
            accepted: components["schemas"]["TulanaSkuCampaignPack"][];
            /** Rejected */
            rejected: components["schemas"]["TulanaPackValidation"][];
            /** Ranked Sku Keys */
            ranked_sku_keys: string[];
            /** Dispatched Task Ids */
            dispatched_task_ids?: string[];
        };
        /** TulanaPackValidation */
        TulanaPackValidation: {
            /** Sku Key */
            sku_key: string;
            /** Accepted */
            accepted: boolean;
            /** Errors */
            errors?: string[];
            /** Rank Score */
            rank_score?: number | null;
        };
        /** TulanaProofPoint */
        TulanaProofPoint: {
            /** Label */
            label: string;
            /** Source */
            source: string;
            /** Url */
            url?: string | null;
        };
        /**
         * TulanaSkuCampaignPack
         * @description Minimum Tulana export shape consumed by Selva campaign orchestration.
         */
        TulanaSkuCampaignPack: {
            /** Generated At */
            generated_at?: string | null;
            /** Sku Key */
            sku_key: string;
            /**
             * Platform
             * @default
             */
            platform: string;
            /** Audience */
            audience: string;
            /**
             * Ga Readiness
             * @enum {string}
             */
            ga_readiness: "near_ready" | "waived" | "blocked" | "ready" | "discovery";
            /** Rank */
            rank?: number | null;
            /** Readiness Reasons */
            readiness_reasons?: string[];
            /**
             * Value Prop
             * @default
             */
            value_prop: string;
            /** Proof Points */
            proof_points?: components["schemas"]["TulanaProofPoint"][];
            /**
             * Claims
             * @description Campaign claims register rows for this SKU. Only rows with campaign_safe=true may ground generated campaign copy.
             */
            claims?: components["schemas"]["TulanaCampaignClaim"][];
            /** Do Not Claim */
            do_not_claim?: string[];
            /**
             * Policy State
             * @default pending_review
             */
            policy_state: ("approved" | "waived_by_operator" | "blocked" | "pending_review") | string;
            /**
             * Last Verified At
             * Format: date-time
             */
            last_verified_at: string;
        };
        /**
         * UnifiedAuditEvent
         * @description Canonical cross-service audit event shape.
         *
         *     Fields are chosen to be the lowest common denominator across the four
         *     Selva ledgers. Source-specific fields (approval chain, hash prefixes,
         *     operation enum values) land in ``details`` so the UI can render them
         *     verbatim without the backend needing to know every ledger's schema.
         */
        UnifiedAuditEvent: {
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
            /**
             * Actor
             * @description Janua user sub or ``agent:<uuid>`` if the action was agent-driven. NULL only for legacy rows predating RFC 0005's actor_user_sub column.
             */
            actor?: string | null;
            /** Actor Email */
            actor_email?: string | null;
            /**
             * Source
             * @enum {string}
             */
            source: "selva_secret" | "selva_github" | "selva_config" | "selva_webhook";
            /**
             * Category
             * @enum {string}
             */
            category: "secret" | "github" | "config" | "webhook";
            /** Action */
            action: string;
            /** Target */
            target: string;
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "success" | "failure" | "denied";
            /** Request Id */
            request_id?: string | null;
            /** Details */
            details?: {
                [key: string]: unknown;
            };
        };
        /** UnifiedAuditListResponse */
        UnifiedAuditListResponse: {
            /** Events */
            events: components["schemas"]["UnifiedAuditEvent"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /** ValidateConsistencyResponse */
        ValidateConsistencyResponse: {
            /** Canonical Id */
            canonical_id: string;
            /** Services Checked */
            services_checked: number;
            /** Drifts */
            drifts: {
                [key: string]: unknown;
            }[];
            /**
             * Checked At
             * Format: date-time
             */
            checked_at: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, unknown>;
        };
        /** VoiceDispatchRequest */
        VoiceDispatchRequest: {
            /** Text */
            text: string;
            /**
             * Graph Type
             * @default coding
             */
            graph_type: string;
        };
        /** VoiceDispatchResponse */
        VoiceDispatchResponse: {
            /** Text */
            text: string;
            /** Graph Type */
            graph_type: string;
            /** Status */
            status: string;
            /** Task Id */
            task_id: string;
        };
        /**
         * VoiceModePreview
         * @description Clause preview for a single mode (read-only).
         */
        VoiceModePreview: {
            /** Mode */
            mode: string;
            /** Label */
            label: string;
            /** Typed Phrase */
            typed_phrase: string;
            /** Heads Up */
            heads_up: string;
            /** Clause Body */
            clause_body: string;
            /** Clause Version */
            clause_version: string;
        };
        /**
         * VoiceModeSelection
         * @description Payload for POST /voice-mode and PUT /settings/outbound-voice.
         */
        VoiceModeSelection: {
            /**
             * Mode
             * @description One of the three legal voice modes.
             */
            mode: string;
            /**
             * Typed Confirmation
             * @description Verbatim typed phrase matching the mode's clause.
             */
            typed_confirmation: string;
        };
        /** WarmupActionResponse */
        WarmupActionResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Egg Id
             * Format: uuid
             */
            egg_id: string;
            /** Action Type */
            action_type: string;
            /** Status */
            status: string;
            /** Scheduled For */
            scheduled_for: string;
            /** Executed At */
            executed_at: string | null;
            /** Result */
            result: {
                [key: string]: unknown;
            } | null;
            /** Day Offset */
            day_offset: number;
            /** Notes */
            notes: string | null;
            /** Content Brief */
            content_brief: string | null;
        };
        /** WorkflowCreateRequest */
        WorkflowCreateRequest: {
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** Yaml Content */
            yaml_content: string;
        };
        /** WorkflowImportRequest */
        WorkflowImportRequest: {
            /** Yaml Content */
            yaml_content: string;
        };
        /** WorkflowListResponse */
        WorkflowListResponse: {
            /** Items */
            items: components["schemas"]["WorkflowResponse"][];
            /** Total */
            total: number;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
        };
        /** WorkflowResponse */
        WorkflowResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Version */
            version: string;
            /** Description */
            description: string;
            /** Yaml Content */
            yaml_content: string;
            /** Org Id */
            org_id: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
        };
        /** WorkflowTemplateResponse */
        WorkflowTemplateResponse: {
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Filename */
            filename: string;
            /** Category */
            category: string;
            /** Node Count */
            node_count: number;
        };
        /** WorkflowUpdateRequest */
        WorkflowUpdateRequest: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
            /** Yaml Content */
            yaml_content?: string | null;
        };
        /** WorkflowValidationResponse */
        WorkflowValidationResponse: {
            /** Is Valid */
            is_valid: boolean;
            /** Errors */
            errors: {
                [key: string]: unknown;
            }[];
            /** Warnings */
            warnings: {
                [key: string]: unknown;
            }[];
        };
        /** ApprovalRequestResponse */
        nexus_api__routers__approvals__ApprovalRequestResponse: {
            /** Id */
            id: string;
            /** Agent Id */
            agent_id: string;
            /** Agent Name */
            agent_name?: string | null;
            /** Action Category */
            action_category: string;
            /** Action Type */
            action_type: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Diff */
            diff: string | null;
            /** Reasoning */
            reasoning: string;
            /** Urgency */
            urgency: string;
            /** Status */
            status: string;
            /** Feedback */
            feedback: string | null;
            /** Responded By */
            responded_by?: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Responded At */
            responded_at: string | null;
        };
        /** DeleteResponse */
        nexus_api__routers__artifacts__DeleteResponse: {
            /**
             * Deleted
             * @default true
             */
            deleted: boolean;
        };
        /** ApprovalRequestResponse */
        nexus_api__routers__command_approvals__ApprovalRequestResponse: {
            /** Id */
            id: string;
            /** Run Id */
            run_id: string;
            /** Command */
            command: string;
            /** Reason */
            reason: string;
            status: components["schemas"]["ApprovalStatus"];
            /** Requested At */
            requested_at: string;
            /** Resolved At */
            resolved_at: string | null;
            /** Resolved By */
            resolved_by: string | null;
        };
        /**
         * DeleteResponse
         * @description Response after unpublishing a skill.
         */
        nexus_api__routers__marketplace__DeleteResponse: {
            /**
             * Deleted
             * @default true
             */
            deleted: boolean;
        };
        /**
         * TenantIdentityResponse
         * @description Server-resolved outbound identity for a tenant.
         *
         *     Returned by ``GET /onboarding/tenant-identity``. Used by the email
         *     tools to populate the ``From:`` header without trusting any
         *     LLM-supplied kwargs (which would be a prompt-injection vector for
         *     sender spoofing within the tenant's verified Resend domain).
         *
         *     Fields are nullable individually so the tool can detect partial
         *     configuration (e.g. brand_name set but no primary contact email
         *     resolved yet) and fail-closed on the missing piece.
         *
         *     **Precedence chain** (resolved server-side; LLM has zero influence):
         *
         *     - ``user_email``: ``tenant_configs.outbound_user_email`` (first-class,
         *       tenant-configurable via the office UI) → fall back to
         *       ``tenant_identities.primary_contact_email`` (legacy MADFAM-ops-set
         *       field).
         *     - ``user_name``: ``tenant_configs.outbound_user_name`` →
         *       ``tenant_configs.brand_name`` → ``tenant_identities.legal_name`` →
         *       ``tenant_configs.razon_social``.
         *     - ``org_name``: ``tenant_identities.legal_name`` →
         *       ``tenant_configs.razon_social`` → ``tenant_configs.brand_name``.
         *     - ``agent_slug``: ``tenant_configs.outbound_agent_slug`` if set and
         *       in the email-tool allow-list, else None (caller falls back to its
         *       own per-tool default — never to LLM-supplied raw text).
         */
        nexus_api__routers__onboarding__TenantIdentityResponse: {
            /**
             * User Email
             * @description Primary outbound mailbox for the tenant (drives From: in user_direct/dyad modes and Reply-To across all modes). Resolves tenant_configs.outbound_user_email then tenant_identities.primary_contact_email.
             */
            user_email?: string | null;
            /**
             * User Name
             * @description Display name for the From: header. Resolves tenant_configs.outbound_user_name then brand_name then tenant_identities.legal_name then razon_social.
             */
            user_name?: string | null;
            /**
             * Org Name
             * @description Organization legal name for the agent_identified signature block. Sourced from tenant_identities.legal_name with fallback to tenant_configs.razon_social or brand_name.
             */
            org_name?: string | null;
            /**
             * Agent Slug
             * @description Optional tenant-configured agent slug for agent_identified mode. NULL means the email tool should fall back to its own per-call role → slug resolution. Constrained to the 5-entry allow-list (sales/support/growth/ops/research) at PUT time.
             */
            agent_slug?: string | null;
        };
        /** TenantIdentityResponse */
        nexus_api__routers__tenant_identities__TenantIdentityResponse: {
            /** Id */
            id: string;
            /** Canonical Id */
            canonical_id: string;
            /** Legal Name */
            legal_name: string;
            /** Primary Contact Email */
            primary_contact_email: string | null;
            /** Janua Org Id */
            janua_org_id: string | null;
            /** Dhanam Space Id */
            dhanam_space_id: string | null;
            /** Phyndcrm Tenant Id */
            phyndcrm_tenant_id: string | null;
            /** Karafiel Org Id */
            karafiel_org_id: string | null;
            /** Resend Domain Ids */
            resend_domain_ids: string[] | null;
            /** Cloudflare Zone Ids */
            cloudflare_zone_ids: string[] | null;
            /** Selva Office Seat Ids */
            selva_office_seat_ids: string[] | null;
            /** R2 Bucket Names */
            r2_bucket_names: string[] | null;
            /** Meta */
            meta: {
                [key: string]: unknown;
            } | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    root_health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    sentry_probe_api_v1_health_sentry_probe_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_v1_health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    ready_api_v1_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    health_detail_api_v1_health_detail_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    pool_stats_api_v1_health_pool_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    queue_stats_api_v1_health_queue_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    dlq_stats_api_v1_health_dlq_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    consent_ledger_grants_api_v1_health_consent_ledger_grants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    rls_status_api_v1_health_rls_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_agents_api_v1_agents__get: {
        parameters: {
            query?: {
                department_id?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_agent_api_v1_agents__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_agent_api_v1_agents__agent_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_agent_api_v1_agents__agent_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_agent_api_v1_agents__agent_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assign_agent_api_v1_agents__agent_id__assign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentAssign"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_agent_stats_api_v1_agents__agent_id__stats_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentStatsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_departments_api_v1_departments__get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DepartmentListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_department_api_v1_departments__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DepartmentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DepartmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_department_api_v1_departments__dept_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dept_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DepartmentDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_department_api_v1_departments__dept_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dept_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DepartmentUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DepartmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_pending_approvals_api_v1_approvals__get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_approval_request_api_v1_approvals__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateApprovalRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_approval_request_api_v1_approvals__request_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_request_api_v1_approvals__request_id__approve_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ApprovalAction"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deny_request_api_v1_approvals__request_id__deny_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ApprovalAction"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_expire_api_v1_approvals_bulk_expire_post: {
        parameters: {
            query?: {
                older_than_hours?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkExpireResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dispatch_task_api_v1_swarms_dispatch_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DispatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dispatch_ecosystem_app_manifest_api_v1_swarms_dispatch_ecosystem_app_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": unknown;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_ecosystem_app_manifest_api_v1_swarms_dispatch_ecosystem_app_verify_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": unknown;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ManifestVerifyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_active_tasks_api_v1_swarms_tasks_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"][];
                };
            };
        };
    };
    get_task_board_api_v1_swarms_tasks_board_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskBoardResponse"];
                };
            };
        };
    };
    export_kanban_tasks_api_v1_swarms_tasks_export_get: {
        parameters: {
            query?: {
                format?: string;
                kanban_status?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_kanban_tasks_api_v1_swarms_tasks_import_post: {
        parameters: {
            query?: {
                format?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KanbanTaskImportResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_kanban_metrics_api_v1_swarms_tasks_kanban_metrics_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KanbanMetricsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    claim_available_task_api_v1_swarms_tasks_claim_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskClaimRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskClaimResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    notify_overdue_tasks_api_v1_swarms_tasks_notify_overdue_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverdueNotificationResponse"];
                };
            };
        };
    };
    notify_overdue_tasks_all_api_v1_swarms_tasks_notify_overdue_all_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverdueNotificationResponse"];
                };
            };
        };
    };
    get_task_api_v1_swarms_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_task_status_api_v1_swarms_tasks__task_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskStatusUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_task_kanban_api_v1_swarms_tasks__task_id__kanban_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KanbanTaskUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwarmTaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_task_comments_api_v1_swarms_tasks__task_id__comments_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskCommentResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_task_comment_api_v1_swarms_tasks__task_id__comments_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskCommentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskCommentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_task_history_api_v1_swarms_tasks__task_id__history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskHistoryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_deployment_evidence_records_api_v1_swarms_evidence_get: {
        parameters: {
            query?: {
                task_id?: string | null;
                graph_type?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeploymentEvidenceRecordListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_deployment_evidence_record_api_v1_swarms_evidence__evidence_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                evidence_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeploymentEvidenceRecordResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reap_stale_tasks_api_v1_swarms_tasks_reap_stale_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number;
                    };
                };
            };
        };
    };
    billing_status_api_v1_billing_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    compute_usage_api_v1_billing_usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    compute_token_status_api_v1_billing_tokens_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    create_billing_portal_api_v1_billing_portal_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    agent_hours_usage_api_v1_billing_agent_hours_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_subscription_tiers_api_v1_billing_tiers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    create_checkout_api_v1_billing_checkout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CheckoutRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_usage_api_v1_billing_record_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    check_budget_api_v1_billing_check_budget_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    [key: string]: unknown;
                };
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BudgetResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_skills_api_v1_skills__get: {
        parameters: {
            query?: {
                tier?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    enable_community_api_v1_skills_community_enable_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    disable_community_api_v1_skills_community_disable_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    community_status_api_v1_skills_community_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: boolean;
                    };
                };
            };
        };
    };
    list_skills_compact_api_v1_skills_compact_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillCompactResponse"][];
                };
            };
        };
    };
    get_skill_full_api_v1_skills_md__skill_name__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                skill_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_skill_reference_api_v1_skills_md__skill_name__refs__ref_path__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                skill_name: string;
                ref_path: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refiner_metrics_api_v1_skills_refiner_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    telegram_webhook_api_v1_gateway_telegram_webhook_post: {
        parameters: {
            query?: never;
            header?: {
                "x-telegram-bot-api-secret-token"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    discord_webhook_api_v1_gateway_discord_webhook_post: {
        parameters: {
            query?: never;
            header?: {
                "x-signature-256"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    slack_webhook_api_v1_gateway_slack_webhook_post: {
        parameters: {
            query?: never;
            header?: {
                "x-slack-signature"?: string;
                "x-slack-request-timestamp"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    email_inbound_api_v1_gateway_email_inbound_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    whatsapp_webhook_verify_api_v1_gateway_whatsapp_webhook_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    whatsapp_inbound_api_v1_gateway_whatsapp_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    matrix_inbound_api_v1_gateway_matrix_webhook_put: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    matrix_inbound_api_v1_gateway_matrix_webhook_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mattermost_inbound_api_v1_gateway_mattermost_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    signal_inbound_api_v1_gateway_signal_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    sms_inbound_api_v1_gateway_sms_inbound_post: {
        parameters: {
            query?: never;
            header?: {
                "x-twilio-signature"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dingtalk_webhook_api_v1_gateway_dingtalk_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    feishu_webhook_api_v1_gateway_feishu_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    wecom_webhook_api_v1_gateway_wecom_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    wecom_callback_api_v1_gateway_wecom_callback_post: {
        parameters: {
            query?: {
                echostr?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    weixin_webhook_api_v1_gateway_weixin_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    bluebubbles_webhook_api_v1_gateway_bluebubbles_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    teams_webhook_api_v1_gateway_teams_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    irc_webhook_api_v1_gateway_irc_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    qq_webhook_api_v1_gateway_qq_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    yuanbao_webhook_api_v1_gateway_yuanbao_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    homeassistant_webhook_api_v1_gateway_homeassistant_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    generic_webhook_api_v1_gateway_webhook__channel_id__post: {
        parameters: {
            query?: {
                x_webhook_signature?: string | null;
            };
            header?: never;
            path: {
                channel_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_complete_api_v1_gateway_api_complete_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_workflows_api_v1_workflows_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_workflow_api_v1_workflows_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_templates_api_v1_workflows_templates_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowTemplateResponse"][];
                };
            };
        };
    };
    create_from_template_api_v1_workflows_from_template_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateFromTemplateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workflow_api_v1_workflows__workflow_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_workflow_api_v1_workflows__workflow_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_workflow_api_v1_workflows__workflow_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_workflow_api_v1_workflows_validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowValidationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_workflow_api_v1_workflows_import_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_workflow_api_v1_workflows__workflow_id__export_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_artifacts_api_v1_artifacts_get: {
        parameters: {
            query?: {
                task_id?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_artifact_api_v1_artifacts__artifact_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_artifact_api_v1_artifacts__artifact_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__artifacts__DeleteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_artifact_api_v1_artifacts__artifact_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_marketplace_skills_api_v1_marketplace_skills_get: {
        parameters: {
            query?: {
                search?: string | null;
                category?: string | null;
                sort_by?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketplaceListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publish_skill_api_v1_marketplace_skills_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PublishSkillRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketplaceEntryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_marketplace_skill_api_v1_marketplace_skills__entry_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketplaceEntryDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unpublish_skill_api_v1_marketplace_skills__entry_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__marketplace__DeleteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rate_skill_api_v1_marketplace_skills__entry_id__rate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RateSkillRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillRatingResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    install_skill_api_v1_marketplace_skills__entry_id__install_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstallResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_maps_api_v1_maps_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MapListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_map_api_v1_maps_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MapCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MapResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_map_api_v1_maps__map_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                map_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MapResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_map_api_v1_maps__map_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                map_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MapUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MapResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_map_api_v1_maps__map_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                map_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_map_api_v1_maps_export_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MapImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_map_api_v1_maps_import_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MapImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MapResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_events_api_v1_calendar_events_get: {
        parameters: {
            query?: {
                hours?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarEventsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    connect_calendar_api_v1_calendar_connect_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConnectCalendarRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disconnect_calendar_api_v1_calendar_disconnect_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DisconnectResponse"];
                };
            };
        };
    };
    calendar_status_api_v1_calendar_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarStatusResponse"];
                };
            };
        };
    };
    get_intelligence_config_api_v1_intelligence_config_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrgConfigResponse"];
                };
            };
        };
    };
    generate_invoice_api_v1_invoices_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InvoiceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InvoiceDispatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    invoice_status_api_v1_invoices__uuid__status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                uuid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InvoiceStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_chat_history_api_v1_chat_history_get: {
        parameters: {
            query: {
                room_id: string;
                limit?: number;
                offset?: number;
                before?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_chat_message_api_v1_chat_messages_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatMessageCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_events_api_v1_events__get: {
        parameters: {
            query?: {
                task_id?: string | null;
                agent_id?: string | null;
                event_type?: string | null;
                event_category?: string | null;
                since?: string | null;
                until?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskEventResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_event_api_v1_events__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateEventRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_task_timeline_api_v1_events_tasks__task_id__timeline_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TimelineResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_metrics_dashboard_api_v1_metrics_dashboard_get: {
        parameters: {
            query?: {
                period?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetricsDashboardResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_roi_dashboard_api_v1_metrics_roi_get: {
        parameters: {
            query?: {
                period?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_ai_tasks_api_v1_convergence_ai_tasks_get: {
        parameters: {
            query: {
                /** @description ISO datetime, inclusive lower bound */
                period_start: string;
                /** @description ISO datetime, exclusive upper bound */
                period_end: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConvergenceAiTask"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_connected_users_api_v1_admin_users_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectedUser"][];
                };
            };
        };
    };
    kick_user_api_v1_admin_kick_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KickRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_room_config_api_v1_admin_room_config_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RoomConfigUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    promote_signing_key_api_v1_admin_consent_ledger_promote_key_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromoteKeyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromoteKeyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_audit_logs_api_v1_audit__get: {
        parameters: {
            query?: {
                page?: number;
                page_size?: number;
                /** @description Filter by HTTP method */
                action?: string | null;
                /** @description Filter by resource type */
                resource_type?: string | null;
                /** @description Filter by user ID */
                user_id?: string | null;
                /** @description Filter after ISO datetime */
                since?: string | null;
                /** @description Filter before ISO datetime */
                until?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditLogListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_audit_logs_api_v1_audit_export_get: {
        parameters: {
            query?: {
                /** @description Filter after ISO datetime */
                since?: string | null;
                /** @description Filter before ISO datetime */
                until?: string | null;
                /** @description Filter by HTTP method */
                action?: string | null;
                /** @description Filter by resource type */
                resource_type?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_unified_audit_api_v1_audit_unified__get: {
        parameters: {
            query?: {
                /** @description ISO-8601 lower bound (inclusive) */
                since?: string | null;
                /** @description ISO-8601 upper bound (inclusive) */
                until?: string | null;
                /** @description Filter to a subset of the four Selva ledgers. Omit for all four. Values: selva_secret, selva_github, selva_config, selva_webhook. */
                source?: string[] | null;
                /** @description Filter by ``actor_user_sub``. Non-admin callers are server-side forced to their own ``sub`` regardless of this parameter. */
                actor?: string | null;
                limit?: number;
                /** @description ISO-8601 timestamp from a prior response's next_cursor */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnifiedAuditListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_unified_audit_api_v1_audit_unified_get: {
        parameters: {
            query?: {
                /** @description ISO-8601 lower bound (inclusive) */
                since?: string | null;
                /** @description ISO-8601 upper bound (inclusive) */
                until?: string | null;
                /** @description Filter to a subset of the four Selva ledgers. Omit for all four. Values: selva_secret, selva_github, selva_config, selva_webhook. */
                source?: string[] | null;
                /** @description Filter by ``actor_user_sub``. Non-admin callers are server-side forced to their own ``sub`` regardless of this parameter. */
                actor?: string | null;
                limit?: number;
                /** @description ISO-8601 timestamp from a prior response's next_cursor */
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnifiedAuditListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sales_pipeline_metrics_api_v1_analytics_sales_get: {
        parameters: {
            query?: {
                /** @description Time period: 1d, 7d, 30d, 90d */
                period?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SalesPipelineMetrics"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    accounting_close_status_api_v1_analytics_accounting_get: {
        parameters: {
            query?: {
                /** @description Time period: 1d, 7d, 30d, 90d */
                period?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountingCloseStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    intelligence_summary_api_v1_analytics_intelligence_get: {
        parameters: {
            query?: {
                /** @description Time period: 1d, 7d, 30d, 90d */
                period?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntelligenceSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_tenant_api_v1_tenants__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_my_tenant_api_v1_tenants_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
        };
    };
    update_my_tenant_api_v1_tenants_me_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tenant_usage_api_v1_tenants_me_usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantUsageResponse"];
                };
            };
        };
    };
    configure_sso_api_v1_tenants_me_sso_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SSOConfig"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_branding_api_v1_tenants_me_branding_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    update_branding_api_v1_tenants_me_branding_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BrandingConfig"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_tenant_identity_api_v1_tenant_identities_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantIdentityCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__tenant_identities__TenantIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_tenant_identity_api_v1_tenant_identities_resolve_get: {
        parameters: {
            query: {
                /** @description One of: canonical_id, janua_org_id, dhanam_space_id, phyndcrm_tenant_id, karafiel_org_id */
                field: string;
                value: string;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__tenant_identities__TenantIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_tenant_consistency_api_v1_tenant_identities__canonical_id__validate_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                canonical_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ValidateConsistencyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transcribe_audio_api_v1_voice_transcribe_post: {
        parameters: {
            query?: {
                language?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_transcribe_audio_api_v1_voice_transcribe_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TranscribeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    voice_dispatch_api_v1_voice_dispatch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VoiceDispatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceDispatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onboarding_status_api_v1_onboarding_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingStatus"];
                };
            };
        };
    };
    get_office_size_api_v1_onboarding_office_size_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OfficeSizeResponse"];
                };
            };
        };
    };
    set_office_size_api_v1_onboarding_office_size_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OfficeSizeSelection"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OfficeSizeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    voice_mode_preview_api_v1_onboarding_voice_mode_preview__mode__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mode: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceModePreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tenant_identity_api_v1_onboarding_tenant_identity_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__onboarding__TenantIdentityResponse"];
                };
            };
        };
    };
    update_tenant_identity_api_v1_onboarding_tenant_identity_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OutboundIdentityUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__onboarding__TenantIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    select_voice_mode_api_v1_onboarding_voice_mode_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VoiceModeSelection"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    change_voice_mode_api_v1_settings_outbound_voice_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VoiceModeSelection"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_schedules_api_v1_schedules__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduleResponse"][];
                };
            };
        };
    };
    create_schedule_api_v1_schedules__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduleCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduleResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_schedule_api_v1_schedules__schedule_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                schedule_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_scheduled_actions_api_v1_scheduled_actions__get: {
        parameters: {
            query?: {
                status?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_scheduled_action_api_v1_scheduled_actions__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduledActionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_scheduled_action_batch_api_v1_scheduled_actions_batch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduledActionBatchCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionBatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_hitl_status_api_v1_scheduled_actions__action_id__hitl_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                action_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduledActionHitlUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    schedule_campaign_social_posts_api_v1_scheduled_actions_campaign_social_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CampaignSocialScheduleRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionBatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_eggs_api_v1_dragon_eggs_get: {
        parameters: {
            query?: {
                /** @description Filter by egg status (laid/incubating/hatching/hatched/matured). */
                status?: string | null;
                platform?: string | null;
                owner_org_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EggResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lay_egg_api_v1_dragon_eggs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LayEggRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EggDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_egg_api_v1_dragon_eggs__egg_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                egg_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EggDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    release_egg_api_v1_dragon_eggs__egg_id__delete: {
        parameters: {
            query?: {
                /** @description When set, force the egg to that status (e.g. 'matured' to skip warmup for a manually-warmed account). Otherwise, delete the egg + cascade actions. */
                force_status?: string | null;
            };
            header?: never;
            path: {
                egg_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transition_egg_api_v1_dragon_eggs__egg_id__transition_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                egg_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransitionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execute_action_api_v1_dragon_eggs__egg_id__actions__action_id__execute_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                egg_id: string;
                action_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WarmupActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    skip_action_api_v1_dragon_eggs__egg_id__actions__action_id__skip_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                egg_id: string;
                action_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["SkipActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WarmupActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_pending_api_v1_command_approvals_pending_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__command_approvals__ApprovalRequestResponse"][];
                };
            };
        };
    };
    approve_command_api_v1_command_approvals__request_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__command_approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deny_command_api_v1_command_approvals__request_id__deny_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["nexus_api__routers__command_approvals__ApprovalRequestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_trajectories_api_v1_trajectories_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": string[];
                };
            };
        };
    };
    get_trajectory_api_v1_trajectories__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrajectoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_batch_api_v1_trajectories_batch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchExportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_checkpoints_api_v1_checkpoints__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CheckpointListItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_checkpoint_api_v1_checkpoints__run_id___phase__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
                phase: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CheckpointState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rollback_to_phase_api_v1_checkpoints__run_id___phase__rollback_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
                phase: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    browse_hub_api_v1_skills_hub__get: {
        parameters: {
            query?: {
                category?: string | null;
                page?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HubSkillResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_hub_api_v1_skills_hub_search_get: {
        parameters: {
            query: {
                q: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HubSkillResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    install_skill_api_v1_skills_hub_install_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InstallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_playbooks_api_v1_playbooks_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaybookResponse"][];
                };
            };
        };
    };
    create_playbook_api_v1_playbooks_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaybookCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaybookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    match_playbook_api_v1_playbooks_match_get: {
        parameters: {
            query: {
                event: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_playbook_api_v1_playbooks__playbook_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                playbook_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaybookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_playbook_api_v1_playbooks__playbook_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                playbook_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_playbook_api_v1_playbooks__playbook_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                playbook_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaybookUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaybookResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    phynd_crm_webhook_api_v1_gateway_phynd_crm_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    import_tulana_pack_api_v1_campaigns_import_tulana_pack_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TulanaImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TulanaImportResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    crm_campaign_handoff_api_v1_campaigns_crm_handoff_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CrmCampaignHandoffRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CrmCampaignHandoffResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    campaign_generate_copy_api_v1_campaigns_generate_copy_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CampaignCopyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CampaignCopyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    campaign_schedule_social_api_v1_campaigns_schedule_social_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CampaignSocialScheduleRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduledActionBatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tulana_campaign_feedback_api_v1_campaigns_tulana_feedback_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TulanaFeedbackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TulanaFeedbackResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pending_api_v1_campaigns_authorizations_pending_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    preview_api_v1_campaigns_authorizations__authorization_id__preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                authorization_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_api_v1_campaigns_authorizations__authorization_id__decide_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                authorization_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    request_fresh_api_v1_campaigns_authorizations_request_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RequestFreshRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stripe_webhook_api_v1_stripe_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    probe_draft_api_v1_probe_draft_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    probe_email_send_api_v1_probe_email_send_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EmailSendRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmailSendResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_probe_run_api_v1_probe_runs_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProbeRunReport"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_latest_probe_run_api_v1_probe_latest_run_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StoredProbeRun"] | null;
                };
            };
        };
    };
    get_probe_history_api_v1_probe_history_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StoredProbeRun"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_provider_balances_api_v1_providers_balance_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: components["schemas"]["ProviderBalance"];
                    };
                };
            };
        };
    };
    list_decisions_api_v1_hitl_decisions_get: {
        parameters: {
            query?: {
                agent_id?: string | null;
                action_category?: string | null;
                outcome?: components["schemas"]["HitlOutcome"] | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecisionList"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_decision_api_v1_hitl_decisions_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordDecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_confidence_api_v1_hitl_confidence_get: {
        parameters: {
            query?: {
                action_category?: string | null;
                org_id?: string | null;
                min_observed?: number;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConfidenceDashboard"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    agent_card_api_v1_a2a__well_known_agent_json_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentCard"];
                };
            };
        };
    };
    send_task_api_v1_a2a_tasks_send_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_task_api_v1_a2a_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    send_subscribe_api_v1_a2a_tasks_sendSubscribe_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
