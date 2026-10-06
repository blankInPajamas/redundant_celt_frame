#!/usr/bin/env bash
# inventory_opus.sh — locate and identify the libopus source tree
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="logs/phase_a/opus_inventory.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== libopus source inventory ==="
  echo
  echo "--- Candidate directories ---"
  find . -maxdepth 3 -type d -name 'opus*' 2>/dev/null | sort
  echo
  echo "--- Version markers ---"
  find . -maxdepth 3 -name 'configure.ac' -o -name 'version.mk' 2>/dev/null | while read -r f; do
    echo ">> $f"
    grep -E 'OPUS_VERSION|AC_INIT|PACKAGE_VERSION' "$f" 2>/dev/null || true
  done
  echo
  echo "--- Git status (if repo) ---"
  if [ -d .git ]; then
    git rev-parse HEAD 2>/dev/null || true
    git status --porcelain 2>/dev/null || true
    git log -1 --oneline 2>/dev/null || true
  else
    echo "not a git repo at project root"
  fi
  echo
  echo "--- Instrumented file presence ---"
  for f in src/opus_encoder.c src/opus_decoder.c celt/celt_encoder.c; do
    if [ -f "$f" ]; then
      echo "FOUND: $f"
      grep -n 'REDUNDANCY' "$f" 2>/dev/null | head -n 20 || echo "  (no REDUNDANCY markers)"
    fi
  done
} | tee "$OUT"

echo "Wrote $OUT"
