#!/usr/bin/env bash
# inventory_inputs.sh — inventory PCM test vectors
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OPUS_SRC="$ROOT/opus"
TOOLS="$ROOT/scripts"        # encode_raw, decode_raw, *.py live here
DATA="$ROOT/data"

OUT="logs/phase_a/inputs_inventory.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Test vector inventory ==="
  echo
  echo "--- PCM/WAV files ---"
  find . -type f \( -name '*.pcm' -o -name '*.wav' -o -name '*.raw' \) 2>/dev/null | sort | while read -r f; do
    size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")
    # assume 48 kHz mono s16le => 96000 bytes/sec
    secs=$(python3 -c "print(f'{$size/96000:.3f}')" 2>/dev/null || echo "?")
    printf "%-60s %10s bytes  ~%ss\n" "$f" "$size" "$secs"
  done
  echo
  echo "--- Mozilla Spontaneous Speech references ---"
  find . -iname '*mozilla*' -o -iname '*spontaneous*' 2>/dev/null | sort
} | tee "$OUT"

echo "Wrote $OUT"
