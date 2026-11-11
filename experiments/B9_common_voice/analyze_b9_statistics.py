#!/usr/bin/env python3

import csv
import random
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "results/b9_full_encoding/independent_audit"

def load_csv(name):
    with open(OUT / name, newline="") as f:
        return list(csv.DictReader(f))

recordings = load_csv("b9_full_recording_summary.csv")
paired = load_csv("b9_full_paired_versions.csv")

lookup = {
    (r["version"], r["recording_id"]): r
    for r in recordings
}

speakers = defaultdict(lambda: {
    "n": 0,
    "frames": 0,
    "events15": 0,
    "events16": 0,
    "present15": 0,
    "present16": 0,
    "exact": 0
})

discordance = {
    "both": 0,
    "only_1_5_2": 0,
    "only_1_6_1": 0,
    "neither": 0
}

for p in paired:

    rid = p["recording_id"]
    sid = p["speaker_id"]

    a = lookup[("1.5.2", rid)]
    b = lookup[("1.6.1", rid)]

    assert a["expected_frames"] == b["expected_frames"]

    x = int(a["celt_to_silk_events"])
    y = int(b["celt_to_silk_events"])

    pa = int(x > 0)
    pb = int(y > 0)

    if pa and pb:
        discordance["both"] += 1
    elif pa:
        discordance["only_1_5_2"] += 1
    elif pb:
        discordance["only_1_6_1"] += 1
    else:
        discordance["neither"] += 1

    s = speakers[sid]
    s["n"] += 1
    s["frames"] += int(a["expected_frames"])
    s["events15"] += x
    s["events16"] += y
    s["present15"] += pa
    s["present16"] += pb
    s["exact"] += int(p["exact_cts_signature_match"])

ids = list(speakers)
n = len(ids)
N = sum(s["n"] for s in speakers.values())

def aggregate(sample):

    recs = sum(speakers[k]["n"] for k in sample)
    frames = sum(speakers[k]["frames"] for k in sample)

    e15 = sum(speakers[k]["events15"] for k in sample)
    e16 = sum(speakers[k]["events16"] for k in sample)

    p15 = sum(speakers[k]["present15"] for k in sample)
    p16 = sum(speakers[k]["present16"] for k in sample)

    sp15 = sum(speakers[k]["events15"] > 0 for k in sample)
    sp16 = sum(speakers[k]["events16"] > 0 for k in sample)

    exact = sum(speakers[k]["exact"] for k in sample)

    return {
        "recording_difference_pp": 100 * (p15-p16) / recs,
        "speaker_difference_pp": 100 * (sp15-sp16) / len(sample),
        "event_rate_difference": 1000 * (e15-e16) / frames,
        "exact_agreement_pct": 100 * exact / recs
    }

def percentile(values, p):
    values = sorted(values)
    return values[round((len(values)-1)*p)]

print("========== RECORDING DISCORDANCE ==========")
for k, v in discordance.items():
    print(f"{k}: {v} ({100*v/N:.2f}%)")

print("\n========== SPEAKER PREVALENCE ==========")

for version, key in [
    ("1.5.2", "events15"),
    ("1.6.1", "events16")
]:
    count = sum(s[key] > 0 for s in speakers.values())
    print(
        f"Opus {version}: {count}/{n} speakers "
        f"({100*count/n:.2f}%)"
    )

print("\n========== BOOTSTRAP ==========")

rng = random.Random(20261103)
B = 10000

metrics = defaultdict(list)

for _ in range(B):

    sample = [rng.choice(ids) for _ in range(n)]
    result = aggregate(sample)

    for key, value in result.items():
        metrics[key].append(value)

observed = aggregate(ids)

for key, value in observed.items():

    low = percentile(metrics[key], 0.025)
    high = percentile(metrics[key], 0.975)

    print(f"\n{key}")
    print(f"Observed: {value:.4f}")
    print(f"95% cluster-bootstrap CI: [{low:.4f}, {high:.4f}]")

print("\nB9 SPEAKER-CLUSTERED STATISTICS: COMPLETE")
