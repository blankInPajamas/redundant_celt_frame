
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B6_s2"
mkdir -p "$OUT"

RESULTS="$SCRIPT_DIR/detection_accuracy.csv"
FRAME_RESULTS="$OUT/transition_frames.csv"

echo "payload_size,stream_type,detector,label,score,target_frame" > "$RESULTS"
echo "source_id,target_frame" > "$FRAME_RESULTS"

SKIPPED=0
TOTAL=0
EMBEDDED=0

VALID_FILES=()
declare -A TARGET_IDX=()

# --- 1. Generate clean streams and identify transition frames ---

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 24; do

    pcm="data/pcm/spontaneous-speech-en-${i}.pcm"
    clean="$OUT/clean_${i}.bin"

    TOTAL=$((TOTAL + 1))

    if [[ ! -f "$pcm" ]]; then
        echo "SKIP: Missing PCM file $i" >&2
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Encode clean stream
    if ! LD_LIBRARY_PATH="$ROOT/opus/.libs" scripts/encode_raw \
        "$pcm" "$clean" audio 32000 \
        2> "$OUT/encode_clean_${i}.log"; then

        echo "SKIP: Encoding failed for recording $i" >&2
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Identify transition-frame candidates
    candidate_info=$(python3 - "$clean" <<'PY'
import sys

sys.path.insert(0, "experiments/B6_steganalysis")

from detectors import load_packets, trailing_zeros

packets = load_packets(sys.argv[1])

candidates = [
    i for i, pkt in enumerate(packets)
    if trailing_zeros(pkt) >= 20
]

target_idx = candidates[0] if len(candidates) == 1 else -1

print(f"{len(candidates)}\t{target_idx}")
PY
    )

    IFS=$'\t' read -r candidate_count target_idx <<< "$candidate_info"

    # Require exactly one candidate
    if [[ "$candidate_count" -ne 1 ]]; then

        echo "SKIP: Recording $i has $candidate_count transition candidates" >&2

        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    VALID_FILES+=("$i")
    TARGET_IDX["$i"]="$target_idx"

    echo "$i,$target_idx" >> "$FRAME_RESULTS"

    echo "VALID: Recording $i -> transition frame $target_idx"

done

echo
echo "Valid recordings: ${#VALID_FILES[@]} / $TOTAL"
echo "Skipped recordings: $SKIPPED"

if [[ ${#VALID_FILES[@]} -eq 0 ]]; then
    echo "ERROR: No valid transition frames found."
    exit 1
fi


# --- 2. Generate stego streams for valid files ---

for N in 1 2 4 8 16 24 32; do

    MSG=$(python3 -c "print('A' * $N)")

    echo
    echo "Generating payload size: $N bytes"

    for i in "${VALID_FILES[@]}"; do

        clean="$OUT/clean_${i}.bin"
        stego="$OUT/stego_N${N}_${i}.bin"

        target_idx="${TARGET_IDX[$i]}"

        # Embed using the verified transition-frame index
        if python3 "$ROOT/experiments/B4_payload/embed.py" \
            "$clean" "$stego" "$MSG" "$target_idx" \
            > "$OUT/embed_N${N}_${i}.log" 2>&1; then

            EMBEDDED=$((EMBEDDED + 1))

            echo "  OK: N=$N recording=$i frame=$target_idx"

        else

            echo "  FAILED: N=$N recording=$i" >&2

            cat "$OUT/embed_N${N}_${i}.log" >&2

            rm -f "$stego"

        fi

    done

done


# --- 3. Run known-location detectors ---

run_detectors() {

    local bin="$1"
    local psize="$2"
    local kind="$3"
    local target_idx="$4"

    if [[ ! -s "$bin" ]]; then
        echo "WARNING: Missing stream $bin" >&2
        return 0
    fi

    python3 - "$bin" "$psize" "$kind" "$target_idx" >> "$RESULTS" <<'PY'

import sys

sys.path.insert(0, "experiments/B6_steganalysis")

from detectors import load_packets, run_known_detectors

bin_path = sys.argv[1]
payload_size = sys.argv[2]
stream_type = sys.argv[3]
target_idx = int(sys.argv[4])

packets = load_packets(bin_path)

results = run_known_detectors(packets, target_idx)

for name, (label, score) in results.items():

    print(
        f"{payload_size},"
        f"{stream_type},"
        f"{name},"
        f"{label},"
        f"{float(score):.6f},"
        f"{target_idx}"
    )

PY

}


# --- 4. Evaluate clean streams ---

echo
echo "Running detectors on clean streams..."

for i in "${VALID_FILES[@]}"; do

    target_idx="${TARGET_IDX[$i]}"

    run_detectors \
        "$OUT/clean_${i}.bin" \
        0 \
        clean \
        "$target_idx"

done


# --- 5. Evaluate stego streams ---

echo
echo "Running detectors on stego streams..."

for N in 1 2 4 8 16 24 32; do

    for i in "${VALID_FILES[@]}"; do

        target_idx="${TARGET_IDX[$i]}"

        run_detectors \
            "$OUT/stego_N${N}_${i}.bin" \
            "$N" \
            stego \
            "$target_idx"

    done

done


# --- 6. Final summary ---

echo
echo "======================================"
echo "B6 S2 EXPERIMENT COMPLETED"
echo "======================================"

echo "Total recordings: $TOTAL"
echo "Valid recordings: ${#VALID_FILES[@]}"
echo "Skipped recordings: $SKIPPED"
echo "Successful embeddings: $EMBEDDED"

echo
echo "Detection results:"
echo "$RESULTS"

echo
echo "Transition-frame records:"
echo "$FRAME_RESULTS"

echo
echo "CSV rows: $(wc -l < "$RESULTS")"

echo "======================================"
