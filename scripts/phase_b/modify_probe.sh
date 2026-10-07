#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

TOOLS="$ROOT/scripts"
OPUS_LIB="$ROOT/opus/.libs"
OUTDIR="$ROOT/logs/phase_b/modify_probe"
mkdir -p "$OUTDIR"

export LD_LIBRARY_PATH="$OPUS_LIB:${LD_LIBRARY_PATH:-}"

INPUT="$ROOT/logs/phase_a/repro_32k_audio/encoded.bin"
BASELINE_PCM="$OUTDIR/baseline.pcm"
FRAME_IDX=3
FRAME_LEN=84

# Baseline decode
"$TOOLS/decode_raw" "$INPUT" "$BASELINE_PCM" 2> "$OUTDIR/baseline.log"

RESULT_CSV="$OUTDIR/results.csv"
echo "byte_offset,decode_rc,pcm_size,identical_to_baseline" > "$RESULT_CSV"

for offset in $(seq 0 $((FRAME_LEN - 1))); do
  MOD_BIN="$OUTDIR/mod_$offset.bin"
  MOD_PCM="$OUTDIR/mod_$offset.pcm"
  MOD_LOG="$OUTDIR/mod_$offset.log"

  python3 "$TOOLS/modify_packet.py" "$INPUT" "$MOD_BIN" "$FRAME_IDX" "$offset" \
    > "$OUTDIR/mod_$offset.modify.log" 2>&1

  set +e
  "$TOOLS/decode_raw" "$MOD_BIN" "$MOD_PCM" 2> "$MOD_LOG"
  RC=$?
  set -e

  SIZE=0
  IDENT="NA"
  if [ -f "$MOD_PCM" ]; then
    SIZE=$(wc -c < "$MOD_PCM")
    if cmp -s "$MOD_PCM" "$BASELINE_PCM"; then
      IDENT="yes"
    else
      IDENT="no"
    fi
  fi

  echo "$offset,$RC,$SIZE,$IDENT" >> "$RESULT_CSV"
  printf "byte %2d -> rc=%d pcm=%d identical=%s\n" "$offset" "$RC" "$SIZE" "$IDENT"
done

echo
echo "Results written to $RESULT_CSV"
column -t -s, "$RESULT_CSV"