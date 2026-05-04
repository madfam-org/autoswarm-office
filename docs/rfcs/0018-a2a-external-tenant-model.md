# RFC 0018 — A2A External-Tenant Model

| Field | Value |
|---|---|
| Status | Draft |
| Author | Architect (Selva Office) |
| Created | 2026-05-03 |
| Supersedes | — |
| Related | RFC 0001 (Onboarding), `docs/RLS_PHASE_1_5_AUDIT.md` §2.E, migration 0027 (Stripe state mirror), `apps/nexus-api/nexus_api/billing_tiers.py` |

## 1. Status quo and the smell

The A2A protocol bridge in `apps/nexus-api/nexus_api/main.py:228-326`
funnels every inbound `tasks/send` and `tasks/sendSubscribe` request
through a single synthetic org:

```python
async with tenant_session(org_id="a2a-external") as db:
    task = SwarmTask(
        ...
        org_id="a2a-external",
    )
```

The synthetic `"a2a-external"` org_id was introduced in PR #126 to
satisfy the RLS Phase 1.5 strict-mode contract (`tenant_session`
requires a non-empty `app.current_org_id`). It is functionally
correct under RLS but is a tenancy anti-pattern.

What "a2a-external" is missing today:

1. **No `tenant_configs` row** — no `subscription_tier`, no
   `max_daily_tasks`, no `voice_mode`, no `stripe_customer_id`. Every
   downstream gate that reads `tenant_configs` (billing, email
   lockdown, intelligence enablement) treats it as the default null
   tenant.
2. **No quota enforcement** — `swarms.py` consults
   `billing_tiers.TIER_DAILY_TASK_LIMIT` keyed on
   `subscription_tier`. With no row, A2A callers fall through to the
   `DEFAULT_TIER = "starter"` fallback (1000 tasks/day) — but it is
   shared across **every** A2A caller globally. One noisy peer
   exhausts the budget for all peers.
3. **No consent ledger entry** — outbound voice mode is gated on a
   ledger row signed with `CONSENT_LEDGER_SIGNING_SECRET`. A2A
   callers cannot trigger any tool that reads `voice_mode` because
   the gate fails closed, but they also cannot opt in. This is a
   product gap, not just a security one.
4. **No identity verification** — the A2A server accepts any HTTP
   client that can reach the public endpoint. `agent_card.json`
   discovery is one-way (we publish ours; we do not require theirs).
5. **No per-caller billing attribution** — every dollar of LLM spend
   for A2A traffic lands on the `"a2a-external"` cost line in Dhanam.
   We cannot answer "which peer cost us the most this month?".
6. **No revocation** — to block one bad actor we have to either
   disable the entire `/api/v1/a2a` router or add an IP-allowlist
   middleware (we have neither).
7. **No audit accountability** — `audit_logs.org_id` is
   `"a2a-external"` for every action, so the ledger collapses
   distinct callers into one undifferentiated stream.

The smell is structural: A2A is a *peer protocol*, but our tenancy
model represents peers as a single shared org. The fix is to model
each AgentCard URL we trust as its own first-class tenant.

## 2. Proposed model

Each A2A caller (uniquely identified by its `agent_card_url`) is a
real tenant in Selva, with its own row in a new `external_a2a_callers`
table that *complements* `tenant_configs` rather than replacing it.

### 2.1 Tenant identity contract

| Property | A2A caller | Regular tenant |
|---|---|---|
| Identifier | `agent_card_url` (UNIQUE) | `org_id` |
| Auth surface | Signed JWT or mTLS (TBD §5) | Janua SSO |
| Onboarding | Self-serve via `POST /api/v1/a2a/register` (TBD) | `/onboarding` flow |
| Voice mode | Forced to `agent_identified` (peer-to-peer is never user-direct) | User chooses |
| Marketplace publish | Denied (untrusted source) | Allowed |
| HITL approvals | Denied (no human on the other end) | Allowed |
| Skill selection | Bound to AgentCard skill list | Full registry |
| Billing | Free tier with per-caller quota; paid tier TBD §7 | Stripe subscription |

### 2.2 Org-id derivation

Each A2A caller is assigned a deterministic `org_id` of the form
`a2a:<sha256(agent_card_url)[:16]>`. This:

- Keeps the existing `org_id` column shape (string, max 255).
- Is deterministic — re-registering the same URL idempotently resolves
  to the same row.
