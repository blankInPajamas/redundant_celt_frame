#!/usr/bin/env bash
# inventory_logs.sh — inventory existing logs and outputs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"


OUT="logs/phase_a/logs_inventory.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Logs and outputs inventory ==="
  echo
  echo "--- REDUNDANCY logs ---"
  grep -rl 'REDUNDANCY' . --include='*.log' --include='*.txt' 2>/dev/null | sort || echo "(none)"
  echo
  echo "--- Encoded .bin outputs ---"
  find . -type f -name '*.bin' 2>/dev/null | sort
  echo
  echo "--- Decoded PCM outputs ---"
  find . -type f -name '*decoded*.pcm' 2>/dev/null | sort
  echo
  echo "--- Any 32 kbps audio run artifacts ---"
  find . -type f \( -iname '*32k*' -o -iname '*audio*' \) 2>/dev/null | sort
} | tee "$OUT"

echo "Wrote $OUT"
