#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B6"
mkdir -p "$OUT"

# Clean stream
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
  data/pcm/spontaneous-speech-en-1.pcm "$OUT/clean.bin" audio 32000 2> /dev/null

# Stego stream (embed 32 'A's into frame 3)
python3 "$ROOT/experiments/B4_payload/embed.py" \
  "$OUT/clean.bin" "$OUT/stego_32.bin" "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" 3

echo "=== Clean stream ==="
python3 "$SCRIPT_DIR/detectors.py" "$OUT/clean.bin"

echo
echo "=== Stego stream (32-byte payload) ==="
python3 "$SCRIPT_DIR/detectors.py" "$OUT/stego_32.bin"