- Is namespaced under the `a2a:` prefix so the audit trail and
  billing reports can filter A2A traffic in one query.
- Avoids leaking the AgentCard URL into every `swarm_tasks.org_id`
  cell (the URL itself can be PII or competitive intel).

The mapping `org_id ↔ agent_card_url` is the single row in
`external_a2a_callers`.

### 2.3 Why a separate table (not a flag on `tenant_configs`)

Considered: add `is_external_a2a BOOLEAN` + `agent_card_url TEXT` to
`tenant_configs`. Rejected because:

1. `tenant_configs` already has 25+ columns scoped to *human-operated*
   tenants (RFC, razon_social, voice_mode, brand_logo_url, Stripe
   subscription state, outbound identity). Most are NULL/inapplicable
   for an A2A peer.
2. The auth surface differs (signed JWT vs Janua SSO) — modelling
   them in one table would require nullable auth columns that mean
   different things depending on the row type.
3. The audit/ops dashboards already special-case `tenant_configs` as
   "the customer table". Adding peer rows would muddy every report.
4. A separate table makes the revocation primitive trivial:
   `UPDATE external_a2a_callers SET status='revoked' WHERE id=...`.

The cost is one JOIN at dispatch time to resolve the caller's tier.
That JOIN is already amortised by an index on `agent_card_url`.

## 3. Schema changes

### 3.1 New table — `external_a2a_callers`

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `id` | UUID | PK | `uuid4()` default |
| `name` | VARCHAR(255) | NOT NULL | Human-readable label, from AgentCard `name` |
| `agent_card_url` | VARCHAR(2048) | NOT NULL, UNIQUE | The peer's `/.well-known/agent.json` URL |
| `public_key` | TEXT | NULL | PEM-encoded key for JWT signature verification (Option B in §5) |
| `status` | ENUM('active','suspended','revoked') | NOT NULL, default `'active'` | Revocation primitive |
| `subscription_tier` | VARCHAR(32) | NOT NULL, default `'external_a2a'` | Maps to `TIER_DAILY_TASK_LIMIT` (new tier slug) |
| `daily_task_limit` | INTEGER | NOT NULL, default 100 | Per-caller cap; overrides tier default when set |
| `created_at` | TIMESTAMPTZ | NOT NULL | `now()` default |
| `last_seen_at` | TIMESTAMPTZ | NULL | Touched on every successful `tasks/send` |
| `owner_user_id` | VARCHAR(255) | NULL | The MADFAM user who approved this caller (for accountability) |

Indexes:
- `ix_external_a2a_callers_agent_card_url` (UNIQUE, redundant with the
  column constraint but pinned for query planner clarity)
- `ix_external_a2a_callers_status` (filter `WHERE status='active'`
  on the dispatch hot path)

### 3.2 New tier slug

Add `"external_a2a": 100` to `TIER_DAILY_TASK_LIMIT` in
`apps/nexus-api/nexus_api/billing_tiers.py`. (NOT in this RFC's
scaffold PR — this lands with the cutover PR.)

### 3.3 No changes to `swarm_tasks`

`swarm_tasks.org_id` continues to hold the deterministic
`a2a:<hash>` id. The JOIN to `external_a2a_callers` happens at
dispatch / quota-check time, not at row write time. Callbacks (status
polling) re-derive the same org_id from the AgentCard auth claim.

## 4. Migration path

Three release cycles, each one non-breaking on its own.

### Phase A — Scaffold (this RFC's companion PR, migration 0029)

- Create `external_a2a_callers` table.
- Add the SQLAlchemy model.
- Add a smoke test (CRUD + UNIQUE).
- **No behavior change.** `_dispatch_a2a_task` still uses
  `org_id="a2a-external"`.

### Phase B — Identity + lookup (next PR)

- Add `register_external_a2a_caller(agent_card_url, public_key)`
  helper.
- Add admin endpoints: `POST /api/v1/admin/a2a/callers`,
  `GET /api/v1/admin/a2a/callers`,
  `PATCH /api/v1/admin/a2a/callers/{id}` (status only).
- Add the verification middleware (signed JWT path — see §5).
- **Still no behavior change** — A2A bridge keeps the synthetic org.

### Phase C — Cutover (subsequent PR, gated by `A2A_PER_CALLER_TENANT` env flag)

