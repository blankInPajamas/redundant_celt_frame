#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B4"
mkdir -p "$OUT"

MESSAGE="HybridModeOfOpus:CELT+SILK"
TARGET_FRAME=3

# 1. Encode
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
  data/pcm/spontaneous-speech-en-1.pcm "$OUT/original.bin" audio 32000 2> "$OUT/encode.log"

# 2. Baseline decode
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
  "$OUT/original.bin" "$OUT/baseline.pcm" 2> /dev/null

# 3. Embed
python3 "$SCRIPT_DIR/embed.py" "$OUT/original.bin" "$OUT/modified.bin" "$MESSAGE" "$TARGET_FRAME"

# 4. Decode modified
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
  "$OUT/modified.bin" "$OUT/modified.pcm" 2> "$OUT/decode.log"

# 5. Compare decoded PCM
if cmp -s "$OUT/baseline.pcm" "$OUT/modified.pcm"; then
  echo "PASS: modified decode identical to baseline"
else
  echo "FAIL: modified decode differs from baseline"
fi

# 6. Extract message and write to file (avoids shell null stripping)
python3 "$SCRIPT_DIR/extract.py" "$OUT/modified.bin" > "$OUT/recovered.txt"
cp "$OUT/recovered.txt" "$SCRIPT_DIR/recovered.txt"

echo "Expected: $MESSAGE"
echo "Recovered: $(cat "$OUT/recovered.txt")"

if [ "$MESSAGE" = "$(cat "$OUT/recovered.txt")" ]; then
  echo "PASS: message recovered exactly"
else
  echo "FAIL: message not recovered"
fi