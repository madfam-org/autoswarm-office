export * from './agent';
export * from './office';
export * from './approval';
export * from './billing';
export * from './avatar';
export * from './sprite-data';
export * from './workflow';
export * from './events';
export * from './world';

// Wire types auto-generated from the nexus-api OpenAPI schema.
// See packages/shared-types/README.md for the domain-vs-wire convention.
// Re-exported under a namespace to avoid collisions with hand-written
// domain types (e.g. `components['schemas']['Agent']` is distinct from
// the camelCase `Agent` interface in `agent.ts`).
export * as api from './generated/api';

// Friendly aliases for the most-used wire types (request/response shapes).
// Prefixed `Wire*` so they don't collide with the hand-written camelCase
// domain types of the same logical name. See `generated/helpers.ts` for
// the full list and `README.md` for the wire/domain convention.
export type {
  WireApprovalAction,
  WireApprovalListResponse,
  WireApprovalRequest,
  WireMetricsDashboard,
  WireTaskBoardItem,
  WireTaskBoardResponse,
  WireTaskEvent,
  WireTaskTimeline,
} from './generated/helpers';
