#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B6_s2"
mkdir -p "$OUT"
RESULTS="$SCRIPT_DIR/detection_accuracy.csv"
echo "payload_size,stream_type,detector,label,score" > "$RESULTS"

SKIPPED=0
TOTAL=0

# --- 1. Generate clean streams and check for transitions ---
VALID_FILES=()
for i in $(seq 1 20); do
  pcm="data/pcm/spontaneous-speech-en-${i}.pcm"
  [ -f "$pcm" ] || continue
  clean="$OUT/clean_${i}.bin"

  LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
    "$pcm" "$clean" audio 32000 2> /dev/null

  # Does this stream have a transition frame?
  has_transition=$(python3 - "$clean" <<'PY'
import sys
sys.path.insert(0, "experiments/B6_steganalysis")
from detectors import load_packets, trailing_zeros
packets = load_packets(sys.argv[1])
print(1 if any(trailing_zeros(p) >= 20 for p in packets) else 0)
PY
  )

  if [ "$has_transition" -eq 1 ]; then
    VALID_FILES+=("$i")
  else
    echo "  skip: ${i} (no transition frame)" | tee -a "$RESULTS"
    SKIPPED=$((SKIPPED + 1))
  fi
  TOTAL=$((TOTAL + 1))
done

echo "Valid: ${#VALID_FILES[@]} / $TOTAL (skipped $SKIPPED)"

# --- 2. Generate stego streams for valid files ---
for N in 1 2 4 8 16 24 32; do
  MSG=$(python3 -c "print('A' * $N)")
  for i in "${VALID_FILES[@]}"; do
    clean="$OUT/clean_${i}.bin"
    stego="$OUT/stego_N${N}_${i}.bin"
    python3 "$ROOT/experiments/B4_payload/embed.py" "$clean" "$stego" "$MSG" 2>/dev/null || {
      echo "  embed failed for N=$N i=$i" >&2
      rm -f "$stego"
    }
  done
done

# --- 3. Run detectors ---
run_detectors() {
  local bin="$1"
  local psize="$2"
  local kind="$3"
  [ -f "$bin" ] || return
  python3 - "$bin" "$psize" "$kind" >> "$RESULTS" <<'PY'
import sys
sys.path.insert(0, "experiments/B6_steganalysis")
from detectors import run_all_detectors
for name, (label, score) in run_all_detectors(sys.argv[1]).items():
    print(f"{sys.argv[2]},{sys.argv[3]},{name},{label},{score:.4f}")
PY
}

for i in "${VALID_FILES[@]}"; do
  run_detectors "$OUT/clean_${i}.bin" 0 clean
done

for N in 1 2 4 8 16 24 32; do
  for i in "${VALID_FILES[@]}"; do
    run_detectors "$OUT/stego_N${N}_${i}.bin" "$N" stego
  done
done

echo "S2 done. Results: $RESULTS ($(wc -l < "$RESULTS") lines)"