- `_dispatch_a2a_task` resolves the caller via the verified JWT
  claim, looks up `external_a2a_callers` row, derives the
  deterministic `org_id`, and writes the SwarmTask under that org.
- Quota check inserted before the SwarmTask INSERT (consults
  `daily_task_limit` first, falls through to
  `TIER_DAILY_TASK_LIMIT["external_a2a"]`).
- Existing `"a2a-external"` rows are **not** rewritten — they remain
  attributed to the legacy synthetic org for audit continuity. A
  one-off backfill script (offline, ops-run) can move them to a
  designated "legacy" caller row if attribution analysis ever
  requires it.
- Feature flag default: `A2A_PER_CALLER_TENANT=false` (legacy path).
  Flip to `true` after 7-day soak.

### Phase D — Deprecation (cycle after Phase C is stable)

- Remove the `"a2a-external"` synthetic-org code path.
- The `tenant_session_helper` regression test that pins the literal
  string `tenant_session(org_id="a2a-external")` is updated to assert
  the per-caller resolution helper is called instead.
- Drop the feature flag.

## 5. Auth / verification — TBD, options analysis

How do we trust that an inbound caller is who they claim to be?

### Option A — DNS verification (TXT record)

The peer publishes `_selva-a2a.<domain>. IN TXT "selva-verified=<token>"`.
Pre-registration generates a one-time token; the peer adds it; we
poll the DNS until it resolves.

- Pros: zero crypto on hot path; simple to operate; aligns with
  ACME / Stripe Connect patterns.
- Cons: DNS propagation latency (up to 48h); cannot verify
  per-request (only per-registration); doesn't authenticate the
  request body.
- Verdict: necessary but not sufficient — pair with B or C.

### Option B — Signed JWT in `Authorization: Bearer ...`

The peer signs requests with a private key whose public counterpart
is registered in `external_a2a_callers.public_key`. Standard JWS
(`alg: ES256` or `RS256`), `iss` claim equals `agent_card_url`,
`exp` <= 5min from `iat`.

- Pros: per-request authentication; rotatable; no DNS dependency on
  hot path; matches the JWT pattern Janua already uses internally.
- Cons: peer must implement JWT signing (most A2A SDKs already do);
  key rotation needs an admin endpoint.
- Verdict: **recommended primary**. Pair with A for initial
  registration verification.

### Option C — mTLS

Peer presents a client cert; we verify against a CA bundle stored on
the gateway.

- Pros: strongest; transparent to the peer's application code.
- Cons: Cloudflare tunnel does not natively pass through client
  certs without paid ZTNA; cert provisioning / rotation is heavy;
  adds an ingress dependency.
- Verdict: future option for high-trust enterprise A2A peers.
  Out of scope for v1.

### Option D — Callback verification

We dispatch the task, then make a callback HTTP request to the
peer's AgentCard URL with a nonce; the peer must echo it back.

- Pros: no crypto; no pre-registration step.
- Cons: doubles every request's network footprint; race conditions
  on first contact; vulnerable to a replay between peer and us.
- Verdict: rejected.

**Recommendation**: **Option A (registration) + Option B (per-request)**.
DNS gates registration, JWT gates each request. Public key registered
during DNS-verified registration step.

## 6. Quota enforcement

At dispatch time, after JWT verification but before the SwarmTask
INSERT:

```python
caller = await db.get(ExternalA2ACaller, caller_id)
if caller.status != "active":
    raise HTTPException(403, "caller suspended/revoked")

limit = caller.daily_task_limit or TIER_DAILY_TASK_LIMIT.get(
    caller.subscription_tier, TIER_DAILY_TASK_LIMIT[DEFAULT_TIER]
)

count_today = await _count_tasks_today(db, caller_org_id)
if count_today >= limit:
    raise HTTPException(429, "daily task limit reached")
```

`_count_tasks_today` is a `SELECT COUNT(*) FROM swarm_tasks WHERE
org_id = :org AND created_at >= date_trunc('day', now())`. Cached in
Redis with key `autoswarm:a2a-quota:<org_id>` and 60s TTL — same
pattern as the existing tier cache (`autoswarm:tier:<org_id>`).

`429` response includes `Retry-After: <seconds-until-midnight-UTC>`
and a JSON body matching the A2A error envelope.

## 7. Billing accounting

Three modes proposed; v1 picks (a). (b) and (c) deferred.

