
#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/logs/phase_b/B6_s2"
RESULTS="$ROOT/experiments/B6_steganalysis/payload_verification.csv"

echo "source_id,payload_size,recovery_ok,decode_ok,pcm_identical" > "$RESULTS"

SOURCES=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 24)
SIZES=(1 2 4 8 16 24 32)

for i in "${SOURCES[@]}"; do

    CLEAN="$OUT/clean_${i}.bin"
    BASELINE_PCM="$OUT/clean_${i}.pcm"

    if ! LD_LIBRARY_PATH="$ROOT/opus/.libs" \
        scripts/decode_raw "$CLEAN" "$BASELINE_PCM" 2>/dev/null; then
        echo "ERROR: Clean decoding failed for $i" >&2
        continue
    fi

    for N in "${SIZES[@]}"; do

        STEGO="$OUT/stego_N${N}_${i}.bin"
        STEGO_PCM="$OUT/stego_N${N}_${i}.pcm"

        if [[ ! -f "$STEGO" ]]; then
            echo "$i,$N,no,no,no" >> "$RESULTS"
            continue
        fi

        EXPECTED="$(python3 -c "print('A' * $N)")"

        RECOVERED="$(python3 experiments/B4_payload/extract.py "$STEGO" 36 2>/dev/null)"

        if [[ "$RECOVERED" == "$EXPECTED" ]]; then
            RECOVERY=yes
        else
            RECOVERY=no
        fi

        if LD_LIBRARY_PATH="$ROOT/opus/.libs" \
            scripts/decode_raw "$STEGO" "$STEGO_PCM" 2>/dev/null; then
            DECODE=yes
        else
            DECODE=no
        fi

        if [[ "$DECODE" == "yes" ]] && \
            cmp -s "$BASELINE_PCM" "$STEGO_PCM"; then
            IDENTICAL=yes
        else
            IDENTICAL=no
        fi

        echo "$i,$N,$RECOVERY,$DECODE,$IDENTICAL" >> "$RESULTS"

        echo "Source $i | Payload $N | Recovery=$RECOVERY | Decode=$DECODE | PCM=$IDENTICAL"

    done
done

echo
echo "Verification completed."
echo "Results: $RESULTS"

python3 - "$RESULTS" <<'PY'
import csv
import sys

rows = list(csv.DictReader(open(sys.argv[1])))

print("\n=== SUMMARY ===")
print("Total:", len(rows))
print("Recovery:", sum(r["recovery_ok"] == "yes" for r in rows))
print("Decode:", sum(r["decode_ok"] == "yes" for r in rows))
print("Identical PCM:", sum(r["pcm_identical"] == "yes" for r in rows))
PY
