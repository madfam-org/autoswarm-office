// Convenience aliases for the most commonly-used wire types.
//
// `paths[...]['get']['responses']['200']['content']['application/json']` is the
// canonical way to spell a response type, but it's verbose to write at the
// hook boundary. The aliases below collapse the indirection so consumer code
// reads `WireTaskBoardResponse` instead of the full path expression.
//
// Naming convention: prefix with `Wire` to make the snake_case / wire-shape
// nature obvious at the call site, and to keep names from colliding with the
// hand-written camelCase domain types in `../approval`, `../events`, etc.
// See `packages/shared-types/README.md` (§ "Wire types") for the convention.

import type { components, paths } from './api';

// ---------------------------------------------------------------------------
// Approvals — /api/v1/approvals
// ---------------------------------------------------------------------------

/** Wire response for a single approval request (GET, POST approve, POST deny,
 *  POST create, and the WS `approval_request` message payload). */
export type WireApprovalRequest =
  components['schemas']['nexus_api__routers__approvals__ApprovalRequestResponse'];

/** Wire response for the paginated list endpoint. */
export type WireApprovalListResponse = components['schemas']['ApprovalListResponse'];

/** Wire request body for approve/deny actions. */
export type WireApprovalAction = components['schemas']['ApprovalAction'];

// ---------------------------------------------------------------------------
// Task board — /api/v1/swarms/tasks/board
// ---------------------------------------------------------------------------

export type WireTaskBoardResponse =
  paths['/api/v1/swarms/tasks/board']['get']['responses']['200']['content']['application/json'];

export type WireTaskBoardItem = components['schemas']['TaskBoardItem'];

// ---------------------------------------------------------------------------
// Events — /api/v1/events, /api/v1/events/tasks/{task_id}/timeline
// ---------------------------------------------------------------------------

export type WireTaskEvent = components['schemas']['TaskEventResponse'];

export type WireTaskTimeline = components['schemas']['TimelineResponse'];

// ---------------------------------------------------------------------------
// Metrics — /api/v1/metrics/dashboard
//
// The Python side returns `task_throughput`, `approval_latency`, `cost_breakdown`,
// and `recent_errors` as plain `dict[str, Any]` / `list[dict[str, Any]]`, so the
// raw generated type loses sub-field structure. We intersect the wire type with
// narrowed sub-shapes that mirror what the FastAPI handler in
// `apps/nexus-api/nexus_api/routers/metrics.py` actually returns. If the
// server-side shape changes, update both sides.
// ---------------------------------------------------------------------------

type WireMetricsDashboardRaw = components['schemas']['MetricsDashboardResponse'];

interface MetricsTaskThroughput {
  status_counts: Record<string, number>;
  total: number;
  avg_duration_s: number | null;
}

interface MetricsApprovalLatency {
  avg_seconds: number | null;
  resolved_count: number;
  pending_count: number;
}

interface MetricsCostBreakdownRow {
  provider: string;
  model: string;
  total_tokens: number;
  call_count: number;
}

interface MetricsRecentError {
  id: string;
  task_id: string | null;
  event_type: string;
  node_id: string | null;
  error_message: string | null;
  created_at: string;
}

export type WireMetricsDashboard = Omit<
  WireMetricsDashboardRaw,
  'task_throughput' | 'approval_latency' | 'cost_breakdown' | 'recent_errors'
> & {
  task_throughput: MetricsTaskThroughput;
  approval_latency: MetricsApprovalLatency;
  cost_breakdown: MetricsCostBreakdownRow[];
  recent_errors: MetricsRecentError[];
};
