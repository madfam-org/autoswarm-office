#!/usr/bin/env bash
# Run k6 Run 4 calibration scenario (no-LLM graph_type=calibration).
#
# Usage:
#   ./scripts/run-staging-load-calibration.sh
#   ./scripts/run-staging-load-calibration.sh --skip-drain
#   ./scripts/run-staging-load-calibration.sh --skip-preflight
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_PREFLIGHT=false
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-preflight)
      SKIP_PREFLIGHT=true
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "$SKIP_PREFLIGHT" != "true" ]]; then
  "${ROOT}/scripts/verify-staging-load-run4b-preflight.sh" --require-live
fi

exec "${ROOT}/scripts/run-staging-load-full.sh" --script calibration-dispatch.js "${ARGS[@]}"
