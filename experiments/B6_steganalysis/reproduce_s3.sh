#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

RESULTS="$SCRIPT_DIR/blind_detection.csv"
echo "sigma,stream_type,z_score" > "$RESULTS"

for sigma in 1.0 1.5 2.0 2.5 3.0 4.0 5.0; do
  for kind in clean stego_N32; do
    for i in $(seq 1 20); do
      bin="$ROOT/logs/phase_b/B6_s2/${kind}_${i}.bin"
      [ -f "$bin" ] || continue
      python3 - "$bin" "$sigma" "$kind" >> "$RESULTS" <<'PY'
import sys, math
sys.path.insert(0, "experiments/B6_steganalysis")
from detectors import load_packets, trailing_zeros

packets = load_packets(sys.argv[1])
tails = [trailing_zeros(pkt) for pkt in packets]
if len(tails) < 5: 
    print(f"{sys.argv[2]},{sys.argv[3]},0")
    sys.exit(0)
mean = sum(tails) / len(tails)
var = sum((t - mean) ** 2 for t in tails) / len(tails)
std = math.sqrt(var) if var > 0 else 1.0
z = (max(tails) - mean) / std
print(f"{sys.argv[2]},{sys.argv[3]},{z:.4f}")
PY
    done
  done
done

echo "S3 done. Results: $RESULTS"