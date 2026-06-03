# AUDIENCE_FILTER_ENABLED — Shadow → Enforce Rollout Plan

> Status: **enforced in production** (configmap flip); shadow procedure below for new envs
> Owner: ops / platform
> Last Updated: 2026-05-30
> Related: ROADMAP.md Phase 2 ("AUDIENCE_FILTER_ENABLED=true"), CLAUDE.md
> "Tool + Skill Audience Split (admin vs tenant)",
> [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
> (provides the log backend the queries below assume)

## TL;DR

The two-tier audience model (`Audience.PLATFORM` vs `Audience.TENANT`) ships
in **shadow mode** by default. Three enforcement points — tool execute, skill
activate, dispatch endpoint — emit a structured `audience_shadow_block` log
line WITHOUT raising or returning 403. After observing zero shadow-block
events over 48h of meaningful production traffic, flip
`AUDIENCE_FILTER_ENABLED=true` on workers AND nexus-api in the same release.

**Selva is pre-launch. There is no real production tenant traffic yet.** This
doc documents the procedure for when there is. Until then, run the synthetic
exercise in Section 5 and confirm the shadow log stays empty.

## Production status (2026-05-30)

Production (`infra/k8s/production/configmap.yaml`) sets
`AUDIENCE_FILTER_ENABLED=true`. The three enforcement points (tool execute,
skill activate, dispatch endpoint) **raise/403 in prod**. Code default remains
off for local dev and new environments until explicitly flipped.

For new staging or greenfield deployments, follow the shadow → enforce
procedure in Sections 1–5 below before setting the env var.

## Section 1 — What "shadow" means today

### 1.1 The three enforcement points

All three read the same env var
(`packages/permissions/selva_permissions/audience.py:AUDIENCE_FILTER_ENABLED_ENV`)
and switch between raise/return-403 (enforce) and log-and-allow (shadow).

| Enforcement point | File:line | What it gates |
|---|---|---|
| **Tool execute** (belt-and-braces, runs after the spec-time filter) | `packages/tools/src/selva_tools/audience.py:100` (`enforce_audience()`) | Every `BaseTool.execute()` call. Auto-wrapped by `BaseTool.__init_subclass__`. Catches the case where a platform tool somehow makes it past the spec-time filter (`get_specs(audience=...)`). |
| **Skill activate** | `packages/skills/selva_skills/registry.py:52` (`_audience_violation()`) | Every `SkillRegistry.activate(name, audience=...)` call. |
| **Dispatch endpoint** | `apps/nexus-api/nexus_api/routers/swarms.py:223` | `POST /api/v1/swarms/dispatch` — when a tenant caller names a platform skill in `required_skills`. |

The spec-time filter (`ToolRegistry.get_specs(audience=...)` strips
PLATFORM-tagged tools when audience is tenant) runs unconditionally and is
not affected by the feature flag — the LLM literally never sees platform
tools when audience is tenant. The three enforcement points above are
defense-in-depth against:

- A tool invoked via a non-standard path that bypassed `get_specs()`.
- A skill loaded by name without the spec filter being applied first.
- A dispatch caller naming the skill explicitly in `required_skills`
  (reaches the endpoint before the worker context binds).

### 1.2 The exact log lines emitted

All three log lines start with the literal string `audience_shadow_block` so
they are grep/LogQL-friendly. They are emitted via the standard Python
`logging.warning(...)` call and pass through structlog's JSON formatter to
stdout, where Promtail / Grafana Agent ships them to Loki (per
[docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)).

**Tool execute**
(`packages/tools/src/selva_tools/audience.py:123-129`):
```
audience_shadow_block tool=<tool_name> required=<platform|tenant> swarm=<platform|tenant|unbound> (permitting — AUDIENCE_FILTER_ENABLED off)
```

**Skill activate**
(`packages/skills/selva_skills/registry.py:61-67`):
```
audience_shadow_block skill=<skill_name> required=<platform|tenant> swarm=<platform|tenant> (permitting — AUDIENCE_FILTER_ENABLED off)
```

**Dispatch endpoint**
(`apps/nexus-api/nexus_api/routers/swarms.py:223-229`):
```
audience_shadow_block caller_org=<org_id> caller_audience=<platform|tenant> forbidden_skills=<list> (permitting — AUDIENCE_FILTER_ENABLED off)
```

### 1.3 What information each log carries

| Field | Tool | Skill | Dispatch |
|---|---|---|---|
| `tool` / `skill` / `forbidden_skills` | name (str) | name (str) | list of skill names |
| `required` / `caller_audience` | required audience for the tool | required audience for the skill | caller's resolved audience |
| `swarm` | current bound audience or `"unbound"` | current bound audience | (in `caller_audience`) |
| `caller_org` | — | — | tenant's `org_id` from JWT |
| Standard structlog context | `request_id`, `task_id`, `agent_id` (if bound) | same | `request_id`, `user_sub` |
| Severity | `WARNING` | `WARNING` | `WARNING` |

Each log line is enough to identify (a) which platform-only resource was
nearly invoked, (b) by whom, and (c) at what enforcement layer the catch
happened. That is exactly the data the on-call needs to triage a real
shadow-block.

## Section 2 — Observation Criteria

### 2.1 How to query the shadow-block logs

Once the log backend from
[docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md)
is wired (Grafana Cloud Loki recommended), the queries below run in
Grafana → Explore → Loki data source.

**LogQL — count of shadow blocks in last 48h, all services**:
```logql
sum by (service_name) (
  count_over_time(
    {cluster="selva-prod"} |= "audience_shadow_block" [48h]
  )
)
```
Acceptance: returns zero for every service.

**LogQL — recent shadow blocks with full payload**:
```logql
{cluster="selva-prod"} |= "audience_shadow_block"
  | json
  | line_format "{{.timestamp}} {{.service_name}} {{.message}}"
```

**LogQL — shadow blocks by enforcement layer**:
```logql
sum by (layer) (
  count_over_time(
    {cluster="selva-prod"} |= "audience_shadow_block"
      | json
      | label_format layer=`{{ if .tool }}tool{{ else if .skill }}skill{{ else }}dispatch{{ end }}`
    [48h]
  )
)
```

**Grafana dashboard panel** (one-time setup): create a "Selva — Audience
Filter Health" dashboard with three panels — total count (24h), per-service
count (24h), and a logs panel filtered to the same query. Add a Grafana
Alerting rule:
- Threshold: `> 0 shadow blocks in any 1h window`.
- Routing: `#alerts-prod-warning` (Slack).

While the gate is in shadow mode, this alert is the early-warning system —
any fire means a tenant tried to do something they shouldn't, OR there's a
legitimate cross-audience use case we haven't accounted for. Either way,
**triage before flipping the flag**.

### 2.2 Acceptance criteria

To call shadow mode "soaked and ready to enforce":

1. **Zero shadow-block log lines over 48h** of continuous production traffic.
   Continuous = the staging or production cluster has had at least one
   tenant request per minute throughout the 48h window. (Empty traffic
   doesn't count as a clean soak — a quiet system can't shadow-block what
   nobody is invoking.)
2. **At least one platform-side request per layer happened during the
   window**, to prove the enforcement code path is live. Easiest way: have
   a MADFAM operator run a smoke that invokes a platform tool, a platform
   skill, and a dispatch with a platform skill — confirm no shadow-block
   fires AND confirm the call succeeded. (Platform audience is allowed; the
   absence of log lines + the success of the call is the positive signal.)
3. **Regression test still passes**:
   ```bash
   uv run pytest packages/tools/tests/test_platform_tool_registry.py
   uv run pytest packages/tools/tests/test_audience.py
   uv run pytest packages/skills/tests/test_skill_audience.py
   uv run pytest apps/nexus-api/tests/test_dispatch_audience_gate.py
   uv run pytest apps/workers/tests/test_audience_integration.py
   ```
   All five must pass on the cutover commit.

### 2.3 What to do if a shadow-block fires

Treat it as a P2 investigation, not an automatic incident:

1. **Pull the offending log line + request_id**.
2. **Trace the request_id through the timeline endpoint**:
   `GET /api/v1/events/tasks/<task_id>/timeline` — see what the swarm was
   trying to do.
3. **Decide which case it is**:
   - **(a) Tenant trying a platform-only thing they shouldn't** — e.g. a
     tenant somehow named `cloudflare_create_zone` in a workflow YAML.
     Confirm the tenant gets a clear UX error, document the case in the
     post-mortem, and proceed with cutover. The shadow block did its job.
   - **(b) Legitimate cross-audience use case we missed** — e.g. a tenant
     swarm needs to call a tool we mistakenly tagged PLATFORM. Re-classify
     the tool: change `_cls.audience = Audience.TENANT` at the bottom of
     the tool's module, **remove** it from
     `packages/tools/tests/test_platform_tool_registry.py:PLATFORM_TOOL_NAMES`
     in the same PR (with a comment in the PR explaining why), and ship.
     Restart the soak window from the deploy timestamp.
   - **(c) Bug in audience resolution** — e.g. `org_id_var` not bound
     correctly so `swarm_audience=unbound` shows up in the log. Investigate
     `selva_permissions.audience.resolve_audience()` and the
     `with_audience()` binding at task dispatch in
     `apps/workers/selva_workers/__main__.py`. Fix, ship, restart soak.

Do NOT flip `AUDIENCE_FILTER_ENABLED=true` until the offending case is
either resolved or accepted as a positive signal.

## Section 3 — Cutover Sequence

### 3.1 Pre-deploy checks

```bash
# 1. Regression tests pass (run on the commit you're about to deploy)
uv run pytest packages/tools/tests/test_platform_tool_registry.py
uv run pytest packages/tools/tests/test_audience.py
uv run pytest packages/skills/tests/test_skill_audience.py
uv run pytest apps/nexus-api/tests/test_dispatch_audience_gate.py
uv run pytest apps/workers/tests/test_audience_integration.py

# 2. Shadow-block log query returns zero for the last 48h
#    (LogQL above; alternatively in your log backend)

# 3. The current staging deploy has the flag flipped first
kubectl -n selva-staging get deploy nexus-api -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="AUDIENCE_FILTER_ENABLED")].value}'
# expected: "true"

# 4. Staging soak — 30 min minimum (per MIN_SOAK_MINUTES) with the flag
#    flipped, no 5xx spike, no audience_mismatch 403s in nexus-api logs
#    (besides the synthetic ones from your test invocations).
```

### 3.2 The flip

The flag must flip on **workers and nexus-api in the same release** because
the three enforcement points span both processes:

- Tool execute: workers (`with_audience()` is bound at task dispatch in
  `selva_workers/__main__.py`).
- Skill activate: workers + nexus-api (both call `SkillRegistry.activate()`).
- Dispatch endpoint: nexus-api only.

If you flip nexus-api first, dispatches with platform skills start 403'ing
while the worker still allows the same skill if it slipped through some
other path — inconsistent. Flip both atomically.

**Kustomize patch** (production overlay):
```yaml
# infra/k8s/overlays/production/nexus-api-patch.yaml
- op: replace
  path: /spec/template/spec/containers/0/env/?(@.name=="AUDIENCE_FILTER_ENABLED")/value
  value: "true"
# infra/k8s/overlays/production/workers-patch.yaml
# (same patch)
```

Or — simpler — just edit the ConfigMap that both Deployments source from:
```yaml
# infra/k8s/overlays/production/configmap.yaml
data:
  AUDIENCE_FILTER_ENABLED: "true"
```
Then bump the rollout annotation to force pod restart for both Deployments.

### 3.3 Post-deploy verification (first 5 min)

```bash
# 1. Check the flag is live in both pods
kubectl -n selva exec deploy/nexus-api -- env | grep AUDIENCE_FILTER_ENABLED
kubectl -n selva exec deploy/workers -- env | grep AUDIENCE_FILTER_ENABLED

# 2. Confirm no 5xx spike on nexus-api
#    Grafana → "nexus-api 5xx rate" panel — should remain at baseline.

# 3. Confirm shadow-block log line stops appearing
#    Run the LogQL query from Section 2.1, time range "Last 5 minutes".
#    Expected: still zero (it was zero before; should remain zero).

# 4. Confirm audience_mismatch 403s WOULD now fire by triggering one
#    intentionally — invoke a platform skill from a tenant test account.
#    Expected: 403 from /api/v1/swarms/dispatch with body
#    {"error": "audience_mismatch", "forbidden_skills": [...], "caller_audience": "tenant"}

# 5. Confirm a legitimate platform-side dispatch still works:
#    Invoke a platform skill from the MADFAM platform org_id.
#    Expected: 202 Accepted; task_id returned; task progresses to running.
```

### 3.4 Rollback procedure

If anything in 3.3 fires unexpectedly:

```bash
# 1. Revert the env var in both Deployments
kubectl -n selva set env deploy/nexus-api AUDIENCE_FILTER_ENABLED=false
kubectl -n selva set env deploy/workers AUDIENCE_FILTER_ENABLED=false

# 2. Force pod restart (env change triggers rolling restart automatically,
#    but for belt-and-braces:)
kubectl -n selva rollout restart deploy/nexus-api deploy/workers

# 3. Confirm rollback
kubectl -n selva exec deploy/nexus-api -- env | grep AUDIENCE_FILTER_ENABLED
# expected: "false"

# 4. Update the configmap in git so next ArgoCD sync doesn't undo the
#    rollback:
#    Edit infra/k8s/overlays/production/configmap.yaml
#    AUDIENCE_FILTER_ENABLED: "false"
#    git commit + push.
```

RTO: under 2 minutes (the env change is a rolling restart, not a rebuild).
This satisfies the <5 min RTO target from CLAUDE.md "Deployment Pipeline →
Rollback".

## Section 4 — What Happens When It's Enforced

### 4.1 User-facing behavior change

Before (shadow):

```
Tenant agent calls platform tool → tool executes normally; log line emitted
Tenant calls /dispatch with platform skill → 202 Accepted; task runs
```

After (enforce):

```
Tenant agent calls platform tool → AudienceMismatch raised in tool execute;
  task fails with status="failed", error_message="tool=<x> requires
  audience=platform, current swarm audience=tenant"; the failure surfaces in
  the dashboard kanban as a red task.
Tenant calls /dispatch with platform skill → 403 Forbidden, body:
  {"error": "audience_mismatch", "message": "Tenant swarms cannot dispatch
   platform-audience skills.", "forbidden_skills": [...],
   "caller_audience": "tenant"}
```

The tenant-facing UX in the office-ui needs a friendly handler for the 403
(it currently surfaces as a generic "Dispatch failed" toast). Tracked
separately — not blocking on the cutover, but should land in the same week
so the error message is helpful instead of cryptic.

### 4.2 CLAUDE.md update

After the cutover, update the "Tool + Skill Audience Split" section in
CLAUDE.md:

- Change "Feature flag + shadow mode" header to "Feature flag (enforced
  since YYYY-MM-DD)".
