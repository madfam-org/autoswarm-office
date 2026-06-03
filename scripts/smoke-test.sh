#!/usr/bin/env bash
# Verify all Selva services are reachable and the agent loop is functional.
set -euo pipefail

API="${NEXUS_API_URL:-http://localhost:${NEXUS_API_PORT:-4300}}"
UI="${OFFICE_UI_URL:-http://localhost:${OFFICE_UI_PORT:-4301}}"
COLYSEUS="${COLYSEUS_URL:-http://localhost:${COLYSEUS_PORT:-4303}}"
WORKER="${WORKER_URL:-http://localhost:${WORKER_PORT:-4305}}"

echo "=== Selva Smoke Test ==="

# Health checks
curl -sf "$API/api/v1/health/health" > /dev/null && echo "✅ nexus-api healthy" || echo "❌ nexus-api unreachable"
curl -sf "$COLYSEUS/health" > /dev/null && echo "✅ colyseus healthy" || echo "❌ colyseus unreachable"
curl -sf "$WORKER/health" > /dev/null && echo "✅ worker healthy" || echo "❌ worker unreachable"
curl -sf "$UI" > /dev/null && echo "✅ office-ui healthy" || echo "❌ office-ui unreachable"

# API readiness (checks DB + Redis)
curl -sf "$API/api/v1/health/ready" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ DB:', d['checks']['database'], '| Redis:', d['checks']['redis'])" 2>/dev/null || echo "❌ readiness check failed"

# Queue stats
curl -sf "$API/api/v1/health/queue-stats" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ Stream:', d.get('stream_length',0), '| DLQ:', d.get('dlq_depth',0))" 2>/dev/null || echo "❌ queue stats unavailable"

# Agent count
curl -sf -H "Authorization: Bearer dev" "$API/api/v1/agents" | python3 -c "import sys,json; agents=json.load(sys.stdin); n=len(agents); print(f'✅ {n} agents seeded') if n > 0 else (print('❌ No agents seeded (run: make dev-seed)'), sys.exit(1))" 2>/dev/null || { echo "❌ No agents (run: make dev-seed)"; exit 1; }

echo "=== Done ==="
