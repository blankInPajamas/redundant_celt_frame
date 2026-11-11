#!/usr/bin/env python3

import csv
import sys
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

OUT = ROOT / "logs/phase_b/B7_official_20261103_020241"
TEST = OUT / "b7_zero_tail_payload_test"

sys.path.insert(0, str(ROOT / "experiments/B6_steganalysis"))

from detectors import load_packets, blind_structural_scan

MAX_PAYLOAD = 35

results = []

with (OUT / "summary.csv").open(newline="") as f:
    summary = list(csv.DictReader(f))

with (TEST / "results.csv").open(newline="") as f:
    positive_cases = list(csv.DictReader(f))


def scan(path):

    packets = load_packets(path)

    result = blind_structural_scan(
        packets,
        tail_size=36,
        max_payload=MAX_PAYLOAD
    )

    return packets, result


# ==========================================
# PART A: NATURAL CLEAN MUSIC CORPUS
# ==========================================

print("Scanning natural clean music corpus...")

for row in summary:

    version = row["version"]
    recording = row["id"]

    path = OUT / row["bitstream"]

    if not path.is_file():
        raise FileNotFoundError(path)

    packets, detection = scan(path)

    indices = [
        h["packet_index"]
        for h in detection["hits"]
    ]

    results.append({
        "version": version,
        "recording": recording,
        "stream_type": "natural_clean",
        "hit_count": detection["hit_count"],
        "detected_indices": ";".join(map(str, indices)),
        "target_found": ""
    })


# ==========================================
# PART B: B7 PAYLOAD-BEARING STREAMS
# ==========================================

print("Scanning B7 payload-bearing streams...")

for row in positive_cases:

    version = row["version"]
    recording = row["id"]
    frame = int(row["frame"])

    path = (
        TEST / "stego" / version /
        f"{recording}_f{frame}.bin"
    )

    if not path.is_file():
        raise FileNotFoundError(path)

    packets, detection = scan(path)

    indices = [
        h["packet_index"]
        for h in detection["hits"]
    ]

    target_found = frame in indices

    results.append({
        "version": version,
        "recording": recording,
        "stream_type": "b7_stego",
        "hit_count": detection["hit_count"],
        "detected_indices": ";".join(map(str, indices)),
        "target_found": target_found
    })


# ==========================================
# PART C: SAVE RESULTS
# ==========================================

output = TEST / "natural_music_detector_audit.csv"

with output.open("w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(results[0].keys())
    )

    writer.writeheader()
    writer.writerows(results)


# ==========================================
# PART D: SUMMARY
# ==========================================

print("\n========== NATURAL MUSIC DETECTOR AUDIT ==========")

clean_rows = [
    r for r in results
    if r["stream_type"] == "natural_clean"
]

stego_rows = [
    r for r in results
    if r["stream_type"] == "b7_stego"
]

print("Natural clean streams:", len(clean_rows))
print("Payload-bearing streams:", len(stego_rows))

for version in ("1.5.2", "1.6.1"):

    clean = [
        r for r in clean_rows
        if r["version"] == version
    ]

    stego = [
        r for r in stego_rows
        if r["version"] == version
    ]

    fp = sum(r["hit_count"] > 0 for r in clean)
    tp = sum(r["hit_count"] > 0 for r in stego)

    localized = sum(
        r["target_found"] is True
        for r in stego
    )

    print(f"\nOPUS {version}")

    print(
        f"Natural clean false positives: "
        f"{fp}/{len(clean)}"
    )

    print(
        f"B7 payload detections: "
        f"{tp}/{len(stego)}"
    )

    print(
        f"Correct target localization: "
        f"{localized}/{len(stego)}"
    )


# Count unique natural recordings flagged
unique_clean = {}

for row in clean_rows:

    key = row["recording"]

    unique_clean[key] = (
        unique_clean.get(key, False)
        or row["hit_count"] > 0
    )

print("\n========== UNIQUE RECORDING SUMMARY ==========")

print("Unique natural recordings:", len(unique_clean))

print(
    "Unique recordings flagged:",
    sum(unique_clean.values()),
    "/", len(unique_clean)
)

print("\nSaved:", output)

