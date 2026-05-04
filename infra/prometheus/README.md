# Selva Office — Prometheus + Grafana SLO config

Recording rules, alerting rules, and a Grafana dashboard that
operationalize the SLO definitions in
[`docs/SLOS.md`](../../docs/SLOS.md).

This directory ships **READY** config — it does not run on its own.
The OTel exporter (Phase 2 item 11 in `ROADMAP.md`) and a Prometheus +
Grafana backend must be wired before anything here produces a signal.
A vendor decision is pending operator review.

---

## File map

| File | Purpose |
|---|---|
| [`recording-rules.yml`](recording-rules.yml) | Pre-computed SLIs (latency p50/p95/p99, error rates over 5m/30m/1h/2h/6h/1d/3d, 30d availability, task SLIs). 14 recording rules. |
| [`alerting-rules.yml`](alerting-rules.yml) | Multi-window multi-burn-rate alerts per SLOS.md §5 (Tier 1 fast/slow page, Tier 2 fast/slow notify) + task-level alerts (DLQ depth, approval-queue p95, task success rate). 7 alerts. |
| [`../grafana/dashboards/selva-slos.json`](../grafana/dashboards/selva-slos.json) | Grafana dashboard. 10 panels across 3 tier rows + availability burn-down + task-level SLI row. Importable via the Grafana UI's "Import dashboard" with a `${DS_PROMETHEUS}` datasource variable. |

---

## How these plug into a Prometheus + Grafana stack

```
                ┌─────────────────────────┐
                │  Selva services emit    │
 OTel SDK ───>  │  metrics on /metrics    │
                │  (FastAPI / Colyseus)   │
                └────────────┬────────────┘
                             │ scrape
                             ▼
                ┌─────────────────────────┐
                │  Prometheus             │
                │   - recording-rules.yml │
                │   - alerting-rules.yml  │
                └────────────┬────────────┘
                             │ /api/v1/query
                             ▼
                ┌─────────────────────────┐
                │  Grafana                │
                │   - selva-slos.json     │
                └─────────────────────────┘
                             │
                             ▼
              Alertmanager → PagerDuty (page) / Slack #ops (notify)
```

### Wiring steps (operator)

1. **Vendor decision lands** — pick a managed Prometheus (Grafana Cloud,
   Chronosphere, AWS Managed Prometheus) OR a self-hosted stack. Wire
   `OTEL_EXPORTER_OTLP_ENDPOINT` env var on every Selva service.
2. **Add these rule files to `prometheus.yml`**:
   ```yaml
   rule_files:
     - /etc/prometheus/recording-rules.yml
     - /etc/prometheus/alerting-rules.yml
   ```
   Mount the files via ConfigMap (K8s) or volume bind (Docker).
3. **Add the `tier` label via relabeling** — the OTel SDK emits
   `http_route` and `http_status_code` natively. The `tier` label is
   computed from the route prefix. Example `metric_relabel_configs`:
   ```yaml
   - source_labels: [http_route]
     regex: "/api/v1/(swarms/dispatch|auth/.*|onboarding/.*|approvals/.*|chat/messages|stripe/webhook|events/ws|approvals/ws)"
     target_label: tier
     replacement: "1"
   - source_labels: [http_route]
     regex: "/api/v1/(marketplace/.*|calendar/.*|maps/.*|workflows/.*|voice/.*|billing/.*|gateway/.*|swarms/tasks/.*)"
     target_label: tier
     replacement: "2"
   - source_labels: [http_route]
     regex: "/api/v1/(agents/.*|health/.*|metrics/.*|events)"
     target_label: tier
     replacement: "3"
   ```
   Keep this in sync with [`docs/SLOS.md`](../../docs/SLOS.md) §4. New
   route → update SLOS.md AND the relabel rules.
4. **Import the Grafana dashboard** via UI: Dashboards → Import → upload
   `infra/grafana/dashboards/selva-slos.json` → select your Prometheus
   datasource at the `DS_PROMETHEUS` variable prompt.
