#!/usr/bin/env python3
"""Analyze B.0 results: classify each byte of frame 3."""
import csv, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CSV = ROOT / "logs/phase_b/B0/results.csv"

rows = list(csv.DictReader(open(CSV)))

inert = []
structural = []
content = []

for r in rows:
    off = int(r["byte_offset"])
    rc = int(r["decode_rc"])
    ident = r["identical_to_baseline"]
    if rc != 0:
        structural.append(off)
    elif ident == "yes":
        inert.append(off)
    else:
        content.append(off)

print(f"structural (decode fails): {len(structural)} bytes: {structural}")
print(f"inert (decode succeeds, PCM unchanged): {len(inert)} bytes: {inert}")
print(f"content (decode succeeds, PCM changed): {len(content)} bytes: {content}")
print()
print(f"Covert channel capacity: {len(inert)} bytes = {len(inert)*8} bits per transition")

# Verify contiguity of inert region
if inert:
    expected = list(range(min(inert), max(inert)+1))
    if inert == expected:
        print(f"Inert region is contiguous: [{min(inert)}, {max(inert)}]")
    else:
        print(f"Inert region is NOT contiguous; gaps: {set(expected) - set(inert)}")