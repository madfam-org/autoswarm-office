# Penny → Selva-Office Consolidation: Migration Plan

**Status:** Proposed (RFC 0024 P4, owner-approved)
**Author:** Consolidation pass (Claude Code)
**Source repo:** [`madfam-org/penny`](https://github.com/madfam-org/penny) @ `e0f9901` (last commit 2025-08-30, ~10 months stale)
**Target repo:** `madfam-org/selva-office` (this repo)
**Companion PR:** deprecation banner on penny (`chore/superseded-by-selva-office`)

---

## 1. Executive summary

`penny` is a stale multi-tenant AI workbench. Its **chat**, **tools**, and **auth**
layers are duplicates of selva-office and will **not** be migrated. Its
potentially-unique value is the **artifact-visualization layer** — a viewer +
12 typed renderers (charts, tables, code, markdown, HTML, images, PDF, JSON,
video, audio, 3D models, maps) plus a Zod type system, a Zustand store,
detect/transform/export utilities, and a backend persistence/versioning service.

The artifact-visualization layer totals **~11,900 lines** across frontend, types,
backend, and tools. It is **too large to port safely in a single pass**, so this
document defines a **phased, feature-flagged, file-by-file** migration for a
reviewed follow-up. Nothing is ported in this PR (see §6 for the rationale and
the one candidate that was considered).

The precedent is the `claudecodeui → selva-office` consolidation, which ported a
single self-contained component (DiffViewer) behind review. This plan follows the
same conservative posture but at larger scale, hence the phasing.

---

## 2. What is UNIQUE in penny (migration candidates)

All paths below are in the **penny** repo. Selva-office currently has **no**
artifact-viewer equivalent (verified: `packages/ui` has only button / agent-card /
approval-modal / pixelact primitives; the only `artifact` matches in selva-office
are an OpenAPI-generated string and an unrelated easter-egg component).

### 2a. Presentational layer — the core value (self-contained: React + Tailwind + `@penny/types` only; no external chart lib)

| Penny path | Lines | Notes |
|---|---:|---|
| `apps/web/src/components/artifacts/ArtifactViewer.tsx` | 250 | Dispatcher + error boundary; switches on artifact type to a renderer |
| `apps/web/src/components/artifacts/ArtifactPanel.tsx` | 258 | Multi-artifact panel wrapper (uses Tabs + Viewer) |
| `apps/web/src/components/artifacts/ArtifactTabs.tsx` | 320 | Tab strip for multiple open artifacts |
| `apps/web/src/components/artifacts/ArtifactHeader.tsx` | 387 | Title/actions/export/share toolbar |
| `apps/web/src/components/artifacts/renderers/ChartRenderer.tsx` | 300 | **Mock canvas chart** — no chart.js dep; likely needs a real charting lib on port |
| `apps/web/src/components/artifacts/renderers/TableRenderer.tsx` | 410 | Sortable/filterable data table |
| `apps/web/src/components/artifacts/renderers/CodeRenderer.tsx` | 323 | Syntax-highlighted code |
| `apps/web/src/components/artifacts/renderers/JSONRenderer.tsx` | 422 | Collapsible JSON tree |
| `apps/web/src/components/artifacts/renderers/MarkdownRenderer.tsx` | 195 | Markdown → HTML |
| `apps/web/src/components/artifacts/renderers/HTMLRenderer.tsx` | 129 | Sandboxed-iframe HTML |
| `apps/web/src/components/artifacts/renderers/ImageRenderer.tsx` | 459 | Zoom/pan image viewer |
| `apps/web/src/components/artifacts/renderers/PDFRenderer.tsx` | 152 | PDF embed |
| `apps/web/src/components/artifacts/renderers/VideoRenderer.tsx` | 187 | Video player |
| `apps/web/src/components/artifacts/renderers/AudioRenderer.tsx` | 258 | Audio player |
| `apps/web/src/components/artifacts/renderers/ModelRenderer.tsx` | 330 | 3D model viewer |
| `apps/web/src/components/artifacts/renderers/MapRenderer.tsx` | 305 | Geo/map viewer |

Subtotal: **~4,685 lines**. Renderers import only `react` + `@penny/types` and
style with Tailwind — technically clean to port (stacks are compatible: penny
React 18 / Tailwind 3 → selva React 19 / Tailwind 3; watch React 18→19 changes,
e.g. `ref` handling, and the `ChartRenderer` mock).

### 2b. Type system — hard dependency of everything above (Zod schemas)

| Penny path | Lines | Notes |
|---|---:|---|
| `packages/types/src/artifacts/index.ts` | 255 | `Artifact`, `ChartArtifact`, `TableArtifact`, `CodeArtifact`, `ImageArtifact`, `MapArtifact`, collections, actions |
| `packages/types/src/artifacts/metadata.ts` | 236 | Artifact metadata schema |
| `packages/types/src/artifacts/renderers.ts` | 388 | Renderer config/options schema |
| `packages/types/src/artifacts/versions.ts` | 188 | Version history schema |

Subtotal: **~1,067 lines**. Zod 3 (matches selva). This is the **blocking
prerequisite** — every renderer and the store import `@penny/types` artifact
schemas. Target: a new `packages/artifacts-types` (or fold into
`packages/shared-types`).

### 2c. State + client utilities (Zustand + pure TS)

| Penny path | Lines | Notes |
|---|---:|---|
| `apps/web/src/store/artifactStore.ts` | 715 | Zustand store (devtools + subscribeWithSelector); depends on detector + transformer |
| `apps/web/src/hooks/artifacts/useArtifact.ts` | 341 | Hook over store + exporter + transformer |
| `apps/web/src/utils/artifacts/detector.ts` | 406 | Infers artifact type from payload |
| `apps/web/src/utils/artifacts/transformer.ts` | 539 | Normalizes/transforms artifact data |
| `apps/web/src/utils/artifacts/exporter.ts` | 608 | Export to PNG/CSV/JSON/etc |

Subtotal: **~2,609 lines**. Zustand 4 matches selva. Needed only for the
interactive/multi-artifact experience; a read-only viewer can ship without the
store.

### 2d. Backend persistence/versioning (optional — only if artifacts must be stored server-side)

| Penny path | Lines | Notes |
|---|---:|---|
| `apps/api/src/services/artifacts/ArtifactService.ts` | 407 | CRUD orchestration |
| `apps/api/src/services/artifacts/ArtifactStorageService.ts` | 403 | Blob/object storage |
| `apps/api/src/services/artifacts/ArtifactProcessingService.ts` | 506 | Server-side processing |
| `apps/api/src/services/artifacts/ArtifactVersionService.ts` | 364 | Version history |
| `apps/api/src/services/artifact.ts` | 391 | Legacy/aggregate service |
| `apps/api/src/routes/artifacts.ts` | 170 | REST routes |
| `packages/database/migrations/005_artifact_system.sql` | 350 | Schema (tables/indexes) |

Subtotal: **~2,591 lines**. This is a **Node/Express-flavored** service; selva's
backend is **FastAPI (Python) `nexus-api`**. Porting means a **rewrite**, not a
copy — highest risk, lowest immediate value. Defer, and only do it if
server-side artifact persistence is actually required (client-only viewer may
suffice initially).

### 2e. Artifact-producing tools (evaluate against selva's tool registry)

| Penny path | Lines | Notes |
|---|---:|---|
| `packages/tools/src/tools/create_chart.ts` | 63 | Emits a ChartArtifact |
| `packages/tools/src/tools/load_dashboard.ts` | 492 | Emits a dashboard artifact |
| `packages/core/src/tools/builtin/dashboard.ts` | 391 | Dashboard builtin |

Subtotal: **~946 lines**. These are the *producers* of artifacts. selva already
has its own tool/skill registry (`packages/tools`, `packages/skills`). Port the
**artifact output shape** only if/when selva tools need to emit artifacts;
otherwise treat the tool bodies as duplicate logic and re-implement against
selva's registry rather than copy.

**Unique-layer grand total: ~11,900 lines.**

---

## 3. What is DUPLICATE in penny (do NOT migrate — "drop" list)

These have first-class selva-office equivalents. Leave them in penny; they die
with the archive.

| Penny area (paths) | Duplicate of (selva-office) |
|---|---|
| **Chat UI** — `apps/web/src/components/MessageBubble.tsx`, `hooks/useChat.ts`, `contexts/ChatContext.tsx`, `pages/ChatView.tsx` | `apps/office-ui` chat/office surfaces |
| **Auth** — `apps/web/src/components/auth/*` (AuthProvider, ProtectedRoute, SessionManager), `packages/security/src/{auth,rbac,crypto,sanitization}` | `packages/permissions`, Janua auth (`packages/janua-stub`, `@janua/nextjs-sdk`) |
| **Tool integrations** — `packages/tools/src/tools/{jira_integration,slack_integration,send_email,python_code,search_documents,export_data,get_company_kpis}.ts` | `packages/tools`, `packages/skills`, coupler tools |
| **Billing** — `apps/web/src/components/billing/*`, `apps/admin/.../billing/*` | `packages/budget-gate`, `packages/revenue-loop-probe`, Dhanam billing |
| **Monitoring** — `apps/web/src/components/monitoring/*`, `packages/monitoring` | `packages/observability`, `docs/OBSERVABILITY_*` |
| **Sandbox** — `apps/sandbox`, `packages/sandbox-client` | `apps/sandbox`, `packages/inference` sandboxing |
| **API / WS / Worker infra** — `apps/api`, `apps/ws`, `apps/worker` (non-artifact parts) | `apps/nexus-api`, `apps/colyseus`, `apps/workers` |
| **Admin shell** — `apps/admin` (non-artifact parts) | `apps/admin` |
| **Analytics / telemetry / core plumbing** — `packages/{analytics,telemetry,core}` | `packages/{observability,orchestrator,config}` |

---

## 4. Feature flags

Follow selva's existing `NEXT_PUBLIC_*_ENABLED` convention (see `.env.example`).

| Flag | Default | Gates |
|---|---|---|
| `NEXT_PUBLIC_ARTIFACTS_ENABLED` | `false` | Mounting any artifact viewer in office-ui |
| `NEXT_PUBLIC_ARTIFACTS_INTERACTIVE_ENABLED` | `false` | Zustand store / multi-artifact panel / export (§2c) |
| `ARTIFACTS_PERSISTENCE_ENABLED` | `false` | Server-side artifact store + routes in nexus-api (§2d), if ever built |

Every phase below ships dark (flag off) until the phase is reviewed and QA'd.

---

## 5. Phased order (each phase = one reviewed PR)

1. **Phase A — Types (prerequisite).** Port §2b into `packages/artifacts-types`
   (or `packages/shared-types`). No UI yet. Pure Zod; lowest risk. Blocks
   everything else.

2. **Phase B — One read-only renderer, flagged.** Port the smallest safe
   renderer + a minimal `ArtifactViewer` dispatch for that one type, behind
   `NEXT_PUBLIC_ARTIFACTS_ENABLED`. Recommended first: **HTMLRenderer** (129 lines,
   already iframe-sandboxed — no new deps, security posture explicit) or
   **MarkdownRenderer** (195 lines). Establishes the pattern (the DiffViewer-style
   thin slice). No store.

3. **Phase C — Remaining static renderers.** Table, Code, JSON, Image, PDF,
   Video, Audio, Markdown, Model, Map. Chart last (its mock needs a real charting
   lib decision — align with the `dataviz` house style). Still read-only, still
   flagged.

4. **Phase D — Interactive shell.** Port §2c (store, hook, detector, transformer,
   exporter) + ArtifactPanel/Tabs/Header behind
   `NEXT_PUBLIC_ARTIFACTS_INTERACTIVE_ENABLED`. Wire into an office-ui surface
   (candidate mount: `apps/office-ui/src/components/` alongside existing panels).

5. **Phase E — Persistence (only if required).** Re-implement §2d as a **FastAPI**
   service in `apps/nexus-api` + a migration in selva's schema, behind
   `ARTIFACTS_PERSISTENCE_ENABLED`. This is a rewrite (Node→Python), not a copy —
   scope separately and only if client-only artifacts prove insufficient.

6. **Phase F — Producers.** If selva tools need to emit artifacts, add artifact
   output to the relevant selva tools/skills using the Phase A types. Do **not**
   copy penny's tool bodies (§2e) — re-implement against selva's registry.

7. **Phase G — Archive penny.** After the wanted phases land and the flags are
   defaulted on, archive the penny repo (separate reviewed action).

**Target stack notes:** office-ui is Next 15 / React 19 / Tailwind 3 / Zustand 4;
penny is React 18 / Tailwind 3 / Zustand 4 / Zod 3. Compatible; the only expected
friction is React 18→19 semantics and replacing ChartRenderer's mock with a real
chart library.

---

## 6. Why nothing is ported in this PR (honesty note)

Per the consolidation directive, a component is ported inline **only if** it is
small, self-contained, and clearly safe (the DiffViewer precedent). The best
single candidate here is **HTMLRenderer** or **MarkdownRenderer**, but each
imports the `@penny/types` artifact schema (`Artifact`) and, without Phase A's
type package plus at least a minimal `ArtifactViewer` host, would land in
selva-office as **orphaned, un-mounted code behind a flag** — neither clearly
valuable (nothing renders into it yet) nor obviously safe (it needs either the
Zod type package or an inlined ad-hoc type that would later diverge). That fails
the "clearly safe and valuable in one pass" bar, so porting is deferred to
**Phase A → Phase B** of a reviewed follow-up rather than forced here.

## 7. What the reviewed follow-up must still do

- Decide the type home: new `packages/artifacts-types` vs. fold into
  `packages/shared-types` (Phase A).
- Pick the real charting library for ChartRenderer and reconcile with the
  `dataviz` design system (Phase C).
- Choose the office-ui mount point / route for the viewer and panel (Phases B/D).
- Decide whether server-side persistence is in scope at all (Phase E) — if yes,
  it is a FastAPI rewrite, not a port.
- Confirm the duplicate "drop" list in §3 with owners before archiving penny
  (Phase G), so no genuinely-unique logic is lost inside a "duplicate" area.
- Verify licensing/attribution is preserved on ported files.
