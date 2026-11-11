#!/usr/bin/env bash

set -uo pipefail

ROOT="$HOME/research/redundant_celt_frame_steganography"

cd "$ROOT" || exit 1

STAMP=$(date +%Y%m%d_%H%M%S)

OUT="$ROOT/experiments/finalization/inventory_$STAMP"

mkdir -p "$OUT"

REPORT="$OUT/finalization_inventory.txt"

exec > >(tee "$REPORT") 2>&1

echo "========== FINALIZATION INVENTORY =========="
echo "Project: $ROOT"
echo "Inventory: $OUT"
echo

echo "========== B16 PREFLIGHT =========="

B16="$ROOT/experiments/B9_common_voice/results/b16_cross_version_transfer/preflight_20261105_161055"

if [ -d "$B16" ]; then
    cat "$B16/b16_preflight_report.txt"
else
    echo "B16 preflight directory not found."
fi

echo
echo "========== SOURCE SCRIPT INVENTORY =========="

FILES=(
    "experiments/B9_common_voice/run_b12_full.py"
    "experiments/B9_common_voice/run_b13_steganalysis.py"
    "experiments/B9_common_voice/run_b14_feature_attribution.py"
    "experiments/B9_common_voice/preflight_b16.py"
    "experiments/B6_steganalysis/detectors.py"
    "experiments/B7_music/results/b15_natural_cover_audit/run_20261104_132107/b15_run.py"
)

for FILE in "${FILES[@]}"; do

    echo
    echo "FILE: $FILE"

    if [ -f "$ROOT/$FILE" ]; then

        sha256sum "$ROOT/$FILE"

        echo "--- Functions, classes and important constants ---"

        grep -nE \
        '^(def |class )|MAX_PAYLOAD|TAIL_SIZE|CAPACITY|ArgumentParser|add_argument|extract_features|StratifiedGroupKFold' \
        "$ROOT/$FILE" || true

    else
        echo "NOT FOUND"
    fi

done

echo
echo "========== EXISTING B16-B19 SCRIPTS =========="

find "$ROOT/experiments" \
    -type f \
    \( -iname '*b16*.py' -o \
       -iname '*b17*.py' -o \
       -iname '*b18*.py' -o \
       -iname '*b19*.py' \) \
    -print

echo
echo "========== LEGACY EXPERIMENT INVENTORY =========="

find "$ROOT/experiments" \
    -maxdepth 5 \
    -type f \
    \( -iname '*b6*.py' -o \
       -iname '*b7*.py' -o \
       -iname '*b8*.py' -o \
       -iname '*audit*.py' \) \
    -print

echo
echo "========== EXISTING CHECKSUM FILES =========="

find "$ROOT/experiments" \
    -type f \
    -name '*checksums*.sha256' \
    -print

echo
echo "========== PYTHON PACKAGE VERSIONS =========="

python - <<'PY'
import numpy
import pandas
import sklearn
import scipy
import matplotlib

print("NumPy:", numpy.__version__)
print("Pandas:", pandas.__version__)
print("Scikit-learn:", sklearn.__version__)
print("SciPy:", scipy.__version__)
print("Matplotlib:", matplotlib.__version__)
PY

echo
echo "========== INVENTORY COMPLETE =========="
echo "Report: $REPORT"

