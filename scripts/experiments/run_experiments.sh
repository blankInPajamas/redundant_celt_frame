#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

for exp in B0_decisive B1_multitransition B2_oneshot_sweep B3_tail_scaling B4_payload; do
  echo "========== Running $exp =========="
  bash "experiments/$exp/reproduce.sh"
  if [ -f "experiments/$exp/analyze.py" ]; then
    python3 "experiments/$exp/analyze.py" || true
  fi
  echo
done

echo "All experiments complete."