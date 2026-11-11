#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$HOME/research/redundant_celt_frame_steganography"
OUT="${1:?Output directory required}"

B7="$ROOT/logs/phase_b/B7_official_20261103_020241"
B15="$ROOT/experiments/B7_music/results/b15_natural_cover_audit/run_20261104_132107"
B16="$ROOT/experiments/B9_common_voice/results/b16_cross_version_transfer/run_20261105_163028"
B12="$ROOT/experiments/B9_common_voice/results/b12_payload_reliability/run_20261104_020705"
B14="$ROOT/experiments/B9_common_voice/results/b14_feature_attribution/run_20261104_110548"

B14_SCRIPT="$ROOT/experiments/B9_common_voice/run_b14_feature_attribution.py"
GTZAN="$ROOT/experiments/B7_music/gtzan_valid_manifest.csv"

mkdir -p "$OUT"

echo "========== B17 SAFE PREFLIGHT =========="
echo "Started: $(date)"
echo "Project: $ROOT"
echo "Output: $OUT"

require_file() {
    if [[ ! -s "$1" ]]; then
        echo "ERROR: Missing file: $1"
        exit 1
    fi
}

for f in \
    "$B14_SCRIPT" \
    "$B14/b14_run_config.json" \
    "$B12/b12_payload_manifest.csv" \
    "$B16/b16_run_config.json" \
    "$B16/b16_transfer_metrics.csv" \
    "$B16/b16_transfer_predictions.csv" \
    "$B15/b15_recording_results.csv" \
    "$B15/b15_positive_control_audit.csv" \
    "$B15/b15_version_summary.csv" \
    "$B15/b15_cross_version_agreement.csv" \
    "$B15/b15_input_bitstream_hashes.csv" \
    "$GTZAN"
do
    require_file "$f"
done

echo
echo "========== B14 SOURCE VALIDATION =========="

EXPECTED="4205c3d6864dea29653ec304bd8387680e01a82ae67917a0c0640a9765e756db"

ACTUAL=$(sha256sum -- "$B14_SCRIPT")
ACTUAL="${ACTUAL%% *}"

echo "Expected: $EXPECTED"
echo "Actual:   $ACTUAL"

[[ "$ACTUAL" == "$EXPECTED" ]] || {
    echo "ERROR: B14 script hash mismatch"
    exit 1
}

echo "B14 SOURCE: PASS"

echo
echo "========== CHECKSUM AUDITS =========="

verify_checksums() {
    local directory="$1"
    local file="$2"

    echo "--- $directory"

    if [[ -f "$directory/$file" ]]; then
        (cd "$directory" && sha256sum -c "$file") || {
            echo "ERROR: Checksum failure in $directory"
            exit 1
        }
    else
        echo "ERROR: Missing checksum file: $file"
        exit 1
    fi
}

verify_checksums "$B12" "b12_checksums.sha256"
verify_checksums "$B14" "b14_checksums.sha256"
verify_checksums "$B15" "b15_checksums.sha256"
verify_checksums "$B16" "b16_checksums.sha256"

echo
echo "========== B7 MUSIC INVENTORY =========="

find "$B7" -maxdepth 4 -type f -print |
    LC_ALL=C sort > "$OUT/b17_b7_file_inventory.txt"

echo "Total B7 files: $(wc -l < "$OUT/b17_b7_file_inventory.txt")"
echo "First 20 inventory entries:"
sed -n '1,20p' "$OUT/b17_b7_file_inventory.txt"

echo
echo "========== B14 CONFIG INVENTORY =========="

find "$ROOT" -type f \
    \( -iname '*b14*.json' -o -iname '*b14*config*' \) \
    -print | LC_ALL=C sort > "$OUT/b17_b14_config_inventory.txt"

echo "Config files: $(wc -l < "$OUT/b17_b14_config_inventory.txt")"
sed -n '1,30p' "$OUT/b17_b14_config_inventory.txt"

echo
echo "========== RECOMPUTING EXPERIMENT COUNTS =========="

python3 - "$B12" "$B14" "$B15" "$B16" "$B7" "$GTZAN" <<'PY'
import csv
import json
import hashlib
import sys
from pathlib import Path
from collections import Counter

