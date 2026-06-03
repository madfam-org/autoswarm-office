# Load Tests

k6 load testing scripts for the Selva Office platform.

## Prerequisites

Install k6:

```bash
# macOS
brew install k6

# Go
go install go.k6.io/k6@latest

# Docker (no install needed)
docker run --rm -i grafana/k6 run - <script.js
```

## Test Scripts

| Script | Target | What it measures |
|--------|--------|------------------|
| `nexus-api-throughput.js` | Nexus API (port 4300) | HTTP endpoint latency and error rate under ramp-up to 100 VUs |
| `colyseus-concurrent.js` | Colyseus (port 4303) | WebSocket connection capacity and message round-trip time at 50 concurrent players |
| `task-queue-throughput.js` | Redis task queue | Sustained dispatch rate (100/min) and queue depth backpressure |
| `concurrent-100-swarmtasks.js` | Nexus API (staging/prod) | 100 VU ramp/hold/drain — Phase 0.4 calibration scenario |
| `approval-flow-e2e.js` | Full approval pipeline | End-to-end latency from task dispatch through approval resolution |

## Running Tests

```bash
# Start services first
make docker-dev && make dev

# Run a single test
k6 run tests/load/nexus-api-throughput.js

# Override target URL
k6 run -e BASE_URL=http://staging.example.com:4300 tests/load/nexus-api-throughput.js

# Override auth token
k6 run -e AUTH_TOKEN=eyJhbGciOi... tests/load/nexus-api-throughput.js

# WebSocket test with custom URL
k6 run -e WS_URL=ws://staging.example.com:4303 tests/load/colyseus-concurrent.js
```

## Environment Variables

| Variable | Default | Used by |
|----------|---------|---------|
| `BASE_URL` | `http://localhost:4300` | nexus-api-throughput, task-queue-throughput, approval-flow-e2e |
| `WS_URL` | `ws://localhost:4303` | colyseus-concurrent |
| `AUTH_TOKEN` | `dev-token` | All scripts (Bearer auth header) |

## Interpreting Results

k6 prints a summary table after each run. Key metrics to watch:

- **http_req_duration p(95)**: 95th percentile response time. Threshold is 500ms for API endpoints.
- **errors rate**: Fraction of failed requests. Threshold is <1% for all scripts.
- **ws_round_trip_ms p(95)**: WebSocket message send latency. Threshold is 100ms.
- **queue_depth value**: Redis queue backlog. Threshold is <50 pending items.
- **e2e_approval_duration_ms p(95)**: Full dispatch-to-approval cycle. Threshold is 5000ms.

A threshold breach causes k6 to exit with a non-zero code, which fails CI.

## CI Integration

Workflow: `.github/workflows/load-test.yml` (`workflow_dispatch`).

Trigger from GitHub Actions → **Load Tests** → pick script + `base_url`
(default `https://staging-api.selva.town`). Set repo secret
`STAGING_LOAD_TEST_TOKEN` for authenticated staging runs.

Manual template (local):

```yaml
name: Load Tests
on:
  workflow_dispatch:
    inputs:
      script:
        description: "Test script to run"
        required: true
        type: choice
        options:
          - nexus-api-throughput.js
          - colyseus-concurrent.js
          - task-queue-throughput.js
          - approval-flow-e2e.js
      base_url:
        description: "Target base URL"
        required: false
        default: "http://localhost:4300"

jobs:
  load-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: selva
          POSTGRES_USER: selva
          POSTGRES_PASSWORD: selva
        ports:
          - 5432:5432
      redis:
        image: redis:7
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      - uses: grafana/setup-k6-action@v1
      - run: k6 run -e BASE_URL=${{ inputs.base_url }} tests/load/${{ inputs.script }}
```
