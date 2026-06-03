# selva-tools

Tool registry and built-in tools for Selva agent workflows. ~240
tools across file ops, code exec, git, web, data, communication,
artifacts, MCP, and Mexican-market integrations
(Karafiel/Dhanam/PhyneCRM/Tezca).

This document covers a small slice of the registry that needs explicit
explanation. Most tools are self-documenting via the `description`
field and `parameters_schema()`. Read the source under
`src/selva_tools/builtins/` for the full surface.

## LinkedIn — DRAFT ONLY (no posting)

The LinkedIn integration in this package is deliberately **draft-only**.
There is no `linkedin_post` tool, and there will not be one. This is
the only public-social channel we have where agents do not post
directly.

### Why drafts only

- LinkedIn has no automation-friendly promo-posting API. The Marketing
  API requires partnership status MADFAM does not (and likely will not)
  hold. The public REST API only allows posting via tokens granted to
  a *signed-in human user*. There is no agent-runtime equivalent of
  PRAW (Reddit), at-protocol (Bluesky), or the Mastodon HTTP API.
- Every "LinkedIn automation" SaaS in the wild operates either by
  reverse-engineering the cookie session (ToS violation, account-ban
  risk) or by holding a user's password (worse). We will do neither.
- For MADFAM's B2B audience (Karafiel = Mexican accountants, Selva =
  founders/CTOs) LinkedIn is the highest-leverage channel — we cannot
  skip it. The pragmatic compromise is **drafts**.

### How it works

1. An agent calls `linkedin_draft_create(audience, platform, topic, body=…, tone=…)`.
2. The tool validates `audience` and `platform` against server-side
   allow-lists (no LLM-controlled freeform values here — same pattern
   as `_AGENT_ROLE_ALLOWLIST` on email tools).
3. The full draft body is saved to artifact storage at the logical
   path `linkedin_drafts/<YYYY-MM-DD>/<draft_id>.md`. Storage backend
   is content-addressable; a sidecar index file under
   `linkedin_drafts_index/<date>/<draft_id>.idx` maps the logical path
   to the SHA-256 storage path.
4. The frontmatter records `audience`, `platform`, `topic`,
   `created_at`, `char_count`, `status: draft`. The body is followed by
   a HOOK section (first 140 chars — what shows above LinkedIn's "see
   more" fold on mobile) and operator instructions.
5. The result returns `{draft_id, draft_path, preview, char_count, hook}`.
   The operator browses recent drafts via `linkedin_draft_list` (filter
   by `status="draft"`, default limit 20) and copy-pastes the body into
   <https://linkedin.com/feed> manually.

### LinkedIn-specific tuning

- Posts work best in the 1300-1500 char range for B2B audiences (per
  multiple 2024-2025 organic-reach analyses). The default `max_chars`
  is 3000 (LinkedIn's hard limit) and the minimum is 200.
- The "see more" cutoff is ~140 chars on mobile, ~210 on desktop.
  Anything past the cutoff is hidden until a click. The first 140
  chars therefore carry disproportionate weight — the **hook**.
- `extract_hook()` picks the natural sentence boundary (`.`/`?`/`!`)
  inside the first 140 chars when one exists, falling back to a
  hard cut at 137 chars + `...` otherwise.
- DO NOT add an "AI generated" disclosure footer. The LinkedIn algorithm
  penalizes such disclosures heavily. Because the operator pastes
  manually, the post is — under most platform-ToS readings — the
  operator's own content. This is the inverse of the Reddit policy
  (mandatory disclosure because the post is automated end-to-end).

### Operator workflow

1. Agents stage drafts during the work day via
   `linkedin_draft_create(...)`. Each call is idempotent on the
   content (content-addressable storage de-dupes byte-identical
   drafts).
2. At review time the operator runs (in any swarm session):
   ```
   linkedin_draft_list(status="draft", limit=20)
   ```
   to enumerate what's queued. The result lists draft_id, audience,
   platform, topic, char_count, created_at, and the storage_path.
3. For each draft worth posting, fetch the artifact (e.g. via
   `retrieve_artifact` against `storage_path`), eyeball the body and
   the hook, copy-paste the body into linkedin.com/feed -> New Post.
4. Optional: update the artifact's frontmatter `status` field to mark
   the draft as `published` so subsequent `linkedin_draft_list` calls
   filter it out. (No tool ships for this yet — manual edit if you
   care; `linkedin_draft_list` defaults to `status="draft"` so
   un-marked drafts naturally sort to the top.)

### Audience tag

Both `linkedin_draft_create` and `linkedin_draft_list` are
`Audience.TENANT` (default). Any tenant swarm can stage drafts for its
own org's social calendar. There is no platform-only LinkedIn surface.

### Permission category

Drafts are pre-staging marketing content. They use the existing
`ActionCategory.MARKETING_SEND` permission category (default level
`ASK`) — same as email + marketing-push. **No new permission category
is added** for LinkedIn drafting; that would proliferate the matrix
without adding signal.

### Tests

`packages/tools/tests/test_linkedin_drafts.py` covers:
- audience/platform/tone/topic/max_chars validation
- hook extraction at sentence boundaries + hard-cut fallback
- char_count accuracy
- frontmatter rendering
- artifact saved at the expected content-addressable path + the
  sidecar index file at `linkedin_drafts_index/<date>/<id>.idx`
- list tool returns recent drafts, respects `limit`, filters by
  `status`
- regression test: there is no `linkedin_post` tool in the registry
  and no module attribute named anything containing "post". This
  guard rejects future PRs that try to add posting.
