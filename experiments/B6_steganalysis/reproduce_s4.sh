# analyze_s4.py
import csv
from collections import defaultdict

rows = list(csv.DictReader(open("experiments/B6_steganalysis/detection_accuracy.csv")))
stats = defaultdict(lambda: {"stego": 0, "stego_ok": 0})

for r in rows:
    if r["stream_type"] != "stego": continue
    key = (r["detector"], int(r["payload_size"]))
    stats[key]["stego"] += 1
    if r["label"] == "stego":
        stats[key]["stego_ok"] += 1

print("Detection threshold (smallest payload with TPR >= 0.9):")
for detector in sorted(set(k[0] for k in stats)):
    for psize in sorted(set(k[1] for k in stats if k[0] == detector)):
        s = stats[(detector, psize)]
        tpr = s["stego_ok"] / s["stego"] if s["stego"] else 0
        if tpr >= 0.9:
            print(f"  {detector:25s} threshold = {psize} bytes")
            break