#!/usr/bin/env bash
# Run k6 Run 4 calibration scenario (no-LLM graph_type=calibration).
#
# Usage:
#   ./scripts/run-staging-load-calibration.sh
#   ./scripts/run-staging-load-calibration.sh --skip-drain
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/run-staging-load-full.sh" --script calibration-dispatch.js "$@"
