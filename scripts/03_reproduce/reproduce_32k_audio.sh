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

export LD_LIBRARY_PATH="$OPUS_LIB:${LD_LIBRARY_PATH:-}"

ENCODE="$TOOLS/encode_raw"
DECODE="$TOOLS/decode_raw"
PARSE="$TOOLS/parse_packets.py"
AUTOMATE="$TOOLS/automate.py"

INPUT_PCM="${INPUT_PCM:-$DATA/pcm/spontaneous-speech-en-1.pcm}"
ENCODED="$OUTDIR/encoded.bin"
ENC_LOG="$OUTDIR/encoder.log"
DEC_LOG="$OUTDIR/decoder.log"
PKT_TXT="$OUTDIR/packets.txt"
CORR_TXT="$OUTDIR/correlation.txt"

echo "=== Using input: $INPUT_PCM ==="
ls -la "$INPUT_PCM"

echo
echo "=== encode_raw CLI ==="
"$ENCODE" 2>&1 | head -n 3 || true

echo
echo "=== Encoding: audio mode, 32 kbps ==="
"$ENCODE" "$INPUT_PCM" "$ENCODED" audio 32000 2> "$ENC_LOG"
echo "encode_raw exit code: $?"

echo
echo "=== Decoding ==="
"$DECODE" "$ENCODED" "$OUTDIR/decoded.pcm" 2> "$DEC_LOG"
echo "decode_raw exit code: $?"

echo
echo "=== REDUNDANCY lines ==="
grep -n 'REDUNDANCY' "$ENC_LOG" || echo "(none)"

echo
echo "=== First 15 FRAME/FINAL lines ==="
awk '/FRAME|FINAL/ {print; n++; if (n>=20) exit}' "$ENC_LOG"

echo
echo "=== Parsing packets ==="
if ! python3 "$PARSE" "$ENCODED" > "$PKT_TXT" 2> "$OUTDIR/parse.err"; then
  echo "PARSE FAILED. See $OUTDIR/parse.err"
  cat "$OUTDIR/parse.err"
  exit 1
fi
echo "Wrote $PKT_TXT ($(wc -l < "$PKT_TXT") lines)"
head -n 10 "$PKT_TXT"

echo
echo "=== Correlation ==="
if ! python3 "$AUTOMATE" "$ENC_LOG" > "$CORR_TXT" 2> "$OUTDIR/correlation.err"; then
  echo "CORRELATE FAILED. See $OUTDIR/correlation.err"
  cat "$OUTDIR/correlation.err"
  exit 1
fi
cat "$CORR_TXT"

echo
echo "Artifacts in: $OUTDIR"