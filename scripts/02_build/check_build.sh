#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="$LOG_DIR/build_check.txt"
OPUS_SRC="$ROOT/opus"
TOOLS="$ROOT/scripts"

{
  echo "=== Build state ==="
  echo
  echo "--- Custom tools ---"
  for b in encode_raw decode_raw; do
    f="$TOOLS/$b"
    if [ -x "$f" ]; then
      echo "FOUND: $f"
      file "$f"
      ldd "$f" 2>/dev/null | head -n 5 || true
    else
      echo "MISSING or not executable: $f"
    fi
    echo
  done

  echo "--- Which libopus does encode_raw link against? ---"
  ldd "$TOOLS/encode_raw" | grep -i opus || true
  echo "Expected: $OPUS_SRC/.libs/libopus.so.0"
  echo

  echo "--- opus_demo ---"
  for cand in "$OPUS_SRC/opus_demo" "$OPUS_SRC/.libs/opus_demo"; do
    [ -e "$cand" ] && echo "FOUND: $cand" && file "$cand"
  done
  echo

  echo "--- libopus artifacts ---"
  ls -la "$OPUS_SRC/.libs/libopus."* 2>/dev/null || echo "(none)"
  echo

  echo "--- Object files ---"
  find "$OPUS_SRC" -name 'opus_encoder.o' -o -name 'opus_decoder.o' 2>/dev/null | sort
  echo

  echo "--- config.log (last 20 lines) ---"
  if [ -f "$OPUS_SRC/config.log" ]; then
    tail -n 20 "$OPUS_SRC/config.log"
  else
    echo "no config.log at $OPUS_SRC"
  fi
} | tee "$OUT"

echo "Wrote $OUT"