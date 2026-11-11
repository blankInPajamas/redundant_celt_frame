#!/usr/bin/env python3
"""Compute TPR/FPR for each detector and payload size."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(open("experiments/B6_steganalysis/detection_accuracy.csv")))

# Group by (detector, payload_size, stream_type)
stats = defaultdict(lambda: {"stego": 0, "stego_ok": 0, "clean": 0, "clean_ok": 0})

for r in rows:
    key = (r["detector"], int(r["payload_size"]))
    is_stego = r["stream_type"] == "stego"
    detected = r["label"] == "stego"
    if is_stego:
        stats[key]["stego"] += 1
        if detected:
            stats[key]["stego_ok"] += 1
    else:
        stats[key]["clean"] += 1
        if not detected:
            stats[key]["clean_ok"] += 1

print(f"{'detector':25s} {'payload':>8s} {'TPR':>8s} {'FPR':>8s}")
for (detector, psize), s in sorted(stats.items()):
    tpr = s["stego_ok"] / s["stego"] if s["stego"] else 0
    fpr = 1 - (s["clean_ok"] / s["clean"]) if s["clean"] else 0
    print(f"{detector:25s} {psize:>8d} {tpr:>8.2f} {fpr:>8.2f}")