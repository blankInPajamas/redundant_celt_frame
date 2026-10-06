#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="$LOG_DIR/instrumentation_check.txt"
OPUS_SRC="$ROOT/opus"

{
  echo "=== Instrumentation check ==="
  echo
  echo "--- REDUNDANCY markers in opus/src/opus_encoder.c ---"
  if [ -f "$OPUS_SRC/src/opus_encoder.c" ]; then
    grep -n 'REDUNDANCY' "$OPUS_SRC/src/opus_encoder.c" || echo "(none)"
  else
    echo "NOT FOUND: $OPUS_SRC/src/opus_encoder.c"
  fi
  echo
  echo "--- Final packet logging markers ---"
  grep -n 'opus_encode_frame_native\|final.*packet\|pkt_len\|FINAL_PKT' \
    "$OPUS_SRC/src/opus_encoder.c" 2>/dev/null | head -n 40 || true
  echo
  echo "--- All instrumented files (grep for REDUNDANCY across opus/) ---"
  grep -rln 'REDUNDANCY' "$OPUS_SRC" 2>/dev/null || echo "(none)"
  echo
  echo "--- Git diff of opus repo ---"
  if [ -d "$OPUS_SRC/.git" ]; then
    (cd "$OPUS_SRC" && git diff --stat)
    echo
    (cd "$OPUS_SRC" && git log -1 --oneline)
  else
    echo "no .git in $OPUS_SRC"
  fi
} | tee "$OUT"

echo "Wrote $OUT"