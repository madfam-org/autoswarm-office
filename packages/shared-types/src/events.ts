// CONVENTION: snake_case fields. These types mirror the wire shape of
// the Python API exactly — the runtime client receives them as-is from
// JSON and consumes the same field names. Do NOT camelCase here; keep
// the field names byte-identical to the FastAPI response schemas in
// `apps/nexus-api/nexus_api/routers/events.py` and `metrics.py`.

/** Event categories for the observability system. */
export type EventCategory =
  | 'task'
  | 'node'
  | 'llm'
  | 'approval'
  | 'git'
  | 'permission'
  | 'webhook'
  | 'system';

/** All known event types. */
export type EventType =
  | 'task.dispatched'
  | 'task.started'
  | 'task.completed'
  | 'task.failed'
  | 'task.timeout'
  | 'node.entered'
  | 'node.exited'
  | 'node.error'
  | 'llm.request'
  | 'llm.response'
  | 'approval.approved'
  | 'approval.denied'
  | 'git.worktree_created'
  | 'git.commit'
  | 'git.push'
  | 'git.pr_created'
  | 'permission.denied'
  | 'webhook.received'
  | 'webhook.processed'
  | 'system.worker_started'
  | 'system.worker_stopped';

/** A single task event from the observability API. */
export interface TaskEvent {
  id: string;
  task_id: string | null;
  agent_id: string | null;
  event_type: EventType | string;
  event_category: EventCategory;
  node_id: string | null;
  graph_type: string | null;
  payload: Record<string, unknown> | null;
  duration_ms: number | null;
  provider: string | null;
  model: string | null;
  token_count: number | null;
  error_message: string | null;
  request_id: string | null;
  org_id: string;
  created_at: string;
}

/** Response for /events/tasks/{task_id}/timeline */
export interface TaskTimeline {
  task_id: string;
  events: TaskEvent[];
  total_duration_ms: number | null;
  total_tokens: number | null;
}

/** Task board item with aggregated event data. */
export interface TaskBoardItem {
  id: string;
  description: string;
  graph_type: string;
  status: string;
  agent_names: string[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  total_tokens: number | null;
  event_count: number;
}

/** Task board columns response. */
export interface TaskBoardResponse {
  columns: Record<string, TaskBoardItem[]>;
  totals: Record<string, number>;
}

/** Trend data point for sparklines. */
export interface TrendPoint {
  timestamp: string;
  value: number;
}

/** Metrics dashboard response. */
export interface MetricsDashboard {
  period: string;
  agent_utilization_pct: number;
  task_throughput: {
    status_counts: Record<string, number>;
    total: number;
    avg_duration_s: number | null;
  };
  approval_latency: {
    avg_seconds: number | null;
    resolved_count: number;
    pending_count: number;
  };
  cost_breakdown: Array<{
    provider: string;
    model: string;
    total_tokens: number;
    call_count: number;
  }>;
  error_rate: number;
  trends: Record<string, TrendPoint[]>;
  recent_errors: Array<{
    id: string;
    task_id: string | null;
    event_type: string;
    node_id: string | null;
    error_message: string | null;
    created_at: string;
  }>;
}
