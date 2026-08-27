# Colyseus 0.16 → 0.18 Upgrade: Blast Radius

> **Status:** DONE — executed as a paired server+client cutover.
>
> **Why this doc exists:** two HIGH Trivy findings (CVE-2026-67213,
> CVE-2026-67214) on `nanoid@2.1.11` were reachable only through
> `@colyseus/core@0.16.24`. The cure was a framework upgrade. This documented
> exactly what that upgrade cost while it was deferred; it now records what the
> upgrade actually turned out to be.
>
> Origin of the finding: PR #277. Interim suppression: PR #278 (both nanoid
> entries **deleted** by this cutover — see "Trivyignore disposition").

## TL;DR

Both apps moved to 0.18 in **one commit**, because the client and server are
protocol-locked and cannot be deployed independently:

| Package                          | Before  | After            |
| -------------------------------- | ------- | ---------------- |
| `@colyseus/core` (apps/colyseus) | 0.16.24 | **0.18.8**       |
| `@colyseus/ws-transport`         | 0.16.5  | **0.18.2**       |
| `@colyseus/schema`               | 4.0.30  | **5.0.22**       |
| `colyseus.js` (apps/office-ui)   | 0.16.22 | **removed**      |
| `@colyseus/sdk` (apps/office-ui) | —       | **0.18.2** (new) |

The upgrade landed **fully mechanical**. The two feared majors both turned out
to be non-events for this codebase:

- **`@colyseus/schema` v4 → v5 required zero source changes.** The `@type`
  decorator API is unchanged and the wire format is byte-identical.
- **`zod` 3 → 4 is not required at all.** It is an _optional_ peer of
  `@colyseus/core` 0.18 and appears nowhere in core's shipped build.

## Schema v4 → v5: inventory vs. actual requirement

Repo schema surface: 2 definition files (`src/schema/OfficeState.ts`,
`src/schema/Whiteboard.ts`, 6 classes / 53 `@type` fields total) plus 3 files
importing `MapSchema`/`Schema` for handlers and tests.

