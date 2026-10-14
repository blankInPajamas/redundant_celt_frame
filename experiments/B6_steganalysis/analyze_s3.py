#!/usr/bin/env python3
"""Analyze S3: extended ROC over a wide sigma range."""
import csv
from collections import defaultdict
import statistics

CSV = "experiments/B6_steganalysis/blind_detection.csv"
rows = list(csv.DictReader(open(CSV)))

if not rows:
    print("No rows in blind_detection.csv")
    raise SystemExit(1)

zscores = defaultdict(list)
for r in rows:
    kind = r["stream_type"]
    z = float(r["z_score"])
    zscores[kind].append(z)

stego_zs = zscores.get("stego_N32", [])
clean_zs = zscores.get("clean", [])

# Fallback
if not stego_zs:
    stego_zs = [v for k, vs in zscores.items() if "stego" in k for v in vs]
if not clean_zs:
    clean_zs = [v for k, vs in zscores.items() if k == "clean" for v in vs]

# Deduplicate: if the same z appears multiple times (repeated for each sigma),
# collapse to unique values
stego_zs = sorted(set(stego_zs))
clean_zs = sorted(set(clean_zs))

print(f"Loaded {len(stego_zs)} unique stego z-scores and {len(clean_zs)} unique clean z-scores")
print()

# Extended sigma sweep
sigma_range = [1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 12.0, 14.0, 15.0, 16.0, 17.0,
               18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 28.0, 30.0, 40.0]

print(f"{'sigma':>6} {'TPR':>8} {'FPR':>8} {'TPR-FPR':>10}")
print("-" * 42)

best = (0.0, 0.0, 0.0, -999.0)
for sigma in sigma_range:
    tpr = sum(1 for z in stego_zs if z > sigma) / len(stego_zs)
    fpr = sum(1 for z in clean_zs if z > sigma) / len(clean_zs)
    gap = tpr - fpr
    if gap > best[3]:
        best = (sigma, tpr, fpr, gap)
    print(f"{sigma:>6.1f} {tpr:>8.2f} {fpr:>8.2f} {gap:>10.2f}")

print()
if best[3] <= 0.0:
    print(f"No separation achieved at any threshold "
          f"(best TPR-FPR = {best[3]:.2f} at sigma={best[0]:.1f})")
else:
    print(f"Best separation: sigma={best[0]:.1f}, TPR={best[1]:.2f}, "
          f"FPR={best[2]:.2f}, gap={best[3]:.2f}")

print()
print("Z-score distributions (unique values):")
print(f"  clean:  mean={statistics.mean(clean_zs):.2f}, "
      f"median={statistics.median(clean_zs):.2f}, "
      f"min={min(clean_zs):.2f}, max={max(clean_zs):.2f}")
print(f"  stego:  mean={statistics.mean(stego_zs):.2f}, "
      f"median={statistics.median(stego_zs):.2f}, "
      f"min={min(stego_zs):.2f}, max={max(stego_zs):.2f}")