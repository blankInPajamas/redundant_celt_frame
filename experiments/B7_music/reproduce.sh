#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B7"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/results.csv"
echo "content_type,file,frames,tail_frames,max_tail" > "$RESULTS"

for pcm in data/pcm/music/*.pcm; do
  [ -f "$pcm" ] || continue
  name=$(basename "$pcm" .pcm)
  bin="$OUT/${name}.bin"

  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
    "$pcm" "$bin" audio 32000 2> /dev/null

  python3 - "$bin" "$name" >> "$RESULTS" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
off = 0; fid = 0; tails = 0; max_tail = 0
while off + 4 <= len(data):
    ln = struct.unpack("<I", data[off:off+4])[0]
    off += 4
    pkt = data[off:off+ln]
    off += ln
    tail = 0
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] == 0: tail += 1
        else: break
    if tail >= 4: tails += 1
    if tail > max_tail: max_tail = tail
    fid += 1
print(f"music,{sys.argv[2]},{fid},{tails},{max_tail}")
PY
done

echo "B.7 done. Results: $RESULTS"
