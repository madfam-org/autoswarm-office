# Secret rotation policy

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


> Phase 3 item 15 in the [full-remediation plan](../ROADMAP.md). Defines
> rotation cadence + procedure for the production-validator-protected
> secrets that gate Selva's tenant isolation, consent ledger integrity,
> and worker→API auth.

---

## 1. What's in scope

This policy covers the **3 Selva-owned secrets** with production
validators in `apps/nexus-api/nexus_api/config.py`:

| Secret | Env var | Used by | Rotation script target |
|---|---|---|---|
| Worker API token | `WORKER_API_TOKEN` | nexus-api ↔ worker auth, gateway → nexus-api | `worker-api-token` |
| Consent ledger HMAC key | `CONSENT_LEDGER_SIGNING_SECRET` | Signing every `consent_ledger` row (migration 0018) | `consent-ledger-signing` |
| Colyseus service token | `COLYSEUS_SERVICE_TOKEN` | nexus-api ↔ Colyseus chat persistence | `colyseus-service` |

Each has a `Settings._validate_*` validator that refuses the dev
default in `ENVIRONMENT=production`, but those validators only catch
"I forgot to set this" — they don't catch "I set this 12 months ago
and never rotated."

### What's NOT in scope (handled by their respective vendors)

- **Stripe API keys** — rotate via Stripe Dashboard
- **Resend API key** — rotate via Resend Dashboard
- **Anthropic / OpenAI / DeepInfra API keys** — rotate via vendor consoles
- **PostgreSQL passwords** — rotate via Enclii Switchyard / your cloud's RDBMS console
- **Janua JWT signing keys** — rotate via the Janua repo's own key-rotation procedure
- **GitHub PAT (`GITHUB_TOKEN`)** — rotate via GitHub
- **Cloudflare tunnel tokens** — rotate via Cloudflare Zero Trust dashboard

If any of those are compromised, follow the vendor's procedure AND
rotate them in `autoswarm-secrets` so the K8s pods see the new values.

---

## 2. Cadence

| Event | Action | Window |
|---|---|---|
| **Quarterly (Q1, Q2, Q3, Q4)** | Rotate all 3 secrets | First Tuesday of the quarter, 14:00 MX |
| **Suspected compromise** | Immediate rotation of affected secret | Within 1 hour of detection |
| **Operator departure** | Rotate everything they had read access to | Within 24 hours of offboarding |
| **Major version change to consent ledger schema** | Rotate `CONSENT_LEDGER_SIGNING_SECRET` as part of the migration | In the same maintenance window |

Quarterly is a balance: too frequent generates change-management noise + risks
operator fatigue (where rotation gets skipped). Too infrequent leaves stale
secrets vulnerable to slow-leak compromise (a credential exfil that hasn't
been weaponized yet). Quarterly gives 4 forced touches per year, matches
SOC 2 audit common practice (90-day key rotation), and aligns with the
quarterly SLO review (`docs/SLOS.md` §7).

---

## 3. Procedure (per-secret)

The `scripts/rotate-secret.sh` tool does the rotation atomically:

```bash
# Single-secret rotation (recommended for routine quarterly cycle)
./scripts/rotate-secret.sh worker-api-token --namespace=autoswarm

# All three at once (use only on operator departure / suspected compromise)
./scripts/rotate-secret.sh --all --namespace=autoswarm

# Dry-run first to see what it'll do without touching anything
./scripts/rotate-secret.sh worker-api-token --dry-run
```

The script will:
1. Read the current secret value (for audit fingerprint logging — first/last
   4 chars only, never the full value)
2. Generate a new 32-byte hex value (`openssl rand -hex 32`)
3. Patch the K8s `autoswarm-secrets` Secret with the new value
4. Rolling-restart every Deployment that env-references the secret
5. Wait for each Deployment's rollout to complete (5min timeout per Deployment)
6. Verify by `kubectl exec`-ing into one pod per Deployment and confirming
   the new value is in env

If verification fails, the script exits non-zero with a clear error — operator
follows the rollback procedure in §5.

### Rotation order when rotating all three

1. `colyseus-service` first (smallest blast radius — only chat persistence)
2. `worker-api-token` second (worker→API auth — most active path, but
   K8s rolling restart keeps ≥1 pod serving)
3. `consent-ledger-signing` last (signing key for new ledger rows). The
   rotation script first calls
   `POST /api/v1/admin/consent-ledger/promote-key` to register the new
   key value in the per-period registry (migration 0030), THEN patches
   the K8s Secret. Old rows stay verifiable forever because each row
   carries a `signing_key_version` and the verifier looks up the key
   by version. Requires `NEXUS_API_URL` and `NEXUS_ADMIN_TOKEN` env
   vars to be set; without them the script falls back to env-only
   patching with a loud warning (operator must call the promote
   endpoint by hand afterwards).

---

## 4. Pre-rotation checklist

Before running the script, the operator MUST:

- [ ] Confirm `kubectl` is pointing at the right cluster + namespace
      (`kubectl config current-context` and `kubectl config view --minify`)
- [ ] Verify cluster health: `kubectl get pods -n autoswarm` — all pods in
      `Running` state, no recent restarts
- [ ] Check there are no in-flight long-running tasks that depend on the
      old secret. For `WORKER_API_TOKEN` specifically: a worker mid-task
      will retry the API call once on its existing connection; rolling
      restart is graceful so this is rare but possible. Check
      `GET /api/v1/health/queue-stats` for backlog before rotating.