- Replace the three "shadow → enforce" bullets with a single sentence:
  "AUDIENCE_FILTER_ENABLED is enforced in production. Tenant swarms that
  invoke platform-only tools or skills receive a 403 / AudienceMismatch.
  Shadow mode is preserved as a feature flag — set the env var to false
  in any environment to revert."
- Add a link to this rollout doc as the historical record.

## Section 5 — When This Procedure Is Appropriate

**Selva is pre-launch as of 2026-05-03. There is no real tenant traffic to
observe.** Running this procedure now would be observing zero traffic and
calling it a clean soak — false confidence. Three options:

### 5.1 Synthetic exercise (do this NOW, pre-launch)

Until we have meaningful tenant traffic, run a synthetic exercise that
covers every tool the platform offers. The shadow-block log MUST stay empty
during this exercise.

1. **Spin up a tenant fixture** — a non-platform Janua org_id, a swarm
   under that org, and an agent with the default skillset.
2. **Walk every tenant-audience tool** — there are ~110 TENANT-audience tools
   (240 total minus ~130 PLATFORM, per
   `packages/tools/tests/test_platform_tool_registry.py`). Build a small
   driver that invokes each tool's `execute()` once with mock-safe
   arguments. The vast majority should run; none should emit
   `audience_shadow_block`.
