#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B2"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/results.csv"

echo "application,bitrate,frames,tail_frames,max_tail" > "$RESULTS"

for app in voip audio lowdelay; do
  for br in 16000 20000 24000 28000 32000 40000 48000 64000; do
    bin="$OUT/${app}_${br}.bin"
    log="$OUT/${app}_${br}.log"

    LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
      data/pcm/spontaneous-speech-en-1.pcm "$bin" "$app" "$br" 2> "$log"

    python3 - "$bin" "$app" "$br" >> "$RESULTS" <<'PY'
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
print(f"{sys.argv[2]},{sys.argv[3]},{fid},{tails},{max_tail}")
PY
  done
done

echo "B.2 done. Results: $RESULTS"