B12, B14, B15, B16, B7, GTZAN = map(Path, sys.argv[1:])

errors = []

def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames, rows

def check_csv(label, path, expected=None):
    if not path.is_file():
        errors.append(f"Missing {label}: {path}")
        return []

    fields, rows = read_csv(path)
    print(f"{label}: {len(rows)} rows")

    if expected is not None and len(rows) != expected:
        errors.append(
            f"{label}: expected {expected}, found {len(rows)}"
        )

    print("Columns:", fields)
    return rows

checks = [
    ("GTZAN manifest", GTZAN, 999),
    ("B12 payload manifest", B12 / "b12_payload_manifest.csv", 3600),
    ("B14 feature metrics", B14 / "b14_feature_group_metrics.csv", 252),
    ("B16 transfer metrics", B16 / "b16_transfer_metrics.csv", 264),
    ("B16 transfer predictions", B16 / "b16_transfer_predictions.csv", 50688),
    ("B15 recording results", B15 / "b15_recording_results.csv", 2018),
    ("B15 positive controls", B15 / "b15_positive_control_audit.csv", 20),
    ("B15 version summary", B15 / "b15_version_summary.csv", 2),
    ("B15 cross-version agreement", B15 / "b15_cross_version_agreement.csv", 2),
    ("B15 input hashes", B15 / "b15_input_bitstream_hashes.csv", 2018),
]

for label, path, expected in checks:
    check_csv(label, path, expected)

print("\n========== B7 BITSTREAM COUNTS ==========")

for version in ("1.5.2", "1.6.1"):
    directory = B7 / version / "bitstreams"
    count = (
        sum(1 for p in directory.glob("*.bin"))
        if directory.is_dir() else 0
    )
    print(f"{version}: {count} bitstreams")

    if count == 0:
        errors.append(f"No B7 bitstreams found for {version}")

print("\n========== B15 POSITIVE-CONTROL DISTRIBUTION ==========")

fields, controls = read_csv(
    B15 / "b15_positive_control_audit.csv"
)

print("Columns:", fields)

if "version" in fields:
    print("By encoder:", dict(Counter(r["version"] for r in controls)))

print("\n========== B15 RECORDING DISTRIBUTION ==========")

fields, recordings = read_csv(
    B15 / "b15_recording_results.csv"
)

for key in ("version", "class"):
    if key in fields:
        print(key, dict(Counter(r[key] for r in recordings)))

print("\n========== B16 CONFIGURATION ==========")

with (B16 / "b16_run_config.json").open() as f:
    config = json.load(f)

for key in (
    "payload_sizes_bytes",
    "shared_speakers_excluded",
    "shared_recordings_excluded",
    "retained_events",
    "bootstrap_repetitions",
    "training_testing",
):
    print(f"{key}: {config.get(key)}")

print("\n========== CROSS-EXPERIMENT HASH MATCHES ==========")

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

comparisons = [
    ("B12 manifest", B12 / "b12_payload_manifest.csv", "b12_manifest_sha256"),
    ("B14 script", B14.parent.parent / "run_b14_feature_attribution.py", "b14_script_sha256"),
    ("B14 config", B14 / "b14_run_config.json", "b14_config_sha256"),
]

for label, path, key in comparisons:
    actual = sha(path)
    expected = config.get(key)
    passed = actual == expected
    print(f"{label}: {'PASS' if passed else 'FAIL'}")
    print("SHA256:", actual)

    if not passed:
        errors.append(f"{label} does not match B16 configuration")

print("\n========== PREFLIGHT VALIDATION ==========")

if errors:
    print("ERRORS:")
    for error in errors:
        print("-", error)
    print("B17 PREFLIGHT: FAIL")
    sys.exit(1)

print("All required files and expected counts validated.")
print("B17 PREFLIGHT: PASS")

print(
    "\nDESIGN NOTE: B15 contains only 10 positive controls per encoder. "
    "This is suitable for an exploratory transfer check, not a "
    "high-confidence independent machine-learning evaluation."
)
PY

echo
echo "========== B17 PREFLIGHT COMPLETE =========="
echo "Finished: $(date)"
echo "Source bitstreams modified: NO"
echo "Output: $OUT"

