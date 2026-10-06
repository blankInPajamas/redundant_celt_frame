#!/usr/bin/env bash
# check_python_tools.sh — verify the Python toolchain is intact
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"


OUT="logs/phase_a/python_tools_check.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Python tools check ==="
  echo
  for t in parse_packets.py automate.py modify_packet.py; do
    if [ -f "$t" ]; then
      echo "FOUND: $t"
      echo "--- head ---"
      head -n 20 "$t"
      echo "--- syntax check ---"
      python3 -m py_compile "$t" && echo "OK" || echo "SYNTAX ERROR"
      echo
    else
      echo "MISSING: $t"
      echo
    fi
  done
} | tee "$OUT"

echo "Wrote $OUT"
