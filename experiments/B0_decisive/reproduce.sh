#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

EXPDIR="$SCRIPT_DIR"

# ------------------------------------------------------------------
# Parameters — change these here, not in the pipeline scripts
# ------------------------------------------------------------------
INPUT_PCM="${INPUT_PCM:-$ROOT/data/pcm/spontaneous-speech-en-1.pcm}"
APP=audio
BITRATE=32000
FRAME_IDX=3
FRAME_LEN=84

# ------------------------------------------------------------------
# Step 1: encode
# ------------------------------------------------------------------
OUTDIR="$ROOT/logs/phase_b/B0"
mkdir -p "$OUTDIR"

LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
  "$INPUT_PCM" "$OUTDIR/encoded.bin" "$APP" "$BITRATE" \
  2> "$OUTDIR/encoder.log"

# ------------------------------------------------------------------
# Step 2: probe every byte of the target frame
# ------------------------------------------------------------------
BASELINE_PCM="$OUTDIR/baseline.pcm"
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
  "$OUTDIR/encoded.bin" "$BASELINE_PCM" 2> "$OUTDIR/baseline.log"

echo "byte_offset,decode_rc,identical_to_baseline" > "$OUTDIR/results.csv"

for offset in $(seq 0 $((FRAME_LEN - 1))); do
  MOD_BIN="$OUTDIR/mod_$offset.bin"
  MOD_PCM="$OUTDIR/mod_$offset.pcm"

  python3 "$ROOT/scripts/modify_packet.py" \
    "$OUTDIR/encoded.bin" "$MOD_BIN" "$FRAME_IDX" "$offset" \
    > /dev/null 2>&1

  set +e
  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
    "$MOD_BIN" "$MOD_PCM" 2> /dev/null
  RC=$?
  set -e

  IDENT="NA"
  if [ -f "$MOD_PCM" ] && cmp -s "$MOD_PCM" "$BASELINE_PCM"; then
    IDENT="yes"
  elif [ -f "$MOD_PCM" ]; then
    IDENT="no"
  fi

  echo "$offset,$RC,$IDENT" >> "$OUTDIR/results.csv"
done

echo "B.0 done. Results: $OUTDIR/results.csv"