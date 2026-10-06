#!/usr/bin/env bash
# verify_32k_audio.sh — check whether the 32 kbps run reproduces
# the original finding: 38-byte proposal, 3-byte final packet.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"


DIR="logs/phase_a/repro_32k_audio"
ENC_LOG="$DIR/encoder.log"
PKT="$DIR/packets.txt"

echo "=== Verification of 32 kbps audio run ==="
echo
echo "--- Redundancy decisions ---"
grep -c 'REDUNDANCY' "$ENC_LOG" 2>/dev/null || echo 0

echo
echo "--- Proposed sizes ---"
grep -oE 'bytes=[0-9]+' "$ENC_LOG" 2>/dev/null || echo "(none)"

echo
echo "--- First 10 packets ---"
head -n 10 "$PKT" 2>/dev/null || echo "(no packet dump)"

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
  echo "NOT REPRODUCED: no 3-byte initial packets"
fi
