# @selva/shared-types

Shared TypeScript types for Selva Office. Two layers, two conventions.

## Domain types (hand-written, camelCase)

Files: `agent.ts`, `approval.ts`, `avatar.ts`, `billing.ts`, `events.ts`,
`office.ts`, `workflow.ts`, `world.ts`, `sprite-data/`.

These are the source of truth for **in-app data shapes** consumed by
React components, Phaser scenes, the Colyseus state schema, and any
internal business logic. They use camelCase, often add UI-only fields
(`statusHalo`, `currentNodeId`), and intentionally diverge from the wire
representation when that helps the UI.

```ts
import type { Agent, AgentStatus } from '@selva/shared-types';

const agent: Agent = {
  id: 'agt_123',
  name: 'Códice',
  status: 'working', // camelCase domain enum
  effectiveSkills: ['coding'], // computed UI field
  // ...
};
```

## Wire types (auto-generated, snake_case)

Files: `generated/api.ts` — produced by `pnpm generate-types` from the
nexus-api OpenAPI schema (FastAPI's `app.openapi()`).

Use these when you are **at the fetch boundary** — request bodies,
response payloads, query string params. They mirror the Python Pydantic
models exactly (snake_case, the same nullability rules, the same enum
literals) so the compiler catches drift.

```ts
import type { api } from '@selva/shared-types';

type DispatchRequest = api.components['schemas']['SwarmDispatchRequest'];
type DispatchResponse = api.components['schemas']['SwarmDispatchResponse'];

async function dispatch(body: DispatchRequest): Promise<DispatchResponse> {
  const res = await fetch('/api/v1/swarms/dispatch', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res.json();
}
```

The generated module is namespaced as `api` to keep wire-type names
(`Agent`, `SwarmTask`, …) from colliding with the hand-written domain
types of the same name.

## Conversion happens at the boundary

Convert from wire to domain immediately after `fetch().json()`; convert
back only when serializing for a request body. This keeps the rest of
the codebase free of snake_case and means every external-facing payload
shape is one renaming step away from the FastAPI route signature.

```ts
import type { Agent, api } from '@selva/shared-types';

function fromWire(wire: api.components['schemas']['Agent']): Agent {
  return {
    id: wire.id,
    name: wire.name,
    status: wire.status,
    effectiveSkills: wire.effective_skills ?? [],
    avgTaskDurationSeconds: wire.avg_task_duration_seconds,
    // ...
  };
}
```

## Regenerating

```bash
pnpm generate-types
```

The script (`scripts/generate-shared-types.mjs`) imports the FastAPI
app via `uv run`, dumps `app.openapi()`, and feeds it into
[openapi-typescript](https://github.com/openapi-ts/openapi-typescript).
No uvicorn boot, no DB connection, no network calls — the lifespan
context is never entered.

## CI drift gate

`.github/workflows/schema-drift.yml` runs `pnpm generate-types` and then
`git diff --exit-code packages/shared-types/src/generated/`. If you
changed a Pydantic model or a FastAPI route signature without
regenerating, the gate fails and your PR is blocked. The fix is always
the same: run `pnpm generate-types` locally and commit the result.
