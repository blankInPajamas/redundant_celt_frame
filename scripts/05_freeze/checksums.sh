#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="$LOG_DIR/checksums.txt"
OPUS_SRC="$ROOT/opus"
TOOLS="$ROOT/scripts"

{
  echo "=== Checksums (SHA-256) ==="
  echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  for f in \
    "$OPUS_SRC/src/opus_encoder.c" \
    "$OPUS_SRC/src/opus_decoder.c" \
    "$TOOLS/encode_raw.c" \
    "$TOOLS/decode_raw.c" \
    "$TOOLS/parse_packets.py" \
    "$TOOLS/automate.py" \
    "$TOOLS/modify_packet.py" \
    "$TOOLS/setup.sh" \
    "$ROOT/patches/0001-redundancy-instrumentation.patch" \
    "$ROOT/patches/0002-fix-frame-correlation.patch"
  do
    if [ -f "$f" ]; then
      sha256sum "$f"
    else
      echo "MISSING $f"
    fi
  done
} | tee "$OUT"

echo "Wrote $OUT"