#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B4"
mkdir -p "$OUT"

# 1. Encode
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
  data/pcm/spontaneous-speech-en-1.pcm "$OUT/original.bin" audio 32000 2> "$OUT/encode.log"

# 2. Baseline decode
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
  "$OUT/original.bin" "$OUT/baseline.pcm" 2> /dev/null

# 3. Embed message
MESSAGE="Hello,OpusCovert"
python3 "$SCRIPT_DIR/embed.py" "$OUT/original.bin" "$OUT/modified.bin" "$MESSAGE"

# 4. Decode modified
LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
  "$OUT/modified.bin" "$OUT/modified.pcm" 2> "$OUT/decode.log"

# 5. Compare
if cmp -s "$OUT/baseline.pcm" "$OUT/modified.pcm"; then
  echo "PASS: modified decode identical to baseline"
else
  echo "FAIL: modified decode differs from baseline"
fi

# 6. Extract
RECOVERED=$(python3 "$SCRIPT_DIR/extract.py" "$OUT/modified.bin" $((${#MESSAGE} * 8)))
echo "Expected: $MESSAGE"
echo "Recovered: $RECOVERED"
if [ "$MESSAGE" = "$RECOVERED" ]; then
  echo "PASS: message recovered exactly"
else
  echo "PARTIAL: message recovered with errors"
fi