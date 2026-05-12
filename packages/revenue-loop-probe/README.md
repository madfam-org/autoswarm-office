# madfam-revenue-loop-probe

Synthetic end-to-end probe for the MADFAM autonomous revenue flywheel.

Every hour, this probe exercises the full money-in path:

```
PhyndCRM lead -> Nexus drafter (LLM) -> email send -> Stripe webhook ->
Dhanam billing event -> PhyndCRM attribution
```

If any stage breaks, the probe exits non-zero with a JSON report that
names the broken stage and why. That gives us a single, definitive signal
for "is the revenue loop working end-to-end."

## Why this matters

Per `memory/project_autonomous_loop_status.md`, the revenue loop is the
flywheel. It's easy to have:

- A green dashboard (no alerts firing)
- Healthy pods
- Zero paying customers

...because a *single* link in the chain quietly broke. The probe's job is
to make that unacceptable. If it fails, somebody is paged.

## Stages

| # | Name                  | What it checks                                                       |
|---|-----------------------|-----------------------------------------------------------------------|
| 1 | `crm.hot_lead`        | PhyndCRM accepts a synthetic hot lead                                |
| 2 | `drafter.first_touch` | Nexus returns a non-empty draft (not the `[LLM unavailable]` sentinel) |
| 3 | `email.send`          | Send pipeline returns intact (list-unsubscribe, sanitized HTML, sender lockdown) |
| 4 | `stripe.webhook`      | Dhanam accepts a signed MXN `payment_intent.succeeded`               |
| 5 | `dhanam.billing_event`| Dhanam's ledger records the event within 30s                         |
| 6 | `phynd.attribution`   | PhyndCRM credits the source agent within 20s                         |

Stages run in order. A failing stage does not stop subsequent stages by
default (we want to know what's broken, not just the first thing). Pass
`--short-circuit` to stop on first failure.

## Safety

- **Dry-run is the default.** Real side effects require `--live`, which
  additionally requires a typed `LIVE` confirmation on stdin. The cron
  deployment runs in dry-run only.
- **Skipped beats failed.** When a required env var is missing, the stage
  returns `skipped`, not `failed` — a partially-deployed environment
  shouldn't page. Only missing mid-chain signals (e.g. prior stage wrote
  no `lead_id`) cause skips; direct endpoint failures are `failed`.
- **Idempotent lead.** The CRM step uses a probe-scoped tenant + correlation
  id, so the ecosystem must expose idempotent probe endpoints. See the
  contract spec in each stage's source file.

## Endpoints each ecosystem service must expose

| Service    | Endpoint                                               | Purpose                               |
|------------|--------------------------------------------------------|---------------------------------------|
| PhyndCRM   | `POST /v1/probe/leads`                                 | Upsert synthetic hot lead (idempotent)|
| PhyndCRM   | `GET /v1/probe/attribution?lead_id=&billing_id=`       | Has credit been written?              |
| Nexus API  | `POST /api/v1/probe/draft`                             | Draft with dry-run flag               |
| Nexus API  | `POST /api/v1/probe/email/send`                        | Run send pipeline (dry-run respected) |
| Dhanam     | `POST /v1/billing/webhooks/stripe`                     | Standard Stripe webhook target        |
| Dhanam     | `GET /v1/probe/billing-events/{stripe_event_id}`       | Ledger lookup by source event         |

All probe endpoints use bearer tokens scoped `probe` and reject requests
without `X-Probe-Correlation-Id`. They are safe to expose publicly because:

1. Every probe endpoint is rate-limited.
2. All writes accept `dry_run: true`; live writes require an additional
   `MADFAM_PROBE_ALLOW_LIVE=true` env on the server.
3. Probe leads and billing events are tagged and excluded from real
   analytics, customer metrics, and human views.

## Usage

### Ad-hoc from a shell

```bash
pip install -e packages/revenue-loop-probe

# Populate env (see packages/revenue-loop-probe/.env.example)
export PHYND_CRM_API_URL=https://crm.madfam.io
export PHYND_CRM_PROBE_TOKEN=...
# ... etc ...

revenue-loop-probe                # dry-run, all stages
revenue-loop-probe --stages crm.hot_lead,drafter.first_touch
revenue-loop-probe --live         # requires typed LIVE confirmation
```

### In production (K8s)

```bash
kubectl create secret generic revenue-loop-probe-tokens -n autoswarm \
  --from-literal=PHYND_CRM_PROBE_TOKEN=... \
  --from-literal=NEXUS_PROBE_TOKEN=... \
  --from-literal=DHANAM_STRIPE_WEBHOOK_SECRET=... \
  --from-literal=DHANAM_PROBE_TOKEN=...

kubectl apply -f packages/revenue-loop-probe/k8s/revenue-loop-probe-cronjob.yaml
```

Runs at `:07` past every hour. A failed CronJob (exit 1) should be routed
to PagerDuty via Alertmanager's `KubeJobFailed` rule.

## Report shape

```json
{
  "correlation_id": "probe-a1b2c3d4e5f6",
  "dry_run": true,
  "started_at": 1713322022.11,
  "finished_at": 1713322027.82,
  "duration_ms": 5710.0,
  "ok": true,
  "fail_count": 0,
  "stages": [
    { "name": "crm.hot_lead", "status": "passed", "duration_ms": 124.3, "facts": {...} },
    { "name": "drafter.first_touch", "status": "passed", ... },
    ...
  ]
}
```

## Tests

```bash
cd packages/revenue-loop-probe
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Covers orchestration: ordering, short-circuit, fail-forward, raising steps,
state threading, JSON serialisation. Individual stages are smoke-testable
against local mocks via the env-var contract.
