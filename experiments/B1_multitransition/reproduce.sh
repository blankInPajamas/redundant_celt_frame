#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B1"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/results.csv"

echo "test,silence_ms,tail_frames" > "$RESULTS"

# --- Test 1: naive multi-transition ---
python3 - <<'PY'
import struct

def read_pcm(path, max_samples=None):
    with open(path, "rb") as f:
        data = f.read()
    samples = list(struct.unpack("<" + "h"*(len(data)//2), data))
    if max_samples:
        samples = samples[:max_samples]
    return samples

def write_pcm(path, samples):
    with open(path, "wb") as f:
        f.write(struct.pack("<" + "h"*len(samples), *samples))

speech  = read_pcm("data/pcm/spontaneous-speech-en-1.pcm", max_samples=96000)
silence = [0] * 48000
out = speech + silence + speech + silence + speech
write_pcm("/tmp/B1_naive.pcm", out)
PY

LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
  /tmp/B1_naive.pcm "$OUT/naive.bin" audio 32000 2> "$OUT/naive.log"

n=$(python3 - "$OUT/naive.bin" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
off = 0; cnt = 0
while off + 4 <= len(data):
    ln = struct.unpack("<I", data[off:off+4])[0]
    off += 4
    pkt = data[off:off+ln]
    off += ln
    tail = 0
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] == 0: tail += 1
        else: break
    if tail >= 4: cnt += 1
print(cnt)
PY
)
echo "naive,-,$n" >> "$RESULTS"

# --- Test 2: silence duration sweep ---
for silence_ms in 20 40 80 160 320; do
  python3 - "$silence_ms" <<'PY'
import struct, sys
ms = int(sys.argv[1])
speech_len = 24000
silence_len = 48 * ms

def read_pcm(path, n):
    with open(path, "rb") as f:
        data = f.read(2*n)
    return list(struct.unpack("<" + "h"*(len(data)//2), data))

def write_pcm(path, s):
    with open(path, "wb") as f:
        f.write(struct.pack("<" + "h"*len(s), *s))

speech = read_pcm("data/pcm/spontaneous-speech-en-1.pcm", speech_len)
silence = [0] * silence_len
out = (speech + silence) * 10
write_pcm(f"/tmp/B1_cycle_{ms}.pcm", out)
PY

  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
    /tmp/B1_cycle_${silence_ms}.pcm "$OUT/cycle_${silence_ms}.bin" audio 32000 2> /dev/null

  n=$(python3 - "$OUT/cycle_${silence_ms}.bin" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
off = 0; cnt = 0
while off + 4 <= len(data):
    ln = struct.unpack("<I", data[off:off+4])[0]
    off += 4
    pkt = data[off:off+ln]
    off += ln
    tail = 0
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] == 0: tail += 1
        else: break
    if tail >= 4: cnt += 1
print(cnt)
PY
)
  echo "silence_${silence_ms}ms,${silence_ms},${n}" >> "$RESULTS"
done

echo "B.1 done. Results: $RESULTS"