- [ ] Snapshot the current K8s Secret for emergency rollback:

      ```bash
      kubectl -n autoswarm get secret autoswarm-secrets -o yaml > \
        /tmp/autoswarm-secrets-pre-rotation-$(date +%Y%m%d-%H%M%S).yaml
      chmod 600 /tmp/autoswarm-secrets-pre-rotation-*.yaml
      ```

      Delete this file within 7 days.

- [ ] Open the rotation runbook in a browser tab (this doc) for the
      verification + rollback steps.

---

## 5. Rollback

If rotation completes but downstream errors spike (5xx rate up, queue
depth growing, workers can't authenticate):

1. **Don't panic** — the new secret is valid; the symptom is most likely
   that one of the secret-consuming services is using a **cached** copy
   of the old value (e.g., a singleton Settings instance that was loaded
   at process start and never re-read).

2. **Check pod restart status**:

   ```bash
   kubectl -n autoswarm get pods -l app.kubernetes.io/name=autoswarm-workers \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.startTime}{"\n"}{end}'
   ```

   Pod startTime should be AFTER the rotation timestamp. If any pod has
   an older startTime, that's the stale pod — `kubectl delete pod <name>`
   to force re-create.

3. **If still broken after all pods are confirmed-restarted**, restore the
   old secret value:

   ```bash
   kubectl apply -f /tmp/autoswarm-secrets-pre-rotation-<timestamp>.yaml
   for dep in autoswarm-nexus-api autoswarm-workers autoswarm-gateway autoswarm-colyseus; do
     kubectl -n autoswarm rollout restart "deployment/$dep"
   done
   ```

4. **File an incident report** with:
   - The rotation start timestamp
   - The script's exit code + stderr
   - Which pods showed errors
   - When the old value was restored
   - Why the new value didn't work (caching, env var typo, etc.)

---

## 6. Consent ledger key rotation (per-period tracking)

Rotating `CONSENT_LEDGER_SIGNING_SECRET` is now safe: per-period key
tracking lives in `consent_ledger_signing_keys` (migration 0030).
Every `consent_ledger` row carries a `signing_key_version` FK to
that table; the verifier looks up the key value by version and
recomputes the HMAC under it. Pre-0030 rows backfill to version 1
(the bootstrap key, which is the env-level
`CONSENT_LEDGER_SIGNING_SECRET` value at migration time).

The rotation flow:

1. `scripts/rotate-secret.sh consent-ledger-signing` generates a new
   32-byte hex value via `openssl rand -hex 32`.
2. The script calls
   `POST /api/v1/admin/consent-ledger/promote-key` with the new
   value. The endpoint atomically marks the previous current row as
   retired (`is_current=false`, `retired_at=NOW()`) and inserts a new
   row with the next monotonic `key_version` and `is_current=true`.
   A Postgres partial unique index on `is_current=true` enforces
   "exactly one current key" at the DB layer.
3. The script then patches the K8s Secret + rolling-restarts the
   nexus-api Deployment so `_signing_secret()` (the env-level legacy
   path used by offline auditor scripts) also picks up the new value.
4. Old ledger rows continue to verify against their original key
   version forever.

The script aborts BEFORE patching the K8s Secret if the promote-key
call fails. Required env vars: `NEXUS_API_URL` (e.g.
`https://api.selva.town`), `NEXUS_ADMIN_TOKEN` (Bearer token with
`admin` or `platform` role).

Quarterly cycle now safely includes `consent-ledger-signing`.

The audit event `consent_ledger.key_promoted` (event_category
`security`) is emitted to `task_events` on every promotion. Payload
includes `new_key_version`, `previous_key_version`, `actor_sub`, and
`actor_ip` — never the key value itself.

---

## 7. Audit trail

Each rotation logs to stderr (script output, captured by the operator's
shell) AND emits a `secret.rotated` event to the `autoswarm:audit`
Redis stream so:

- The SRE Grafana dashboard reflects rotation history (panel:
  "Secret rotations — last 90d")
- A failed quarterly rotation is visible as a missing event
- Suspected-compromise rotations carry an `incident_ref` annotation
  the operator passes via env var

The event payload includes the secret name, fingerprint of old + new
values (first/last 4 chars masked), the operator's `KUBECTL_USER` (from
the active kubeconfig), and the timestamp. **Never** the full secret
values.

---

## 8. Compliance + contracts

- **SOC 2 CC6.1**: 90-day key rotation cadence is the audit-common standard
- **NIST SP 800-57 Part 1 §5.6**: cryptoperiod ≤ 1 year for HMAC keys; this
  policy's quarterly cadence is well within
- **PCI DSS 3.5.x**: applicable only if Stripe customer data flows through
  Selva (it does not today — Stripe webhooks update tenant_configs but
  card data never leaves Stripe)
- **MX LFPDPPP (Mexican PII)**: consent ledger HMAC is the integrity
  mechanism for the consent record audit trail; rotation procedure must
  preserve verifiability of historical consent rows (see §6)

---

## 9. Related work

- `scripts/rotate-secret.sh` — the rotation tool itself
- `apps/nexus-api/nexus_api/config.py:_validate_*` — production
  validators that gate the dev defaults
- `infra/k8s/production/*.yaml` — Deployment env references that the
  rotation script restarts
- [docs/SLOS.md](SLOS.md) §7 — quarterly review cadence (this policy
  reviews on the same cycle)
