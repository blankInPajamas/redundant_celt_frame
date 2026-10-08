#!/usr/bin/env python3
"""Analyze S4: smallest payload size detectable with TPR >= 0.9."""
import csv
from collections import defaultdict

CSV = "experiments/B6_steganalysis/detection_accuracy.csv"
rows = list(csv.DictReader(open(CSV)))

stats = defaultdict(lambda: {"n": 0, "detected": 0})
for r in rows:
    if r["stream_type"] != "stego":
        continue
    key = (r["detector"], int(r["payload_size"]))
    stats[key]["n"] += 1
    if r["label"] == "stego":
        stats[key]["detected"] += 1

print("Detection threshold (smallest payload with TPR >= 0.90):")
print(f"{'detector':<25} {'threshold':>12} {'TPR':>8}")
print("-" * 50)

for detector in sorted(set(k[0] for k in stats)):
    found = None
    for psize in sorted(set(k[1] for k in stats if k[0] == detector)):
        s = stats[(detector, psize)]
        tpr = s["detected"] / s["n"] if s["n"] else 0
        if tpr >= 0.90:
            found = (psize, tpr)
            break
    if found:
        print(f"{detector:<25} {found[0]:>12} {found[1]:>8.2f}")
    else:
        print(f"{detector:<25} {'>32':>12} {'—':>8}")