# RLS Phase 1.5 Audit + Tightening Plan

> **Status**: planning artifact (this PR ships no schema changes).
> The actual tightening migration (`0027_tighten_rls_policies.py`) and
> code wiring lands in the follow-up implementation PR.
>
> **Audience**: anyone touching tenant-scoped DB code, anyone reviewing
> the follow-up migration, ops on rollout day.
>
> **Bottom line**: PR #93 / migration `0025` enabled RLS on 18 tenant
> tables with a deliberately permissive `IS NULL OR = '' OR = $org_id`
> policy so unauthenticated paths kept working. We now know exactly
> which paths rely on that escape hatch (count: **9 distinct categories,
> ~13 concrete code locations**). This doc enumerates them, recommends
> **Option B** (separate `app_admin` Postgres role with `BYPASSRLS` for
> ops, force-RLS for `autoswarm_app`), and drafts the migration SQL +
> rollout/rollback plan.

---

## 1. Why the Phase 1 escape hatch exists

Migration `0025` (commit `57014eb` ancestor, merged ~24h ago) does this
for every tenant-scoped table:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_<t> ON <t>
FOR ALL
USING (
    current_setting('app.current_org_id', true) IS NULL
    OR current_setting('app.current_org_id', true) = ''
    OR org_id = current_setting('app.current_org_id', true)
)
WITH CHECK (<same>);
```

The `IS NULL OR = ''` legs are the escape hatch. Three things rely on
them today:

1. **Alembic** runs as superuser with no session var — so
   `current_setting(..., true)` returns `NULL` and the policy permits
   the migration's data DML. (Schema-changing DDL is not policy-gated,
   so this only matters for migrations that backfill rows.)
2. **Code paths that call `async_session_factory()` directly** (i.e.
   not via the `get_db` dependency that calls `_set_session_org_id`)
   never set the session var. The variable is unset → `NULL` →
   permissive.
3. **The `org_id_var` ContextVar default is `"default"`** (see
   `apps/nexus-api/nexus_api/middleware/security.py:14`). Anonymous
   requests that DO go through `get_db` get `"default"` written into
   the session var. The escape hatch does NOT fire for them — they
   match `org_id = 'default'`, which by happy accident is the column
   default for every tenant model (see `models.py`, every `org_id`
   column declares `default="default"`).

That coincidence is the load-bearing detail behind Phase 1 working at
all: rows seeded without an explicit `org_id` land in `"default"`, and
anonymous reads against tenant tables (e.g. via an unscoped router
that forgot `Depends(get_current_user)`) return only the `"default"`
slice rather than everything. **It is not a designed invariant** — it
is a bug-bug cancellation. Phase 1.5 must replace it with intent.

---

## 2. Inventory: every "no tenant context" path

Categories and concrete locations. For each: **does it currently set
the session var?** ("no" = bypasses `_set_session_org_id`), **what
tables does it touch?**, and **what happens after tightening?**.

### A. Migrations and seeds

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `apps/nexus-api/alembic/env.py` (Alembic up/down) | no — runs as DB superuser | every tenant table during DDL backfills | Migrations run as the DB role configured in `DATABASE_URL`. If that role is the app role (`autoswarm_app`), data backfills inside future migrations break. If it's a superuser, RLS is bypassed automatically. **Need: a documented requirement that Alembic must run as a `BYPASSRLS` role**. |
| `scripts/seed-agents.py` | no — calls HTTP API at `localhost:4300` | `departments`, `agents`, permission rows | Goes through nexus-api → `get_db` → `_set_session_org_id`. JWT-derived `org_id` ("dev-org" via dev bypass) flows through. **Works after tightening** as long as the dev bypass continues to set `org_id_var.set("dev-org")` in `auth.py:131`. |
| `scripts/seed-madfam-org.py` | no — calls HTTP API too | `departments`, `agents` | Same as above. |
| (no other seed/fixture scripts found) | — | — | — |

**Verdict for category A**: low risk if Alembic runs as a role with
`BYPASSRLS`. We currently have no enforcement of which role runs
migrations — `DATABASE_URL` is set per-environment. Recommended:
mandate two distinct DB roles (see Option B in §3).

### B. Health and probe endpoints

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `apps/nexus-api/nexus_api/routers/health.py` `/health`, `/ready`, `/detail`, `/pool-stats`, `/queue-stats`, `/dlq-stats` | no DB tenant access (`SELECT 1` via `async_session_factory`) | none tenant-scoped | Safe — `SELECT 1` is unaffected by RLS. |
| `apps/nexus-api/nexus_api/routers/health.py:228` `/health/consent-ledger-grants` | yes via `Depends(get_db)`, but unauthenticated → `org_id_var = "default"` | `consent_ledger` (in `_TENANT_TABLES`), runs `has_table_privilege(...)` (catalog query — not row-filtered) | Catalog functions ignore RLS, so safe. The session var ends up as `"default"`, harmless for this query. |
| `apps/nexus-api/nexus_api/routers/probe.py` `/probe/*` (4 endpoints) | bearer-auth'd via `NEXUS_PROBE_TOKEN` (not Janua JWT, not worker token) — does **not** call `get_current_user`, so `org_id_var` is whatever `TenantRLSMiddleware` set it to (`"default"`) | `latest-run` and `history` live in **Redis**, not Postgres | Safe — no Postgres tenant tables touched. |

**Verdict for category B**: safe. The only DB-touching health endpoint
(`consent-ledger-grants`) hits Postgres catalog functions which are
unaffected by RLS.

### C. Demo and unauthenticated paths

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `/demo` (office-ui only — Next.js client) | no Postgres access at all; client mints unsigned `org_id="demo-public"` JWT consumed by Colyseus only | none from nexus-api | Safe. Demo never enters nexus-api with a real DB session. |
| Landing page `/` (server-rendered) | no Postgres access | none | Safe. |
| Onboarding preview `GET /api/v1/onboarding/voice-mode/preview/{mode}` (`onboarding.py:554`) | needs verification (see Open Questions) | `tenant_configs` (in `_TENANT_TABLES`) if it reads brand info — **must check** | **Action item**: confirm whether the preview endpoint is anonymous and what it reads. If it reads `tenant_configs` with no `org_id` context, it relies on the escape hatch. |
| `POST /api/v1/swarms/tasks/reap-stale` (`swarms.py:688`) | yes via `Depends(get_db)`, **explicitly unauthenticated** (comment: "No auth required (internal endpoint)") | `swarm_tasks` (TENANT) — needs to scan ALL orgs | **WILL BREAK after tightening.** Currently relies on default `"default"` session var, but only reaps tasks for `org_id="default"`. Even today this is a silent bug — it only reaps the default-org slice, not the actual cross-tenant queue. **Needs a platform-bypass mechanism**, not the escape hatch. |

**Verdict for category C**: `reap-stale` is the canonical example of an
endpoint that genuinely needs to bypass RLS (cross-tenant ops), is
already partially broken under Phase 1, and **must** be fixed by
tightening. The onboarding preview needs a 5-minute audit before the
follow-up PR.

### D. Worker startup and runtime

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `apps/workers/selva_workers/__main__.py` startup | no Postgres at all — workers use Redis Streams + HTTP back to nexus-api | none directly | Safe. Workers never touch Postgres directly. |
| `_cleanup_stale_worktrees` | filesystem only | none | Safe. |
| `_fetch_agent_skills` global cache | calls `GET /api/v1/agents/{id}` over HTTP with `X-Selva-Tenant-Org: <org_id>` (centralized via `auth.py:get_worker_auth_headers`) | `agents` (read) via nexus-api | Safe — nexus-api scopes by header-derived `org_id`. The header MUST be set; missing header → `org_id="platform"` per `auth.py:155-160`, and the agent row is unlikely to be in the platform org. **This is correct strict behaviour** — silent miss is a bug we want surfaced. |
| `task_status.py`, `event_emitter.py`, `interrupt_handler.py`, `learning.py` | all call nexus-api over HTTP with `X-Selva-Tenant-Org` header | various TENANT tables (writes via API) | Safe. |
| `packages/tools/src/selva_tools/approval.py:202` `_persist_and_broadcast` | **direct DB access from worker process** via `nexus_api.database.AsyncSessionLocal` | `command_approval_requests` (NOT in `_TENANT_TABLES` — scoped by `run_id`) | Safe today AND after tightening — `command_approval_requests` is intentionally excluded from `_TENANT_TABLES`. |

**Verdict for category D**: workers are clean by design. The single
direct-DB call in `selva_tools/approval.py` writes to a non-tenant
table.

### E. Cross-tenant maintenance ops

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `apps/nexus-api/nexus_api/routers/admin.py` `/admin/users`, `/admin/kick`, `/admin/room-config` | requires `admin` role JWT — `org_id_var` set from JWT `org_id` (admin's org) | `swarm_tasks` (none directly), Redis pub/sub | Safe **as long as admin endpoints stay scoped to one org**. Cross-org admin (MADFAM ops kicking a tenant user) needs the platform-bypass mechanism. |
| `apps/nexus-api/nexus_api/middleware/audit.py` `_insert_audit_log` | **uses `async_session_factory()` directly, NOT `get_db`** — session var never set despite `org_id_var` being set in the request flow | `audit_logs` (TENANT) — INSERT only | **WILL BREAK after tightening.** Today the insert succeeds via the `IS NULL` escape hatch; tightened policy will reject the INSERT because `org_id != current_setting(..., true)` (the latter being NULL). **Fix**: switch to `get_db` OR call `set_config` manually in the middleware. Either way, fix in the follow-up PR. |
| `apps/nexus-api/nexus_api/routers/marketplace.py` (publish/install) | `Depends(get_current_user)` at router level, so `org_id_var` set | `skill_marketplace_entries`, `skill_ratings` (both TENANT) | Safe. The marketplace is org-scoped on read AND publish (org_id stamped from JWT). |
| `apps/nexus-api/nexus_api/main.py:233` A2A `_dispatch_a2a_task` | **uses `async_session_factory()` directly**, hardcodes `org_id="a2a-external"` on the task | `swarm_tasks` (TENANT) — INSERT | **WILL BREAK after tightening.** Today the insert succeeds via escape hatch (no session var); tightened policy rejects because `org_id="a2a-external" != NULL`. **Fix**: either `get_db`-ify the helper OR explicitly `SET LOCAL app.current_org_id = 'a2a-external'` before the insert. |
| `apps/nexus-api/nexus_api/main.py:289` A2A `_get_a2a_task_status` | **same — direct factory** | `swarm_tasks` (TENANT) — SELECT by id | **Subtle**: the SELECT is by primary key (`SwarmTask.id`), so an "empty result" today returns `None` correctly because `org_id != NULL` → no rows match the filter ANYWAY (since A2A tasks live in `org_id="a2a-external"`). Wait — in Phase 1, NULL session var hits the escape hatch and returns the row. After tightening, NULL would NOT hit the escape hatch and the SELECT returns nothing → A2A status checks always return "not found". **Fix**: same as the dispatch helper. |
| `apps/nexus-api/nexus_api/routers/approvals.py:454,523` (WS initial batch + `_handle_wave`) | **uses `async_session_factory()` directly**, but both have an authenticated `org_id` in scope (from WS auth or wave dispatch arg) | `approval_requests`, `swarm_tasks` (both TENANT) | **WILL BREAK after tightening.** WS initial batch writes/reads with the right `org_id` value baked into the query, but the session var is unset. INSERT will fail policy check; SELECT will return empty. **Fix**: either switch to `get_db` (for the SELECT path inside the WS handler — easy) or wrap the factory call in `_set_session_org_id` (for INSERTs in `_handle_wave`). |
| `apps/nexus-api/nexus_api/routers/events.py:345` (WS initial batch) | **same — direct factory** | `task_events` (TENANT) — SELECT only | **Same break.** Easy fix: wrap with `_set_session_org_id` after WS auth resolves `org_id`. |
| `apps/nexus-api/nexus_api/routers/tenant_identities.py` (3 sites) | direct factory | `tenant_identities` (intentionally NOT in `_TENANT_TABLES`) | Safe — table is excluded from RLS by design (it's a directory keyed by canonical_id). |
| Audit middleware writes to `audit_logs` (re-listed for emphasis) | see above | `audit_logs` | **Will break.** |

**Verdict for category E**: 5 distinct break sites, all sharing the
root cause "code path uses `async_session_factory()` instead of
`get_db`". **The cleanest single fix** is a module-level helper
`async with tenant_session(org_id="..."):` that wraps the factory + a
`SET LOCAL` call, and migrate every direct-factory caller to use it.
That helper plus an `app_admin` BYPASSRLS role for true cross-tenant
ops covers everything.

### F. Scheduled / Celery tasks

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| `apps/nexus-api/nexus_api/celery_app.py` Celery Beat | no — Celery workers run outside HTTP request flow, no `TenantRLSMiddleware` runs, no JWT, no `org_id_var` | depends on the task | See per-task. |
| `tasks/skill_tasks.py:refine_skills_task` (daily) | no | uses `selva_skills.refiner.SkillRefiner` — operates on the in-process skill registry + LLM, **does not touch Postgres tenant tables** | Safe. |
| `tasks/skill_tasks.py:compact_memory_task` (weekly) | no | uses `nexus_api.tasks.memory_tasks.compact_memory` which operates on the **SQLite memory store** (`autoswarm_state.db`) via `nexus_api.memory_store.db.memory_store`, NOT the main Postgres | Safe — wrong DB entirely. |
| `tasks/acp_tasks.py:run_acp_workflow_task` | no | `memory_store` (SQLite) | Safe. |

**Verdict for category F**: Celery tasks today don't touch Postgres
tenant tables, so RLS doesn't bite. **Future-proofing note**: when we
move the memory store to Postgres (RFC TBD) or add Celery tasks that
hit tenant tables, those tasks will need the same `tenant_session` /
`app_admin` mechanism as category E.

### G. Background / fire-and-forget code paths from middleware

| Path | Sets var? | Tables touched | After tightening |
|---|---|---|---|
| Audit middleware `_insert_audit_log` (re-listed) | no | `audit_logs` (TENANT) | Will break — see category E. |

### H. WebSocket initial-batch fetches

Already covered in category E (events.py:345, approvals.py:454). Worth
calling out separately because the WS auth path resolves `org_id` from
the `?token=` query param BUT then uses `async_session_factory()`
without forwarding it to the session var. This is a textbook case
where the `tenant_session(org_id=org_id)` helper would have prevented
the bug from ever existing.

### I. WebSocket message handlers (post-init)

`approvals.py:_handle_wave` is the only one that does new INSERTs from
inside a long-lived WS handler. Already covered in category E.

---

## 3. Recommended tightening: **Option B** (two-role split)

### The three options considered

**Option A — explicit `'platform'` sentinel**

Replace the escape hatch with `current_setting(..., true) = 'platform'`
as the bypass. Pros: pure-SQL, no role gymnastics. Cons: still
permissive (any code path that forgets to set the var defaults to
`NULL` which now FAILS, surfacing bugs — that part is good — but
"platform" is a magic string anyone can write and there's no audit
trail of who's using it). And it does not actually solve the migration
problem (Alembic still needs a way to run schema-changing DDL plus
data backfills).

**Option B — `app_admin` Postgres role with `BYPASSRLS`** ✅ recommended

Two DB roles:

- `autoswarm_app` — what nexus-api connects as in normal operation.
  RLS is enforced via `FORCE ROW LEVEL SECURITY` (so the table-owner
  bypass doesn't apply).
- `app_admin` — what Alembic, the `reap-stale` endpoint, the audit
  middleware insert, and the A2A bridge connect as. Has `BYPASSRLS`.
  Used only for code paths that legitimately need cross-tenant or
  no-tenant access.

Pros:
- Clean, auditable: every cross-tenant query is visible in `pg_stat_activity` as the `app_admin` role.
- Built-in Postgres mechanism — no application logic to maintain.
- Forces a deliberate decision at the connection level, not a session-variable footgun.
- Composes with the `tenant_session(org_id=...)` helper for per-request scoping.

Cons:
- Two `DATABASE_URL`-ish env vars (`DATABASE_URL` for app, `DATABASE_ADMIN_URL` for ops).
- One more thing to bootstrap in dev (the migration that creates the role + grants).
- Need to grant `app_admin` to `autoswarm_app` (or have ops scripts switch role explicitly) so that hot-path code can `SET ROLE app_admin` for very brief cross-tenant work, but we'd avoid this and prefer a separate connection pool.

**Option C — per-table `FORCE ROW LEVEL SECURITY`, mixed bypass**

Some tables get FORCE (no owner bypass), others retain owner bypass for
ops scripts. Pros: granular. Cons: complex to reason about, every new
tenant table is a coin-flip decision, no clean ops-vs-app boundary.

### Why B over A and C

A is fragile (sentinel string footgun). C is granular but adds
per-table cognitive load. B aligns with how every other multi-tenant
Postgres app does this (Heroku PG, Supabase, RDS) and gives ops a
single observable signal: any `app_admin` connection in
`pg_stat_activity` is an explicit cross-tenant op.

The accompanying app code change in the follow-up PR:

```python
# new helper in apps/nexus-api/nexus_api/database.py
@asynccontextmanager
async def tenant_session(org_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with `app.current_org_id` bound to org_id.

    Use this whenever you would otherwise call `async_session_factory()`
    directly. The `get_db` FastAPI dependency continues to be the
    happy path for HTTP request handlers.
    """
    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :v, true)"),
            {"v": org_id},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# new helper for true cross-tenant ops
@asynccontextmanager
async def admin_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session against the `app_admin` connection pool
    (BYPASSRLS). Use ONLY for cross-tenant maintenance — reap-stale,
    audit-log insert, A2A bridge, migrations.

    Logs every entry at WARNING so cross-tenant access is observable.
    """
    logger.warning("admin_session() opened — cross-tenant access path")
    async with get_admin_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

## 4. Migration text (draft, not committed)

```sql
-- Migration 0027 — Tighten RLS policies + add app_admin role.
-- Replaces the IS NULL / = '' escape hatch in policies created by 0025
-- with strict equality. Cross-tenant ops migrate to app_admin role
-- (BYPASSRLS) via a separate connection pool.

-- 1. Create the app_admin role with BYPASSRLS. Grant it the same
--    table privileges as autoswarm_app so ops paths work identically
--    minus the row filter. The role is LOGIN so it can be the
--    DATABASE_ADMIN_URL connection user; if your deployment prefers
--    SET ROLE-from-app-role, drop LOGIN and GRANT app_admin TO autoswarm_app.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
        CREATE ROLE app_admin LOGIN BYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_admin;

-- 2. Re-create every tenant-isolation policy with strict equality.
--    The escape-hatch legs (IS NULL / = '') are removed. Code paths
--    that need cross-tenant access MUST use the app_admin role.
DO $$
DECLARE
    t TEXT;
    tenant_tables TEXT[] := ARRAY[
        'departments', 'agents', 'approval_requests', 'swarm_tasks',
        'workflows', 'artifacts', 'compute_token_ledger',
        'skill_marketplace_entries', 'skill_ratings',
        'calendar_connections', 'maps', 'task_events', 'chat_messages',
        'tenant_configs', 'audit_logs', 'consent_ledger',
        'hitl_decisions', 'hitl_confidence'
    ];
BEGIN
    FOREACH t IN ARRAY tenant_tables
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_%I ON %I', t, t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_%I ON %I FOR ALL '
            'USING (org_id = current_setting(''app.current_org_id'', true)) '
            'WITH CHECK (org_id = current_setting(''app.current_org_id'', true))',
            t, t
        );
        -- FORCE means even the table owner gets policy-checked; only
        -- BYPASSRLS roles (i.e. app_admin) skip the check. This is the
        -- thing that closes the "table owner forgets to scope" hole.
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    END LOOP;
END
$$;

-- 3. (Future hardening, NOT in 0027) Move tenant_identities into
--    tenant scoping with a different policy (canonical_id lookup is
--    cross-tenant by design, but enumeration must be platform-only).
--    Tracked in ROADMAP.md.

-- Downgrade: restore the permissive policy and drop FORCE.
-- DO NOT drop the app_admin role on downgrade — it may have
-- session-active connections. Ops will drop manually if needed.
```

Downgrade body:

```sql
DO $$
DECLARE
    t TEXT;
    tenant_tables TEXT[] := ARRAY[ /* same list */ ];
