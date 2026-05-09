---
name: staging-refresh
description: Refresh the staging database from prod with PII masked. Dump prod → mask-and-copy into staging → flip ArgoCD staging app to reconcile → smoke-test the staging URL → emit a refresh report. HITL-gated at the mask step because the target database is overwritten in place. Per the PhyndCRM PP.5 staging spec.
audience: platform
allowed_tools:
  - db_dump_to_r2
  - db_restore_from_r2
  - db_mask_and_copy
  - db_size_report
  - argocd_get_app
  - argocd_sync_app
  - argocd_refresh_app
  - k8s_get_pods
  - k8s_rollout_status
  - http_request
  - save_artifact
metadata:
  category: data-lifecycle
  complexity: high
  reversibility_cost: medium
---

# Staging Refresh Skill

Keeps staging useful. Staging drifts from prod in data shape over the
course of a sprint — columns added, row distributions skewed, new
tenants — and once the drift gets large enough, staging stops being a
credible dress rehearsal for prod. This skill refreshes staging from
prod on demand, with PII masked so the refresh doesn't widen the blast
radius of a staging compromise.

## Invariants

- **Target db is overwritten.** `db_mask_and_copy` restores the source
  dump over the target. The skill MUST HITL-gate this step — no silent
  auto-execution. `reversibility_cost: medium` because the target's
  pre-refresh state is itself a dump in R2 (step 2 below), so recovery
  is possible but costly.
- **Mask every PII column on every refresh.** Even if a column didn't
  previously contain PII, it might now. The `table_mask_rules` mapping
  is the source of truth — update it when a migration adds a new
  PII-bearing column, not when you remember to.
- **No live secrets in staging.** The refresh does not copy secret
  material. OAuth client secrets, Stripe keys, Resend keys, etc.
  remain environment-specific — staging has its own Secret objects per
  `docs/PP_4_STAGING_AUDIT.md`.
- **One tenant, or all.** The skill refreshes a whole database, not a
  tenant subset. Tenant-scoped refresh is a future skill (would need
  tenant_id-scoped DELETE + INSERT, not pg_dump/restore).

## PII mask rule set — the canonical map

This is the set every refresh applies. Extend here when a migration
adds a PII-bearing column.

```python
TABLE_MASK_RULES = {
    # PhyndCRM
    "contacts": ["email", "phone", "whatsapp_number"],
    "leads": ["contact_email", "contact_phone"],
    # Janua
    "users": ["email", "display_name", "phone_number"],
    "guest_invites": ["email", "typed_name"],
    # Dhanam
    "tenants": ["billing_email", "contact_email"],
    "customers": ["email", "shipping_address", "billing_address"],
    # Karafiel
    "sat_certs": ["password_hash"],
    # AutoSwarm Office
    "tenant_configs": ["contact_email"],
    "consent_ledger": ["signer_ip", "signer_user_agent", "user_email"],
}
```

(Mask rules hash columns deterministically via SHA256, so referential
integrity is preserved across tables that share an email/id key.)

## Runbook — 6-step refresh flow

### 1. Pre-flight — state before touching anything

- `db_size_report(database=<prod_db>)` — snapshot row counts + bytes per
  table. Logged in the report.
- `db_size_report(database=<staging_db>)` — snapshot the about-to-be-
  overwritten staging size. Logged for comparison.
- `argocd_get_app(name=<staging_app>)` — confirm the staging ArgoCD app
  is in a clean Synced state. A degraded staging app means the cluster
  isn't ready to receive a refresh; abort.

### 2. Dump prod to R2 (safety snapshot)

```python
await db_dump_to_r2(
    database=<prod_db>,
    bucket="madfam-db-backups",
    key_prefix=f"staging-refresh/{today}",
)
```

This dump is both the source for the restore AND the escape hatch if the
mask-and-copy corrupts staging. Retain for 30 days per backup policy.

### 3. **HITL GATE** — confirm before overwriting staging

Present:
- Source DB + row count + bytes.
- Target DB + row count + bytes (the state being overwritten).
- List of tables-to-be-masked and columns-per-table.
- Staging ArgoCD app name.

Pause for ASK-level approval. Proceed on APPROVE; record + emit report on
DENY.

### 4. Mask-and-copy

```python
await db_mask_and_copy(
    source_db=<prod_db>,
    target_db=<staging_db>,
    table_mask_rules=TABLE_MASK_RULES,
)
```

Time budget: 15–45 minutes depending on DB size. Surface the log tail
from the response's `data.log_tail` for sanity.

Post-refresh: `db_size_report(database=<staging_db>)` — row counts should
match source within a small delta (mask only changes column values, not
row counts).

### 5. Reconcile staging app

- `argocd_refresh_app(name=<staging_app>, type="hard")` — re-evaluate
  manifests against cluster state after the DB refresh.
- `argocd_sync_app(name=<staging_app>)` — roll the apps so they re-read
  any new rows (caches, Redis indices, etc.).
- `k8s_rollout_status` on each deployment owned by the app — wait for
  Ready.

### 6. Smoke test + report

- HTTP GET the staging URL's health endpoint (via the existing
  `http_request` tool). Expect 200 + `status: "healthy"`.
- Write the refresh record to the artifact store:
  `save_artifact(key=f"staging-refreshes/{today}.yaml", ...)`.

## Output format — the refresh report

```yaml
refresh_id: <timestamp-short-uuid>
started_at: <iso8601>
completed_at: <iso8601>
duration_minutes: <int>
source:
  database: <name>
  rows_total: <int>
  bytes_total: <int>
target:
  database: <name>
  rows_before: <int>
  bytes_before: <int>
  rows_after: <int>
  bytes_after: <int>
dump_r2_object: s3://<bucket>/<key>
mask:
  tables: [<list>]
  columns_total: <int>
argocd:
  app: <name>
  pre_sync_status: <Synced|OutOfSync>
  post_sync_status: <Synced|OutOfSync>
smoke_test:
  url: <staging URL>
  status_code: <int>
  response_preview: <short>
hitl:
  gated: true
  approver: <sub>
  approved_at: <iso8601>
follow_ups:
  - <anything unexpected observed>
```

## Known pitfalls

- **Connection count mismatch.** If the staging app is running when the
  DROP-and-recreate inside mask-and-copy fires, psql reports `other
  session is connected`. Scale the staging app to 0 before step 4:
  `argocd_sync_app(name, dry_run=false)` after patching the HPA
  minReplicas — or pause the ArgoCD app entirely. Restore after step 5.
- **Migration drift.** If staging has migrations prod doesn't yet (or
  vice versa), the mask step's UPDATEs may target columns that don't
  exist. Always run the refresh AFTER merging any pending migrations
  to both environments.
- **Referential integrity inside masked columns.** SHA256 is
  deterministic, so `contacts.email = "a@b.com"` and
  `leads.contact_email = "a@b.com"` hash to the same value post-mask.
  If you add a new PII column that references an un-masked id, review
  the impact on joins.
- **Long-running dumps time out.** The 1800s timeout on
  `db_dump_to_r2` is usually enough for the PhyndCRM-sized DBs
  (<5 GB) but will not be for fortuna's embedding store. For those
  databases, pre-partition by schema and dump separately.
