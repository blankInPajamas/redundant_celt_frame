#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B4_all"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/results_all.csv"
echo "file,frames,embed_frame,embed_ok,decode_rc,pcm_identical,recovered,recovery_ok" > "$RESULTS"

MESSAGE="HybridModeOfOpus:CELT+SILK"

for pcm in data/pcm/spontaneous-speech-en-*.pcm; do
  [ -f "$pcm" ] || continue
  name=$(basename "$pcm" .pcm)

  original="$OUT/${name}_original.bin"
  if ! LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
       "$pcm" "$original" audio 32000 2>/dev/null; then
    echo "$name,0,,ENCODE_FAIL,0,no,,no" >> "$RESULTS"
    continue
  fi

  baseline_pcm="$OUT/${name}_baseline.pcm"
  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
    "$original" "$baseline_pcm" 2>/dev/null

  modified="$OUT/${name}_modified.bin"
  embed_out=$(python3 "$SCRIPT_DIR/embed.py" "$original" "$modified" "$MESSAGE" 2>&1) || true

  if echo "$embed_out" | grep -q 'embedded'; then
    embed_frame=$(echo "$embed_out" | sed -n 's/.*into frame \([0-9]*\).*/\1/p')
    embed_ok="OK"
  else
    echo "$name,,,EMBED_FAIL,0,no,,no" >> "$RESULTS"
    continue
  fi

  modified_pcm="$OUT/${name}_modified.pcm"
  set +e
  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/decode_raw \
    "$modified" "$modified_pcm" 2>/dev/null
  RC=$?
  set -e

  if cmp -s "$baseline_pcm" "$modified_pcm"; then
    IDENT="yes"
  else
    IDENT="no"
  fi

  recovered=$(python3 "$SCRIPT_DIR/extract.py" "$modified" 2>/dev/null || echo "")
  if [ "$recovered" = "$MESSAGE" ]; then
    OK="yes"
  else
    OK="no"
  fi

  frames=$(python3 - "$original" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
off = 0; cnt = 0
while off + 4 <= len(data):
    ln = struct.unpack("<I", data[off:off+4])[0]
    off += 4 + ln
    cnt += 1
print(cnt)
PY
)

  echo "$name,$frames,$embed_frame,$embed_ok,$RC,$IDENT,$recovered,$OK" >> "$RESULTS"
done

echo "B4_all done. Results: $RESULTS"
echo
echo "=== Summary ==="
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open('experiments/B4_payload/results_all.csv')))
n = len(rows)
print(f"Total files: {n}")
print(f"Embed OK:    {sum(1 for r in rows if r['embed_ok'] == 'OK')}/{n}")
print(f"Decode OK:   {sum(1 for r in rows if r['decode_rc'] == '0')}/{n}")
print(f"PCM identical: {sum(1 for r in rows if r['pcm_identical'] == 'yes')}/{n}")
print(f"Recovery OK: {sum(1 for r in rows if r['recovery_ok'] == 'yes')}/{n}")
PY
