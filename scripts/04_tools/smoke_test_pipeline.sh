#!/usr/bin/env bash
# smoke_test_pipeline.sh — end-to-end smoke test of the pipeline
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="logs/phase_a/smoke_test"
mkdir -p "$OUT"

# Create a tiny 1-second silence input if none exists
TMP_PCM="$OUT/silence_1s.pcm"
python3 - <<PY
import struct
with open("$TMP_PCM", "wb") as f:
    f.write(struct.pack("<" + "h"*48000, *([0]*48000)))
print("wrote $TMP_PCM")
PY

echo "=== Encode ==="
./encode_raw --application voip --bitrate 24000 --samplerate 48000 --channels 1 \
  "$TMP_PCM" "$OUT/encoded.bin" 2> "$OUT/encoder.log" || {
    echo "encode_raw failed"; exit 1;
  }

echo "=== Parse ==="
python3 parse_packets.py "$OUT/encoded.bin" > "$OUT/packets.txt"
head -n 5 "$OUT/packets.txt"

echo "=== Decode ==="
./decode_raw "$OUT/encoded.bin" "$OUT/decoded.pcm" 2> "$OUT/decoder.log"
ls -la "$OUT"

echo "Smoke test complete."
