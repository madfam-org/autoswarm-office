# Colyseus 0.16 → 0.18 Upgrade: Blast Radius

> **Status:** BLOCKED — needs owner ratification. Not scheduled.
>
> **Why this doc exists:** two HIGH Trivy findings (CVE-2026-67213,
> CVE-2026-67214) on `nanoid@2.1.11` are reachable only through
> `@colyseus/core@0.16.24`. The cure is a framework upgrade. This documents
> exactly what that upgrade costs, so the interim `.trivyignore` entry is a
> ratified deferral and not an unexamined suppression.
>
> Interim suppression + exposure argument: [`.trivyignore`](../.trivyignore).
> Origin of the finding: PR #277.

## TL;DR

The **server-side** upgrade to `@colyseus/core@0.17.50` is clean and was
validated end to end. It is **not shippable alone**, because 0.17 changed the
seat-reservation wire shape and `colyseus.js@0.16.22` — the client
`apps/office-ui` ships — cannot join a 0.17 server. There is no 0.17 client to
upgrade to, so the only coherent target is **0.18 on both sides**, which drags
in a `@colyseus/schema` major (4 → 5) and `zod` 3 → 4.

This is a two-app protocol cutover with a hard client/server version lock, not
a dependency patch.

## What was empirically verified

Attempted in an isolated worktree off `origin/main`, bumping
`@colyseus/core` `^0.16.24 → ^0.17.50` and `@colyseus/ws-transport`
`^0.16.5 → ^0.17.13` (`@colyseus/schema` stays at 4.x — 0.17 peers on `^4.0.7`).

**Server side: works.** Only two mechanical source edits were needed, both
predicted by the migration guide:

| Break                                                            | Fix                                                              |
| ---------------------------------------------------------------- | ---------------------------------------------------------------- |
| `Room<State>` generic is now a room-options object               | `Room<OfficeStateSchema>` → `Room<{ state: OfficeStateSchema }>` |
| `onLeave(client, consented: boolean)` → `(client, code: number)` | derive `consented` from `code === CloseCode.CONSENTED` (4000)    |

Evidence at that commit:

- `pnpm typecheck` — 10/10 tasks pass
- `pnpm test` — 10/10 tasks, **1068 tests pass** (colyseus app: 19 files / 166 tests)
- `pnpm --filter @selva/colyseus lint` — 0 errors (9 pre-existing warnings)
- Server boots on 0.17.50; `/health` green
- Real room lifecycle exercised: Room created → onAuth → Client joined →
  Client left (`code:4000, consented:true`) → Room disposed
- `generateId()` verified working — roomId/sessionId minted as valid 9-char
  IDs (`qUCSCmXkM`, `JlH_5vM88`). This is the exact path the forced-nanoid-3.x
  break destroyed, so it is the load-bearing proof the CVE cure works.
- Trivy 0.70.0 (CI's version): `pnpm-lock.yaml` **HIGH 2 → 0**, all three
  lockfiles clean. `nanoid@2.1.11` disappears from the lockfile entirely.

## The blocker: client/server protocol lock

0.17 **flattened the seat reservation**. The server now returns:

```json
{ "name": "office", "sessionId": "JlH_5vM88", "roomId": "qUCSCmXkM", "processId": "6shYOHiUp" }
```

`colyseus.js@0.16.22` expects the old nested shape and reads
`response.room.name` (`colyseus.js/build/cjs/Client.js:116`). Against a 0.17
server `response.room` is `undefined`, so a real 0.16 client join fails with:

```
Cannot read properties of undefined (reading 'name')
```

Verified by driving the actual `colyseus.js@0.16.22` package against the
upgraded server — not inferred from changelogs.

**There is no 0.17 client.** `colyseus.js` stops at **0.16.22**. The successor
package is `@colyseus/sdk`, which only publishes **0.18.x** and pins
`@colyseus/core` to `0.18.x`. So the upgrade cannot stop at 0.17.

## Real target: 0.18 on both sides

| Package                          | Now     | Target      | Note                                   |
| -------------------------------- | ------- | ----------- | -------------------------------------- |
| `@colyseus/core` (apps/colyseus) | 0.16.24 | 0.18.8      | nanoid `^3.3.11` — clears both CVEs    |
| `@colyseus/ws-transport`         | 0.16.5  | 0.18.x      | peer-locked to core                    |
| `@colyseus/schema`               | 4.0.30  | **^5.0.8**  | **major**, both sides                  |
| `colyseus.js` (apps/office-ui)   | 0.16.22 | **removed** | replaced by `@colyseus/sdk@0.18.2`     |
| `zod`                            | 3.25.76 | **^4.1.12** | core 0.18 peer; repo-wide blast radius |

### Work items

1. **Server** — the two mechanical fixes above, re-verified on 0.18 (0.18 may
   add more; only 0.17 was validated).
2. **Schema v4 → v5** — `apps/colyseus/src/schema/{OfficeState,Whiteboard}.ts`
   plus every `@colyseus/schema` import in tests. Both sides must agree; the
   serializer is the wire format, so a mismatch is a silent decode failure.
3. **Client** — rewrite `apps/office-ui/src/hooks/useColyseus.ts` (332 lines,
   the single integration point) onto `@colyseus/sdk`. Also touches
   `OfficeExperience.tsx`, `SimplifiedView.tsx`, `HUD.tsx`.
4. **zod 3 → 4** — repo-wide; currently only an unmet-peer warning, but it is
   a real major.
5. **Deploy** — client and server are version-locked, so this is a **hard
   cutover**, not a rolling upgrade. A 0.16 client hitting a 0.18 pod fails to
   join. Sequencing (and whether a brief maintenance window is acceptable) is
   an operator decision. See [`COLYSEUS_SCALING.md`](COLYSEUS_SCALING.md) for
   the current topology.

### Known landmine to re-check

`ArraySchema.flatMap` is broken in colyseus schema and requires
`Array.from()` first. The current code is **not** relying on that workaround
for ArraySchema — the one `Array.from` in
`apps/colyseus/src/handlers/proximity.ts:100` wraps a `MapSchema.entries()`
call, which is ordinary iterator materialization. Re-verify against schema v5
during the migration, since v5 rewrites the collection internals.

## Recommendation

Defer. The CVEs are DoS-only and unreachable in this codebase (every
`generateId()` call site uses the hardcoded default length; no attacker input
reaches nanoid's `size`) — the full argument is in `.trivyignore`. Carry the
suppression until the office-ui client migration is scheduled on its own
merits, then do 0.18 across both apps in one change and delete the
suppression.

The alternative — shipping the server bump alone — would take the office
offline for every existing client. That is strictly worse than the deferred
DoS exposure.
