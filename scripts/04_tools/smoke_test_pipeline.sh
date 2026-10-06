#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

TOOLS="$ROOT/scripts"
OPUS_LIB="$ROOT/opus/.libs"
OUT="$ROOT/logs/phase_a/smoke_test"
mkdir -p "$OUT"

export LD_LIBRARY_PATH="$OPUS_LIB:${LD_LIBRARY_PATH:-}"

# Create a 1-second silence PCM if none exists
TMP_PCM="$OUT/silence_1s.pcm"
python3 - <<PY
import struct
with open("$TMP_PCM", "wb") as f:
    f.write(struct.pack("<" + "h"*48000, *([0]*48000)))
print("wrote $TMP_PCM")
PY

echo
echo "=== encode_raw usage (for reference) ==="
"$TOOLS/encode_raw" 2>&1 | head -n 5 || true
echo

echo "=== Encode: voip mode, 24 kbps ==="
"$TOOLS/encode_raw" "$TMP_PCM" "$OUT/encoded.bin" voip 24000 \
  2> "$OUT/encoder.log"
echo "encode_raw exit code: $?"

echo
echo "=== Encoder log (first 20 lines) ==="
head -n 20 "$OUT/encoder.log"

echo
echo "=== Parse with parse_packets.py ==="
python3 "$TOOLS/parse_packets.py" "$OUT/encoded.bin" > "$OUT/packets.txt" 2>&1 || {
  echo "parse_packets.py failed:"; cat "$OUT/packets.txt"; }

echo
echo "=== First 10 parsed packets ==="
head -n 10 "$OUT/packets.txt" || true

echo
echo "=== Decode ==="
"$TOOLS/decode_raw" "$OUT/encoded.bin" "$OUT/decoded.pcm" 2> "$OUT/decoder.log"
echo "decode_raw exit code: $?"
ls -la "$OUT"

echo
echo "Smoke test complete."