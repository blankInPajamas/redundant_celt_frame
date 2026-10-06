#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

DIR="$ROOT/logs/phase_a/repro_32k_audio"
ENC_LOG="$DIR/encoder.log"
PKT="$DIR/packets.txt"
ENCODED="$DIR/encoded.bin"
PARSE="$ROOT/scripts/parse_packets.py"

echo "=== Verification of 32 kbps audio run ==="
echo

if [ ! -f "$ENC_LOG" ]; then
  echo "ERROR: $ENC_LOG missing. Run reproduce_32k_audio.sh first."
  exit 1
fi

echo "--- Redundancy decisions ---"
grep -c 'REDUNDANCY' "$ENC_LOG" 2>/dev/null || echo 0

echo
echo "--- Proposed sizes ---"
grep -oE 'bytes=[0-9]+' "$ENC_LOG" 2>/dev/null || echo "(none)"

echo
echo "--- packets.txt ---"
if [ ! -s "$PKT" ]; then
  echo "packets.txt missing or empty; regenerating..."
  if [ -f "$ENCODED" ]; then
    python3 "$PARSE" "$ENCODED" > "$PKT"
    echo "Regenerated: $PKT ($(wc -l < "$PKT") lines)"
  else
    echo "ERROR: $ENCODED missing. Cannot regenerate."
    exit 1
  fi
else
  echo "packets.txt present ($(wc -l < "$PKT") lines)"
fi

echo
echo "--- First 10 packets ---"
head -n 10 "$PKT"

echo
echo "--- Check for 38-byte proposal ---"
if grep -q 'bytes=38' "$ENC_LOG" 2>/dev/null; then
  echo "REPRODUCED: 38-byte proposal present"
else
  echo "NOT REPRODUCED: no 38-byte proposal"
fi

echo
echo "--- Check for 3-byte first packets ---"
if head -n 5 "$PKT" 2>/dev/null | grep -q 'pkt_len=3'; then
  echo "REPRODUCED: 3-byte initial packets present"
else
  echo "NOTE: no 3-byte initial packets in first 5 lines of packets.txt"
  echo "      (expected if input does not begin with silence)"
fi