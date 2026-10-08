#!/usr/bin/env python3
"""Analyze S3: TPR/FPR for the blind detector at varying sigma thresholds.

The blind detector computes a z-score from the packet-size distribution
of each stream. A stream is flagged as "stego" if its maximum packet size
exceeds the stream mean by more than sigma standard deviations.

Interpretation:
  TPR(sigma) = fraction of stego streams with z > sigma
  FPR(sigma) = fraction of clean streams with z > sigma

A useful detector has TPR >> FPR for some sigma. A chance-level detector
has TPR ≈ FPR for all sigma.
"""
import csv
from collections import defaultdict

CSV = "experiments/B6_steganalysis/blind_detection.csv"
rows = list(csv.DictReader(open(CSV)))

if not rows:
    print("No rows in blind_detection.csv")
    raise SystemExit(1)

# Collect z-scores by (sigma_used_to_generate, stream_type)
# Note: the CSV has one row per (sigma, stream_type, stream), but z is
# computed once per stream (independent of sigma). The sigma column just
# records what sigma was passed when the z-score was computed. We can
# use any sigma to gather the z-scores since they don't depend on sigma.
zscores = defaultdict(list)
for r in rows:
    kind = r["stream_type"]
    z = float(r["z_score"])
    zscores[kind].append(z)

stego_zs = zscores.get("stego_N32", [])
clean_zs = zscores.get("clean", [])

if not stego_zs or not clean_zs:
    # Fall back to any key that matches the pattern
    stego_zs = [v for k, vs in zscores.items() if "stego" in k for v in vs]
    clean_zs = [v for k, vs in zscores.items() if k == "clean" for v in vs]

print(f"Loaded {len(stego_zs)} stego streams and {len(clean_zs)} clean streams")
print()
print(f"{'sigma':>6} {'TPR':>8} {'FPR':>8} {'TPR-FPR':>10}")
print("-" * 40)

best = None
for sigma in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
    tpr = sum(1 for z in stego_zs if z > sigma) / len(stego_zs)
    fpr = sum(1 for z in clean_zs if z > sigma) / len(clean_zs)
    gap = tpr - fpr
    print(f"{sigma:>6.1f} {tpr:>8.2f} {fpr:>8.2f} {gap:>10.2f}")
    if best is None or gap > best[3]:
        best = (sigma, tpr, fpr, gap)

print()
print(f"Best separation: sigma={best[0]:.1f}, TPR={best[1]:.2f}, FPR={best[2]:.2f}, gap={best[3]:.2f}")

# Diagnostic: distribution of z-scores
import statistics
print()
print("Z-score distributions:")
print(f"  clean:  mean={statistics.mean(clean_zs):.2f}, "
      f"median={statistics.median(clean_zs):.2f}, "
      f"min={min(clean_zs):.2f}, max={max(clean_zs):.2f}")
print(f"  stego:  mean={statistics.mean(stego_zs):.2f}, "
      f"median={statistics.median(stego_zs):.2f}, "
      f"min={min(stego_zs):.2f}, max={max(stego_zs):.2f}")