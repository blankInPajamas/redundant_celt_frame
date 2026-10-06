#!/usr/bin/env bash
# inventory_tree.sh — top-level directory tree (depth-limited)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"


OUT="logs/phase_a/tree.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Directory tree (depth 3) ==="
  find . -maxdepth 3 -not -path '*/.git/*' -not -path '*/node_modules/*' \
    | sort
} | tee "$OUT"

echo "Wrote $OUT"
