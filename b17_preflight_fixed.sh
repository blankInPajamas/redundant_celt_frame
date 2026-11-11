#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/research/redundant_celt_frame_steganography"

B7="$ROOT/logs/phase_b/B7_official_20261103_020241"
B15="$ROOT/experiments/B7_music/results/b15_natural_cover_audit/run_20261104_132107"
B16="$ROOT/experiments/B9_common_voice/results/b16_cross_version_transfer/run_20261105_163028"
B12="$ROOT/experiments/B9_common_voice/results/b12_payload_reliability/run_20261104_020705"

EXPECTED_B14_SHA="4205c3d6864dea29653ec304bd8387680e01a82ae67917a0c0640a9765e756db"

echo "========== B17 PREFLIGHT INVENTORY =========="
echo "Project: $ROOT"
echo "Started: $(date)"
echo

echo "========== LOCATING EXACT B14 SCRIPT =========="

B14_SCRIPT=""

while IFS= read -r -d '' candidate; do
    HASH=$(sha256sum -- "$candidate")
    HASH="${HASH%% *}"

    if [[ "$HASH" == "$EXPECTED_B14_SHA" && -z "$B14_SCRIPT" ]]; then
        B14_SCRIPT="$candidate"
    fi
done < <(find "$ROOT" -type f -name '*.py' -print0)

if [[ -n "$B14_SCRIPT" ]]; then
    echo "B14 script: $B14_SCRIPT"
    sha256sum "$B14_SCRIPT"
    wc -l "$B14_SCRIPT"

    echo
    echo "Relevant implementation:"
    grep -nE '^(def |class )|payload|tail|manifest|feature|packet|split|train_test' \
        "$B14_SCRIPT" | sed -n '1,180p' || true
else
    echo "WARNING: Expected B14 script SHA256 not found."
fi

echo
echo "========== B14 CONFIG FILES =========="

find "$ROOT" -type f \
    \( -iname '*b14*.json' -o -iname '*b14*config*' \) \
    -print | head -30

echo
echo "========== B16 CONFIGURATION =========="

if [[ -f "$B16/b16_run_config.json" ]]; then
    cat "$B16/b16_run_config.json"
else
    echo "WARNING: B16 configuration not found."
fi

echo
echo "========== B12 MANIFEST FILES =========="

if [[ -d "$B12" ]]; then
    find "$B12" -maxdepth 4 -type f \
        \( -iname '*manifest*' -o -iname '*config*.json' \) \
        -print
else
    echo "WARNING: B12 run directory not found."
fi

echo
echo "========== B7 MUSIC MANIFEST =========="

MANIFEST="$ROOT/experiments/B7_music/gtzan_valid_manifest.csv"

if [[ -f "$MANIFEST" ]]; then
    head -n 5 "$MANIFEST"
else
    echo "WARNING: B7 manifest not found."
fi

echo
echo "========== B7 MUSIC RESULT HEADERS =========="

for f in \
    "$ROOT/experiments/B7_music/results.csv" \
    "$ROOT/experiments/B7_music/b7_music_results.csv"
do
    if [[ -f "$f" ]]; then
        echo "--- $f"
        head -n 4 "$f"
    else
        echo "Not found: $f"
    fi
done

echo
echo "========== B7 RUN FILE INVENTORY =========="

if [[ -d "$B7" ]]; then
    find "$B7" -maxdepth 4 -type f -print | sort | head -100
else
    echo "WARNING: B7 run directory not found."
fi

echo
echo "========== B15 COMPLETE AUDIT SUMMARY =========="

if [[ -d "$B15" ]]; then
python3 - "$B15" <<'PY'
import csv
import sys
from pathlib import Path
from collections import Counter

root = Path(sys.argv[1])

files = [
    "b15_positive_control_audit.csv",
    "b15_recording_results.csv",
    "b15_version_summary.csv",
    "b15_cross_version_agreement.csv",
]

columns = [
    "version",
    "detected_anywhere",
    "payload_recovered",
    "pcm_identical",
    "packet_lengths_preserved",
    "independent_payload_correct",
    "other_packets_unchanged",
    "target_prefix_unchanged",
]

for name in files:
    path = root / name

    if not path.exists():
        print(f"\nMISSING: {name}")
        continue

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

        print(f"\n{name}: {len(rows)} rows")
        print("Columns:", reader.fieldnames)

        for col in columns:
            if reader.fieldnames and col in reader.fieldnames:
                print(f"{col}: {dict(Counter(r[col] for r in rows))}")
PY
else
    echo "WARNING: B15 directory not found."
fi

echo
echo "========== PREFLIGHT COMPLETE =========="
echo "Finished: $(date)"
echo "Original experiment data was not modified."