5. **Wire Alertmanager** — `severity=page` routes to PagerDuty,
   `severity=notify` routes to Slack `#ops`. Example route:
   ```yaml
   route:
     receiver: ops-slack
     routes:
       - matchers: [severity = page]
         receiver: pagerduty
   ```

---

## Expected metric labels (OTel semantic conventions)

The recording rules expect the following labels to be present on the
source metrics. These are emitted by default by
`opentelemetry-instrumentation-fastapi` and the Prometheus exporter
when configured for OTel HTTP semantic conventions:

| Label | Source | Example |
|---|---|---|
| `service` | `OTEL_SERVICE_NAME` env or `Resource.SERVICE_NAME` | `nexus-api` |
| `http_route` | `http.route` semantic attribute (route template, NOT URL) | `/api/v1/swarms/dispatch` |
| `http_method` | `http.request.method` | `POST` |
| `http_status_code` | `http.response.status_code` | `500` |
| `tier` | Added via relabel rule (see step 3 above) | `1` / `2` / `3` |

Source metric names expected:

- `http_server_duration_milliseconds_bucket` (latency histogram)
- `http_server_requests_total` (request counter)
- `selva_task_completed_total{graph_type, org_id}` (worker-emitted)
- `selva_task_failed_total{graph_type, org_id}` (worker-emitted)
- `selva_dlq_depth` (gauge — already exposed via `/api/v1/health/dlq-stats`; expose as Prom metric)
- `selva_approval_pending_age_seconds_bucket` (histogram — to be added in approvals router)

The `selva_*` task-level metrics need to be added by the OTel exporter
wave alongside the standard HTTP metrics. They derive directly from
the existing `TaskEvent` stream (see CLAUDE.md "Full-Stack Observability").

---

## What needs to land BEFORE these are useful

1. **PR #137** — W3C trace-context propagation across services
   (already merged 2026-05-04). Recording rules depend on consistent
   `service` labels which the propagation work standardizes.
2. **Phase 2 item 11 — OTel exporter wired** — `OTEL_EXPORTER_OTLP_ENDPOINT`
   currently no-ops when unset. Until set, no metrics flow. **Vendor
   decision pending.**
3. **OTel HTTP-server instrumentation enabled** in nexus-api,
   colyseus, gateway, workers — usually a 2-line install via
   `opentelemetry-instrumentation-fastapi.instrument_app(app)`.
4. **`tier` relabel rule added** — see step 3 in the wiring section.
5. **`selva_task_*` metrics emitted** by workers via the OTel
   Prometheus exporter (or a sidecar that converts `TaskEvent` rows
   to a metric — both are valid).

Until all five land, the recording rules will produce empty time
series and the alerts will never fire (which is the correct safe
default — no false pages on missing data).

---

## How to add a new endpoint to the SLO set

1. **Update [`docs/SLOS.md`](../../docs/SLOS.md) §4** — add the
   endpoint row with its tier classification and SLI definition.
2. **Update the `tier` relabel rule** in your Prometheus config
   (step 3 in wiring) — make sure the new route's regex matches the
   correct tier replacement.
3. **No changes needed to the recording or alerting rules** — they
   are tier-driven, not route-driven. The dashboard's `service`
   template variable picks up the new endpoint automatically the
   moment the OTel exporter starts seeing traffic for it.
4. **PR review checklist** — the SLOS.md §9 adoption checklist also
   requires the PR author to confirm tier classification + SLI row
   are present before merge.

---

## Validation

`promtool` was not installed in the dev environment when this PR
was authored, so syntactic validation is recommended on the operator
side before deploy:

```bash
# Validate rule files
promtool check rules infra/prometheus/recording-rules.yml
promtool check rules infra/prometheus/alerting-rules.yml

# Test alerts against historical data (once Prometheus has scrape data)
promtool test rules tests/prometheus/*.yml
```

The Grafana dashboard JSON was validated as syntactically correct
JSON; visual sanity-check happens on first import.

---

## SLO review cadence

Per [`docs/SLOS.md`](../../docs/SLOS.md) §7: quarterly review every
90 days. Outcomes documented in `docs/SLO_REVIEW_QYYYY.md`. Tune
recording-rule windows, alert thresholds, and dashboard panels there.
