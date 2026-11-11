#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

RESULTS="$SCRIPT_DIR/blind_detection.csv"
echo "stream_type,z_score" > "$RESULTS"

for kind in clean stego_N32; do
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 24; do
    bin="$ROOT/logs/phase_b/B6_s2/${kind}_${i}.bin"
    [ -f "$bin" ] || continue
    python3 - "$bin" "$kind" >> "$RESULTS" <<'PY'
import sys
sys.path.insert(0, "experiments/B6_steganalysis")
from detectors import load_packets, detector_blind_tail_outlier
packets = load_packets(sys.argv[1])
_, z = detector_blind_tail_outlier(packets, sigma=3.0)
print(f"{sys.argv[2]},{z:.4f}")
PY
  done
done

echo "S3 done. Results: $RESULTS ($(wc -l < "$RESULTS") lines)"