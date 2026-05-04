# selva_observability

Shared logging, Sentry, and OpenTelemetry helpers for AutoSwarm Office.

## Public API

| Helper                         | Purpose                                                          |
|--------------------------------|------------------------------------------------------------------|
| `configure_logging(format)`    | structlog + stdlib logging configuration (JSON or human format). |
| `bind_task_context(...)`       | Attach `task_id`, `agent_id`, etc. to all logs in this context.  |
| `clear_context()`              | Wipe context vars at the end of a request/task.                  |
| `init_sentry(service_name)`    | Wire up Sentry. No-op when `SENTRY_DSN` is unset.                |
| `init_tracing(service_name)`   | Wire up OpenTelemetry SDK + OTLP exporter. No-op when            |
|                                | `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.                          |
| `inject_trace_context(headers)`| Inject W3C `traceparent` into an outbound request's headers.     |
| `extract_trace_context(headers)`| Extract a parent context from incoming request headers.         |

## W3C Trace Context Propagation

Selva propagates the W3C `traceparent` header (and `tracestate` when
present) on every in-Selva HTTP hop so that — once an OTLP exporter is
wired in production — traces correlate end-to-end across:

```
Janua → office-ui → nexus-api → worker → (LLM proxy / Karafiel / Dhanam / …)
```

### Where it's wired

| Layer                          | Direction      | Mechanism                                                         |
|--------------------------------|----------------|-------------------------------------------------------------------|
| `nexus-api`                    | server (in)    | `nexus_api.middleware.tracing.TraceContextMiddleware`             |
| Worker → nexus-api             | client (out)   | `selva_workers.auth.get_worker_auth_headers` (one call site)      |
| Tool-originated outbound HTTP  | client (out)   | `selva_tools.builtins.http_tools._build_safe_request_kwargs`      |
| Worker → Worker (Redis)        | n/a            | Not yet propagated; tracked separately.                           |

The injection helpers are deliberately **side-effect free** when
OpenTelemetry is not installed or no provider has been initialised —
they import lazily, swallow `ImportError`, and never raise. This keeps
local dev (no tracing extras) byte-for-byte compatible with production
(full tracing).

### Operator setup (production)

To turn the propagation into actual exported traces:

1. Install the tracing extras on every service:

   ```bash
   pip install 'selva-observability[tracing]'
   ```

2. Set `OTEL_EXPORTER_OTLP_ENDPOINT` on every service pod:

   ```bash
   OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example.com:4317
   # Optional — for vendor-specific auth (Honeycomb, Datadog, Tempo, …)
   OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<key>,x-honeycomb-dataset=selva
   ```

3. (Optional) Set the resource attributes for service identification.
   `init_tracing(service_name)` already sets `service.name`; add
   environment / version via env vars if your backend supports them:

   ```bash
   OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.version=v2.2.x
   ```

The vendor decision (Honeycomb vs. Tempo vs. self-hosted Jaeger) is
tracked in `docs/OBSERVABILITY_VENDOR_SELECTION.md`. This package is
vendor-agnostic — `init_tracing` uses the OTLP gRPC exporter so any
backend that speaks OTLP works.

### What "propagation" means in this PR

- **Today**: every outbound HTTP request from an instrumented call site
  carries `traceparent`. nexus-api extracts it and any spans created in
  the request handler become children of the upstream span.
- **Without an exporter**: the spans are still created and have valid
  trace_ids — they just aren't sent anywhere. So the moment an exporter
  is wired (operator action above) traces start correlating, with no
  code change required.

### Adding a new propagation call site

When you add a new outbound HTTP call from a Selva service:

```python
from selva_observability import inject_trace_context

headers = {"Authorization": f"Bearer {token}"}
inject_trace_context(headers)  # mutates in place AND returns headers
await client.post(url, headers=headers, json=payload)
```

Or, if it's a tool that already goes through `_build_safe_request_kwargs`
(SSRF-protected outbound HTTP), propagation is automatic — no code
change needed.

### Adding a new server-side extraction call site

If you add a new FastAPI app (not the nexus-api), mount the
`TraceContextMiddleware` early in the stack — after security headers
but before any middleware that creates spans:

```python
from nexus_api.middleware.tracing import TraceContextMiddleware

app.add_middleware(RequestIdMiddleware)
app.add_middleware(TraceContextMiddleware)  # AFTER request id (LIFO)
```

(Or extract the middleware into `selva_observability` if more services
need it.)
