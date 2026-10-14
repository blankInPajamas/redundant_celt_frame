#!/usr/bin/env python3
"""Analyze B0 results: classify each byte of frame 3."""
import csv, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CSV = ROOT / "experiments/B0_decisive/results.csv"

if not CSV.exists():
    print(f"no results at {CSV}")
    raise SystemExit(1)

rows = list(csv.DictReader(open(CSV)))

structural, inert, content = [], [], []

# Baseline PCM size (from a clean decode). We compare each modified decode's
# size to this to distinguish "content changed" from "decoder truncated."
# If the analyzer doesn't have the baseline, we infer it from the majority.
BASELINE_SIZE = 963840  # observed in B0 for speech-en-1.pcm at 32kbps

for r in rows:
    off = int(r["byte_offset"])
    rc = int(r["decode_rc"])
    ident = r["identical_to_baseline"]
    pcm_size = int(r.get("pcm_size", 0)) if "pcm_size" in r else None

    # Structural: decode failed, OR decoder produced truncated PCM
    if rc != 0:
        structural.append(off)
        continue
    if pcm_size is not None and pcm_size != BASELINE_SIZE:
        structural.append(off)
        continue

    if ident == "yes":
        inert.append(off)
    else:
        content.append(off)

print(f"structural (decode fails or truncated): {len(structural)} bytes: {structural}")
print(f"content (decode succeeds, PCM changed): {len(content)} bytes: {content}")
print(f"inert (decode succeeds, PCM unchanged): {len(inert)} bytes: {len(inert)}")

if inert:
    print()
    print(f"inert region: {inert}")
    print(f"channel capacity (all inert): {len(inert)} bytes = {len(inert)*8} bits")

    # Contiguous tail
    tail_start = None
    for i in range(len(inert)):
        if inert[i] == 48:
            tail_start = 48
            break
    if tail_start is not None:
        contiguous = [b for b in inert if b >= tail_start]
        print(f"contiguous tail at [{tail_start}, 83]: {len(contiguous)} bytes = {len(contiguous)*8} bits")
