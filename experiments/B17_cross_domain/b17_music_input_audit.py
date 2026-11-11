#!/usr/bin/env python3

import csv
import hashlib
import sys
from pathlib import Path
from collections import Counter

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

B7 = ROOT / "logs/phase_b/B7_official_20261103_020241"

B15 = ROOT / (
    "experiments/B7_music/results/b15_natural_cover_audit/"
    "run_20261104_132107"
)

OUT = ROOT / (
    "experiments/B17_cross_domain/"
    "preflight_20261105_202713"
)

OUT.mkdir(parents=True, exist_ok=True)

REPORT = OUT / "b17_music_input_audit.txt"

def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def truth(value):
    return str(value).strip().lower() in ("true", "1", "yes")

def normalize_class(value):
    value = value.lower()
    if "cover" in value and "stego" not in value:
        return "cover"
    return "positive"

def resolve_file(value):
    p = Path(value).expanduser()

    candidates = [p] if p.is_absolute() else [
        ROOT / p,
        B7 / p,
        B15 / p,
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return None

def main():

    failures = []
    lines = []

    def log(message):
        print(message)
        lines.append(str(message))

    log("========== B17 MUSIC INPUT AUDIT ==========")
    log(f"Project: {ROOT}")
    log(f"B7: {B7}")
    log(f"B15: {B15}")

    recording_file = B15 / "b15_recording_results.csv"
    positive_file = B15 / "b15_positive_control_audit.csv"
    hashes_file = B15 / "b15_input_bitstream_hashes.csv"

    for path in (recording_file, positive_file, hashes_file):
        if not path.is_file():
            failures.append(f"Missing input: {path}")

    if failures:
        raise FileNotFoundError("\n".join(failures))

    recordings = read_csv(recording_file)
    positives = read_csv(positive_file)
    hashes = read_csv(hashes_file)

    log("\n========== INPUT COUNTS ==========")
    log(f"Recording rows: {len(recordings)}")
    log(f"Positive-control rows: {len(positives)}")
    log(f"Input hash rows: {len(hashes)}")

    if len(recordings) != 2018:
        failures.append("Unexpected recording row count")

    if len(positives) != 20:
        failures.append("Unexpected positive-control count")

    if len(hashes) != 2018:
        failures.append("Unexpected input hash count")

    expected_counts = {
        ("1.5.2", "cover"): 999,
        ("1.6.1", "cover"): 999,
        ("1.5.2", "positive"): 10,
        ("1.6.1", "positive"): 10,
    }

    actual_counts = Counter(
        (r["version"], normalize_class(r["class"]))
        for r in recordings
    )

    log("\n========== CLASS DISTRIBUTION ==========")

    for key, expected in expected_counts.items():
        actual = actual_counts[key]
        log(f"{key}: {actual}/{expected}")

        if actual != expected:
            failures.append(f"Count mismatch: {key}")

    hash_map = {}

    for row in hashes:
        key = (
            row["version"],
            normalize_class(row["class"]),
            row["recording"],
        )

        if key in hash_map:
            failures.append(f"Duplicate hash entry: {key}")

        hash_map[key] = row["sha256"]

    log("\n========== BITSTREAM HASH VALIDATION ==========")

    checked = 0
    missing = 0
    mismatched = 0
    path_map = {}

    for i, row in enumerate(recordings, 1):

        version = row["version"]
        recording = row["recording"]
        cls = normalize_class(row["class"])

        key = (version, cls, recording)

        path = resolve_file(row["file"])

        if path is None:
            missing += 1
            failures.append(f"Missing bitstream: {row['file']}")
            continue

        path_map[key] = path

        expected = hash_map.get(key)

        if expected is None:
            failures.append(f"Missing input hash: {key}")
            continue

        actual = sha256(path)

        if actual != expected:
            mismatched += 1
            failures.append(f"SHA256 mismatch: {key}")
            continue

        checked += 1

        if i % 250 == 0:
            log(f"Validated {i}/{len(recordings)} records")

    log(f"Hash matches: {checked}")
    log(f"Missing files: {missing}")
    log(f"Hash mismatches: {mismatched}")

    log("\n========== POSITIVE CONTROL VALIDATION ==========")

    required_flags = [
        "detected_anywhere",
        "payload_recovered",
        "pcm_identical",
        "packet_lengths_preserved",
        "independent_payload_correct",
        "other_packets_unchanged",
        "target_prefix_unchanged",
    ]

    positive_keys = set()

    for row in positives:

        version = row["version"]
        recording = row["recording"]

        key = (version, "positive", recording)
        positive_keys.add(key)

        for flag in required_flags:
            if not truth(row[flag]):
                failures.append(
                    f"Positive-control failure: {key}: {flag}"
                )

        path = resolve_file(row["file"])

        if path is None:
            failures.append(f"Positive file missing: {row['file']}")

        log(
            f"{version} | {recording} | "
            f"detected={row['detected_anywhere']} | "
            f"recovered={row['payload_recovered']} | "
            f"frame={row['expected_frame_from_manifest']}"
        )

    if len(positive_keys) != 20:
        failures.append("Positive-control identities are not unique")

    recording_positive_keys = {
        (
            r["version"],
            "positive",
            r["recording"],
        )
        for r in recordings
        if normalize_class(r["class"]) == "positive"
    }

    if positive_keys != recording_positive_keys:
        failures.append("Positive-control manifest disagreement")

    log("\n========== MATCHED CLEAN CONTROLS ==========")

    cover_keys = {
        (r["version"], r["recording"])
        for r in recordings
        if normalize_class(r["class"]) == "cover"
    }

    matched = 0

    for version, cls, recording in sorted(positive_keys):
        if (version, recording) in cover_keys:
            matched += 1
        else:
            failures.append(
                f"Missing matched clean recording: {version}/{recording}"
            )

    log(f"Matched positive-control recordings: {matched}/20")

    log("\n========== PAYLOAD LENGTH INVENTORY ==========")

    lengths = Counter(
        r.get("hit_payload_lengths", "")
        for r in recordings
        if normalize_class(r["class"]) == "positive"
    )

    for value, count in lengths.items():
        log(f"{value}: {count}")

    log("\n========== FINAL RESULT ==========")

    if failures:
        log(f"B17 MUSIC INPUT AUDIT: FAIL ({len(failures)} issues)")
        for item in failures:
            log(f"ERROR: {item}")
    else:
        log("B17 MUSIC INPUT AUDIT: PASS")
        log("All 2018 input bitstream hashes verified.")
        log("All 20 positive controls validated.")
        log("All positive controls have matched clean recordings.")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    log(f"\nReport saved: {REPORT}")

    if failures:
        sys.exit(1)

if __name__ == "__main__":
    main()