| v5 concern                                      | Requirement for this repo                                                                                            |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Decorator API                                   | **No change.** `@type("string")`, `@type({map: X})`, `@type([X])` all still supported and not deprecated.            |
| tsconfig                                        | **No change.** `experimentalDecorators: true` + `useDefineForClassFields: false` — already set.                      |
| Codegen                                         | **Not required.** Runtime reflection is intact; `schema-codegen` is only for statically-typed (C#/Haxe) clients.     |
| TypeRegistry                                    | **No action.** No such export. `registerType()` is for custom _primitive_ codecs only; schema classes self-register. |
| Serialization / wire format                     | **Byte-identical** to v4 for these schemas (verified: same hex output from v4.0.31 and v5.0.22 encoders).            |
| `defineTypes()` removal                         | **N/A** — not used anywhere in the repo.                                                                             |
| 63-field-per-class cap                          | **Clear.** Largest class is 13 fields.                                                                               |
| `client.id` removal                             | **Clear.** No usages; the code already uses `client.sessionId`.                                                      |
| `setMetadata()` now replaces rather than merges | **Clear.** No usages.                                                                                                |

Net schema-v5 source diff: **zero lines**. The state classes were not touched.

## Server 0.16 → 0.18 source changes

Only the two mechanical fixes already predicted at 0.17, both re-verified on
0.18 (the `Room` generic shape introduced in 0.17 is unchanged in 0.18):

| Break                                                            | Fix                                                              |
| ---------------------------------------------------------------- | ---------------------------------------------------------------- |
| `Room<State>` generic is now a room-options object               | `Room<OfficeStateSchema>` → `Room<{ state: OfficeStateSchema }>` |
| `onLeave(client, consented: boolean)` → `(client, code: number)` | derive `consented` from `code === CloseCode.CONSENTED` (4000)    |

## Client swap surface

`colyseus.js` → `@colyseus/sdk` touched **one line of runtime code**.

The single integration point is `apps/office-ui/src/hooks/useColyseus.ts` (332
lines), and the API surface it uses — `new Client(url)`, `joinOrCreate`,
`onStateChange`, `onMessage`, `send`, `leave`, `onLeave`, `onError`,
`sessionId` — is unchanged in the SDK. The hook consumes state through
`onStateChange` snapshots rather than per-field `onAdd`/`onChange` listeners,
so the `getStateCallbacks` / `Callbacks.get()` API never enters the picture.
`OfficeExperience.tsx`, `SimplifiedView.tsx` and `HUD.tsx` consume the hook's
plain-object output and needed no changes.

### ArraySchema landmine — re-verified on v5, and one real bug fixed

The recorded workaround ("`ArraySchema.flatMap` needs `Array.from` first") is
**still required on v5, but it is not shaped the way the note implies.** Probed
directly against `@colyseus/schema@5.0.22`:

- `ArraySchema#flatMap()` now **throws** `ArraySchema#flatMap() is not
supported.` — v5 made the old silent misbehavior loud. No repo code calls it,
  so this is not a live break here.
- The actual repo hazard is the **outer** call: `plainArray.flatMap(d =>
d.agents)` where `d.agents` is an `ArraySchema`. It does not throw — it
  silently returns `[[...]]` un-flattened, because the proxy fails
  `Array.isArray()`. Unchanged from v4.

Call-site audit:

| Site                     | Status                                                             |
| ------------------------ | ------------------------------------------------------------------ |
| `SpaceRoster.tsx:146`    | already correct (`Array.from`)                                     |
| `DashboardPanel.tsx:356` | safe — inner `.filter().map()` returns a real array before flatMap |
| `CommandPalette.tsx:90`  | **was buggy — fixed in this change**                               |

`CommandPalette` was building agent entries from
`departments.flatMap(d => d.agents ?? [])`, which produced one un-flattened
proxy per department, so `.map(a => a.id/a.name)` read those fields off the
array object itself — yielding a bogus `undefined` entry per department instead
of one entry per agent. Now normalized with `Array.from`, matching `SpaceRoster`.

## Validation

- `pnpm typecheck` — **10/10 tasks pass**
- `pnpm test` — **1068 tests pass**, matching the pre-upgrade baseline exactly
  (shared-types 86, map-gen 39, ui 55, gateway 41, colyseus 166, admin 49,
  office-ui 632)
- `pnpm --filter @selva/colyseus lint` — 0 errors (9 pre-existing warnings)
- `pnpm --filter @selva/office-ui lint` — 0 errors
- Server boots on `@colyseus/core` 0.18.8; `/health` green
- **Real `@colyseus/sdk@0.18.2` client → real 0.18.8 server round-trip, 11/11
  checks** (a node process driving the actual published SDK over a real
  WebSocket — not a mock, not a browser): join → state sync (5 departments and
  their `@type` fields decoded, nested `ArraySchema` intact, players map
  populated) → client→server `move` applied and synced back → server→client
  `player_emote` broadcast received → consented leave. Server-side lifecycle log
  confirms `Room created → Client joined → Client left (code:4000,
consented:true) → Room disposed`.

The 0.17 blocker is gone: the join that previously failed with
`Cannot read properties of undefined (reading 'name')` now succeeds.

## Deploy note — HARD CUTOVER, NO MIXED-VERSION WINDOW

**`apps/colyseus` and `apps/office-ui` must ship together.** The versions are
protocol-locked in both directions:

- a `colyseus.js@0.16` client **cannot join** a 0.18 server (the seat
  reservation was flattened — this is the empirically reproduced failure above);
- a `@colyseus/sdk@0.18` client cannot talk to a 0.16 server either.

So this is not a rolling upgrade. Deploy both images from this commit in the
same window and expect connected clients to reconnect onto the new pair. The
client reconnects with exponential backoff (`useColyseus.ts`), so an in-flight
session recovers on its own once both sides are up, but a partial rollout leaves
every client unable to join for as long as it lasts. Roll back **both** together
too. Current topology: [`COLYSEUS_SCALING.md`](COLYSEUS_SCALING.md).

## Trivyignore disposition

`nanoid@2.1.11` is **gone from the lockfile entirely** (only 3.3.17/3.3.18
remain), and `colyseus.js` is fully removed. That satisfies the suppression's
own stated re-evaluation trigger — _"(a) apps/office-ui migrates to
`@colyseus/sdk` (then do the real 0.18 upgrade and DELETE this entry)"_ — so
**CVE-2026-67213 and CVE-2026-67214 are deleted from `.trivyignore`** in this
change rather than carried forward.

`CVE-2024-23342` (python-ecdsa) is unrelated and stays.