3. **Walk every tenant-audience skill** — 12 of the 17 skills are tenant.
   Activate each via `SkillRegistry.activate(name, audience=Audience.TENANT)`.
   None should raise `SkillAudienceMismatch` or emit shadow-block.
4. **Adversarial smoke** — explicitly try to invoke a platform tool from
   the tenant fixture. The shadow-block line MUST appear (this is the
   positive signal that the gate is wired). After confirming, remove the
   adversarial invocation from the fixture and resume the clean run.

This synthetic walk takes ~30 min to write as a pytest fixture and
re-run on demand. Add it to the cutover checklist as the pre-launch
substitute for "48h of meaningful production traffic".

### 5.2 First-paying-tenant soak (when one exists)

When the first paying tenant onboards, restart this rollout from Section 2.
The 48h soak is meaningful at that point because the tenant's swarm is
exercising real workflows you don't control.

### 5.3 Cohort-based gradual enforcement (Phase 3 territory)

If the shadow-block soak surfaces gray-area cases (Section 2.3 case (b)
that take time to re-classify), consider per-tenant feature flagging:

- Add a per-tenant `audience_filter_enforced` boolean to `tenant_configs`.
- Default true for new tenants; default false for legacy tenants while
  their use cases are reviewed.
- Migrate legacy tenants to enforced one at a time after confirming each is
  clean for 48h.

Defer this to Phase 3 unless the cutover surfaces enough cases to justify
the per-tenant complexity.

## References

- CLAUDE.md "Tool + Skill Audience Split (admin vs tenant)" — the
  end-to-end flow this rollout flips the gate on.
- ROADMAP.md Phase 2 "AUDIENCE_FILTER_ENABLED=true" — the parent task.
- `packages/permissions/selva_permissions/audience.py` —
  `is_audience_enforcement_enabled()` and `resolve_audience()`.
- `packages/tools/src/selva_tools/audience.py` — `enforce_audience()`,
  `with_audience()` context manager.
- `packages/skills/selva_skills/registry.py:_audience_violation` —
  shadow/enforce branch for skills.
- `apps/nexus-api/nexus_api/routers/swarms.py:200-229` — dispatch
  endpoint shadow/enforce branch.
- `packages/tools/tests/test_platform_tool_registry.py` — regression test
  pinning the platform tool inventory.
- [docs/OBSERVABILITY_VENDOR_SELECTION.md](OBSERVABILITY_VENDOR_SELECTION.md) —
  log backend selection (provides the LogQL the queries above assume).