BEGIN
    FOREACH t IN ARRAY tenant_tables
    LOOP
        EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_%I ON %I', t, t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_%I ON %I FOR ALL '
            'USING ('
            '  current_setting(''app.current_org_id'', true) IS NULL '
            '  OR current_setting(''app.current_org_id'', true) = '''' '
            '  OR org_id = current_setting(''app.current_org_id'', true)'
            ') '
            'WITH CHECK (<same>)',
            t, t
        );
    END LOOP;
END
$$;
```

---

## 5. Test plan (the follow-up PR's test matrix)

Required tests for the implementation PR — not optional, all must
pass in CI before merge.

### Unit / contract tests

- **`test_rls_session_org_id.py`** (existing): update the
  `test_passes_empty_string_when_no_context` contract — after
  tightening, an unset session var no longer means "permissive";
  add a new test asserting the policy returns zero rows for a
  no-context session against a seeded tenant table.
- **New: `test_tenant_session_helper.py`** — verify the
  `tenant_session(org_id=...)` context manager sets the var, commits
  on success, rolls back on exception, and that two concurrent
  sessions don't see each other's var (asyncio task isolation).
- **New: `test_admin_session_helper.py`** — verify `admin_session()`
  bypasses RLS (returns rows from multiple orgs), logs at WARNING on
  every entry, and uses a distinct connection pool.

### Integration tests (Postgres-only, skipped on SQLite)

- **`test_rls_postgres_isolation.py`** (existing — extend):
  - Demo path still returns isolated rows for `org_id="demo-public"`.
  - Health endpoints still return 200 (catalog queries unaffected).
  - `Depends(get_db)` happy path still scopes correctly.
  - **New**: verify that anonymous DB queries against tenant tables
    return ZERO rows (not the `"default"` slice as today).
  - **New**: verify that `app_admin` role queries return rows from
    multiple orgs.
  - **New**: verify INSERT into tenant table from `autoswarm_app`
    role with no session var FAILS (policy WITH CHECK violation).
  - **New**: verify INSERT into tenant table from `app_admin` role
    with no session var SUCCEEDS.

### Code-path regression tests

For each of the 5 break sites identified in §2.E, an explicit test
asserting it works post-tightening:

- `audit_logs` insert via the audit middleware on a real request.
- `swarm_tasks` insert via A2A `_dispatch_a2a_task` returns a UUID.
- `swarm_tasks` SELECT via A2A `_get_a2a_task_status` returns the row.
- `approval_requests` initial-batch fetch on WS connect returns the
  expected pending requests for that tenant.
- `task_events` initial-batch fetch on events WS connect.
- `swarm_tasks` reap-stale across multiple seeded orgs (must reap
  ALL stale tasks, not just `org_id="default"`).

### Migration application tests

- **`test_migration_0027_apply.py`**: spin up a Postgres test
  container, apply 0000→0026, snapshot the policy definitions, apply
  0027, verify the policies match the strict form, verify the
  `app_admin` role exists with `rolbypassrls = true`, downgrade,
  verify the permissive form is restored.

### Worker startup smoke test

- **Updated `make smoke-test`**: add a check that boots a worker,
  has it consume one task end-to-end, and asserts no policy
  violation logs in nexus-api during that flow. (Guards against the
  worker hot path silently relying on the escape hatch.)

---

## 6. Rollback plan

### Why we need a real rollback

Migration 0025 was permissive — wrong policies meant "more rows than
expected" but everything worked. Migration 0027 is strict — wrong
policies mean "fewer rows than expected" or "INSERTs rejected". Most
break modes are "the API works but returns empty data" — silent in
metrics, loud in user reports. **We need to be able to roll back
inside one rollback window (RTO < 5 min)**.

### Three rollback layers, fastest first

1. **Feature flag `RLS_STRICT_MODE` (recommended for the implementation PR)**.
   The follow-up PR ships the migration `0027` AND adds an env var
   `RLS_STRICT_MODE=true|false` (default `false`). When `false`, the
   migration's policies STILL include the IS NULL / = '' legs (i.e.
   the migration is no-op for policies, but creates the `app_admin`
   role + grants). Code paths use `tenant_session()` and
   `admin_session()` — and these continue to work because the
   policies remain permissive. When ops sets `RLS_STRICT_MODE=true`
   in the env, a tiny startup hook runs `ALTER POLICY ...` on every
   tenant table to remove the permissive legs. Rollback: set
   `RLS_STRICT_MODE=false` and restart nexus-api → another startup
   hook restores the permissive policies. **RTO: ~30s** (pod restart).

2. **Alembic downgrade** (`alembic downgrade -1`). Drops the strict
   policies, restores the permissive form, leaves the `app_admin`
   role in place. RTO: depends on rollout, but under 5 min if Argo
   rolls back the manifest revision. Risk: `app_admin` queries that
   were already opened on the strict policies need to be drained or
   they'll see inconsistent behaviour for ~seconds.

3. **Ops manual SQL** (last resort): apply the downgrade body in §4
   directly via `psql`. RTO: as fast as ops can paste.

### Shadow mode (highly recommended before flipping the flag)

Before `RLS_STRICT_MODE=true` in production:

- Add a Postgres `log_min_messages = NOTICE` rule + a custom log line
  in `_set_session_org_id` that emits when the session var is empty
  AND a tenant table is about to be touched (we can't easily detect
  the second condition without query inspection — easier to log every
  empty-context DB call and grep ops dashboards for unexpected
  callers). 24-48h of shadow-mode logs across staging + prod tells us
  whether any production code path still relies on the escape hatch.
- The `audit_shadow_block` pattern from §audience-filter
  (`AUDIENCE_FILTER_ENABLED`) is the precedent. Same shape.

---

## 7. Verification (for the doc reader)

You should be able to answer YES to all of these after reading:

- [ ] Why does Phase 1's `IS NULL OR = ''` escape hatch exist?
  → §1: Alembic, direct-factory call sites, and unauthenticated
  request paths all run with no session var.
- [ ] How many concrete code locations would break under strict RLS?
  → §2.E lists 5 explicit break sites + 1 conditional (onboarding
  preview) = **6 break sites across 9 audited categories**.
- [ ] Which option is recommended and why?
  → Option B (`app_admin` BYPASSRLS role + `tenant_session` helper).
  Pros: standard Postgres mechanism, observable, forces deliberate
  decision at connection level.
- [ ] What's the fastest rollback?
  → §6.1 — `RLS_STRICT_MODE=false` + pod restart, ~30s RTO.
- [ ] What does the implementation PR have to land?
  → Migration `0027` (§4 SQL), `tenant_session` + `admin_session`
  helpers (§3 code sketch), audit middleware fix, A2A bridge fix,
  approvals/events WS initial-batch fix, reap-stale fix, test plan
  (§5), `RLS_STRICT_MODE` env var (§6.1).

---

## 8. Open audit gaps (things I couldn't verify from inside the repo)

- **Alembic role in production**: I don't know which Postgres role
  the production `DATABASE_URL` connects as. If it's the application
  role (`autoswarm_app`), data-backfilling migrations break under
  Phase 1.5. Need to verify with ops + add to the runbook: "Alembic
  must run as a `BYPASSRLS` role".
- **Onboarding voice-mode preview**: §2.C lists this as
  `needs verification`. Spent 10 min looking, didn't pin down whether
  the preview endpoint reads `tenant_configs` and whether it has an
  auth dep. Resolve before the implementation PR.
- **Cloudflare / external tenant-id lookups**: The `tenant_identities`
  table is excluded from RLS by design. If any code path leaks
  `tenant_identities` data into a tenant-scoped response, that's a
  separate audit (not covered here).
- **Future Celery tasks**: Today none touch tenant Postgres tables.
  When that changes (e.g. PMF widget aggregation jobs), each new
  Celery task is a potential break site. Add to RFC 0013 review
  checklist.
- **Direct DB access from ops scripts** (`scripts/backup-postgres.sh`,
  `scripts/restore-postgres.sh`): these run `pg_dump` / `pg_restore`
  which connect as a superuser by convention. RLS doesn't apply.
  Verified for backup; restore happens by superuser too. Not a break
  site.
- **Per-row `pg_stat_user_tables` impact**: FORCE RLS adds a small
  per-query planner cost. Not measured. Should benchmark in the
  implementation PR's perf section.

---

## 9. References

- Migration that introduced the escape hatch:
  `apps/nexus-api/alembic/versions/0025_enable_rls_tenant_tables.py`
- Session-var setter:
  `apps/nexus-api/nexus_api/database.py:53-84` (`_set_session_org_id`)
- Auth-side ContextVar binding:
  `apps/nexus-api/nexus_api/auth.py:130-178` (`get_current_user`)
- Middleware that initialises the ContextVar default:
  `apps/nexus-api/nexus_api/middleware/security.py:14,17-32`
- Existing contract tests:
  `apps/nexus-api/tests/test_rls_session_org_id.py`,
  `apps/nexus-api/tests/test_rls_isolation.py`
- Postgres docs: row security policies, `BYPASSRLS`, `FORCE ROW LEVEL SECURITY`
  (`https://www.postgresql.org/docs/current/ddl-rowsecurity.html`)