(a) **Free tier with quota cap** — every A2A caller gets the
  `external_a2a` tier (100 tasks/day default). Token usage logged in
  `task_events` with `event_category="llm.response"` and rolled up
  in the metrics dashboard, but not billed. Cost lands on a
  consolidated `platform-cost-a2a` line in Dhanam.

(b) **Paid A2A tier** — peer presents a Stripe customer ID at
  registration; usage charged like a regular tenant. Requires
  Stripe Connect or a separate pricing SKU. Out of scope.

(c) **Per-call micropayments** — Lightning / x402 style. Way out of
  scope; flagged for a future RFC if A2A traffic ever justifies it.

The metrics dashboard (`routers/metrics.py`) gains a new pivot:
"A2A callers" tab listing each `external_a2a_callers` row with
its 24h / 7d / 30d task counts, token spend, error rate.

## 8. Open questions

| # | Question | Provisional answer |
|---|---|---|
| Q1 | What happens to existing `"a2a-external"` rows in production? | Leave in place; do not migrate. Add a `LEGACY_A2A_EXTERNAL_ORG_ID` constant pointing to that string so callers can still query them by the old id. After 90 days of zero new traffic, archive to cold storage. |
| Q2 | Can A2A callers use HITL approvals? | No. There is no human on the peer side who can satisfy an `interrupt()`. Auto-deny any graph that requires approval; surface this in the AgentCard's skill metadata so the peer knows up-front. |
| Q3 | Can A2A callers publish skills to the marketplace? | No. Marketplace publish is a trust action; A2A peers are by definition external. They CAN install skills (read path) — but only from the curated subset (no `community_skills_enabled` toggle). |
| Q4 | Voice-mode lockdown for outbound from A2A-dispatched tasks? | Forced to `agent_identified`. Co-branded "Selva on behalf of <peer>" is dishonest because there is no signed delegation chain. `user_direct` is impossible (no user). |
| Q5 | What `agent_card_url` do we publish for ourselves? | Same as today: `https://api.selva.town/api/v1/a2a/.well-known/agent.json`. The change is on inbound only. |
| Q6 | Rate-limit per-IP in addition to per-caller? | Yes, keep the existing IP-based middleware as defence-in-depth (one caller, many IPs is fine; many callers, one IP smells like a relay). |
| Q7 | What about the existing `tenant_session_helper` regression test that pins the literal `tenant_session(org_id="a2a-external")`? | Updated in Phase D to assert the per-caller resolution helper is called instead. Until then it stays. |

## 9. Acceptance criteria (cutover PR — Phase C)

- [ ] `external_a2a_callers` table exists in production (migration 0029 already deployed by Phase A).
- [ ] At least one `external_a2a_callers` row exists (the seed/test peer).
- [ ] `_dispatch_a2a_task` rejects requests without a valid signed JWT (`401`).
- [ ] `_dispatch_a2a_task` rejects requests from suspended/revoked callers (`403`).
- [ ] `_dispatch_a2a_task` rejects requests over the daily quota (`429` with `Retry-After`).
- [ ] `_dispatch_a2a_task` writes SwarmTasks under the deterministic per-caller `org_id` (not `"a2a-external"`).
- [ ] `_get_a2a_task_status` resolves the same per-caller `org_id` from the JWT and reads the task under that scope.
- [ ] Audit log entries for A2A traffic carry the per-caller `org_id`, never `"a2a-external"`.
- [ ] Metrics dashboard "A2A callers" pivot shows per-caller task counts.
- [ ] `A2A_PER_CALLER_TENANT` env flag toggles the new path (`false` = legacy).
- [ ] Feature flag flipped to `true` in production after 7-day soak.
- [ ] Regression: HITL-required graphs auto-deny when dispatched by A2A caller.
- [ ] Regression: Voice mode for A2A-dispatched outbound is forced to `agent_identified`.
- [ ] Documentation: `docs/A2A_PEER_ONBOARDING.md` published with DNS + key-registration walkthrough.

---

*Sections written above: §1-§9 complete. No TBDs in §1, §3, §4, §6, §7,*
*§8, §9. §2.1/§2.2/§2.3 complete. §5 written as options analysis with*
*explicit recommendation; the final auth choice is technically still*
*"TBD pending one round of stakeholder review" but a concrete*
*recommendation is on record.*
