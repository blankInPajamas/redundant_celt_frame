
#!/usr/bin/env python3

import csv
import sys
from pathlib import Path

sys.path.insert(0, "experiments/B6_steganalysis")

from detectors import load_packets, blind_structural_scan

OUT = Path("logs/phase_b/B6_s2")

SOURCES = [
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    11, 12, 13, 14, 15, 16, 17, 18, 19, 24
]

SIZES = [1, 2, 4, 8, 16, 24, 32]

# Load candidate frame indices for post-hoc evaluation.
# These indices are NOT passed to the detector.

frame_map = {}

with open(OUT / "transition_frames.csv") as f:

    for row in csv.DictReader(f):
        frame_map[int(row["source_id"])] = int(row["target_frame"])


results = []


def evaluate(path, source, payload_size, stream_type):

    packets = load_packets(path)

    # Important: no target_idx is supplied here.
    detection = blind_structural_scan(packets)

    hits = detection["hits"]

    detected_indices = [
        hit["packet_index"] for hit in hits
    ]

    target_idx = frame_map[source]

    target_found = target_idx in detected_indices

    result = {
        "source_id": source,
        "payload_size": payload_size,
        "stream_type": stream_type,
        "predicted_label": detection["label"],
        "hit_count": detection["hit_count"],
        "detected_packet_indices": ";".join(
            str(i) for i in detected_indices
        ),
        "candidate_frame": target_idx,
        "target_packet_found": target_found
    }

    results.append(result)


# 1. Clean streams

print("Evaluating clean streams...")

for source in SOURCES:

    path = OUT / f"clean_{source}.bin"

    evaluate(
        path,
        source,
        0,
        "clean"
    )


# 2. Stego streams

print("\nEvaluating stego streams...")

for n in SIZES:

    for source in SOURCES:

        path = OUT / f"stego_N{n}_{source}.bin"

        evaluate(
            path,
            source,
            n,
            "stego"
        )


# 3. Save results

output = Path(
    "experiments/B6_steganalysis/blind_structural_results.csv"
)

with open(output, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)


# 4. Calculate metrics

clean_rows = [
    r for r in results
    if r["stream_type"] == "clean"
]

print("\n========== BLIND DETECTOR RESULTS ==========")

for n in SIZES:

    stego_rows = [
        r for r in results
        if r["stream_type"] == "stego"
        and r["payload_size"] == n
    ]

    tp = sum(
        r["predicted_label"] == "stego"
        for r in stego_rows
    )

    fn = len(stego_rows) - tp

    fp = sum(
        r["predicted_label"] == "stego"
        for r in clean_rows
    )

    tn = len(clean_rows) - fp

    tpr = tp / (tp + fn) if tp + fn else 0
    fpr = fp / (fp + tn) if fp + tn else 0

    localization = sum(
        r["target_packet_found"]
        for r in stego_rows
    )

    print(f"\nPayload: {n} bytes")
    print(f"TP: {tp} | FN: {fn}")
    print(f"FP: {fp} | TN: {tn}")
    print(f"TPR: {tpr * 100:.2f}%")
    print(f"FPR: {fpr * 100:.2f}%")
    print(f"Correct packet localization: {localization}/20")

print("\nTotal records:", len(results))
print("Saved:", output)
