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
