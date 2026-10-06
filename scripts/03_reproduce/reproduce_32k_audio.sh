#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

TOOLS="$ROOT/scripts"
DATA="$ROOT/data"
OPUS_LIB="$ROOT/opus/.libs"
OUTDIR="$ROOT/logs/phase_a/repro_32k_audio"
mkdir -p "$OUTDIR"

# --- CRITICAL: use the instrumented libopus, not the system one ---
export LD_LIBRARY_PATH="$OPUS_LIB:${LD_LIBRARY_PATH:-}"

ENCODE="$TOOLS/encode_raw"
DECODE="$TOOLS/decode_raw"
PARSE="$TOOLS/parse_packets.py"
AUTOMATE="$TOOLS/automate.py"

INPUT_PCM="${INPUT_PCM:-$DATA/pcm/spontaneous-speech-en-1.pcm}"
ENCODED="$OUTDIR/encoded.bin"
ENC_LOG="$OUTDIR/encoder.log"
DEC_LOG="$OUTDIR/decoder.log"

echo "=== Using input: $INPUT_PCM ==="
ls -la "$INPUT_PCM"

echo
echo "=== Verifying which libopus encode_raw is using ==="
ldd "$ENCODE" | grep libopus || true
echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"

echo
echo "=== Encoding: audio mode, 32 kbps ==="
set +e
"$ENCODE" "$INPUT_PCM" "$ENCODED" audio 32000 2> "$ENC_LOG"
RC=$?
set -e
echo "encode_raw exit code: $RC"

if [ $RC -ne 0 ]; then
  echo "encode_raw FAILED. Last 30 lines:"
  tail -n 30 "$ENC_LOG"
  exit 1
fi

echo
echo "=== Decoding ==="
"$DECODE" "$ENCODED" "$OUTDIR/decoded.pcm" 2> "$DEC_LOG" || true

echo
echo "=== REDUNDANCY lines in encoder log ==="
grep -n 'REDUNDANCY' "$ENC_LOG" || echo "(none)"

echo
echo "=== First 15 packet lines ==="
grep -n 'FRAME\|FINAL' "$ENC_LOG" | head -n 20

echo
echo "=== Parsing ==="
python3 "$PARSE" "$ENCODED" > "$OUTDIR/packets.txt" 2>&1 || true
head -n 15 "$OUTDIR/packets.txt" || true

echo
echo "=== Correlation ==="
python3 "$AUTOMATE" "$ENC_LOG" "$ENCODED" > "$OUTDIR/correlation.txt" 2>&1 || true
cat "$OUTDIR/correlation.txt" 2>/dev/null || true

echo
echo "Artifacts in: $OUTDIR"