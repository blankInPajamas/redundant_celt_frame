#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B3"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/results.csv"

echo "bitrate,frame_size,tail_bytes,ratio" > "$RESULTS"

for br in 20000 24000 28000 32000 40000; do
  bin="$OUT/audio_${br}.bin"
  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
    data/pcm/spontaneous-speech-en-1.pcm "$bin" audio "$br" 2> /dev/null

  python3 - "$bin" "$br" >> "$RESULTS" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
off = 0; best = (0,0)  # (frame_size, tail)
while off + 4 <= len(data):
    ln = struct.unpack("<I", data[off:off+4])[0]
    off += 4
    pkt = data[off:off+ln]
    off += ln
    tail = 0
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] == 0: tail += 1
        else: break
    if tail > best[1]:
        best = (ln, tail)
ratio = best[1] / best[0] if best[0] else 0
print(f"{sys.argv[2]},{best[0]},{best[1]},{ratio:.3f}")
PY
done

echo "B.3 done. Results: $RESULTS"