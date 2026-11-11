#!/usr/bin/env python3

import csv
import math
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]

SOURCE = ROOT / "experiments/B6_steganalysis/detection_accuracy.csv"

OUT = ROOT / "results/phase_b/B6_S4_v2"

OUT.mkdir(parents=True, exist_ok=True)


def wilson_interval(successes, total):

    if total == 0:
        return float("nan"), float("nan")

    z = 1.959963984540054

    p = successes / total
    z2 = z * z

    denominator = 1 + z2 / total

    center = (p + z2 / (2 * total)) / denominator

    margin = (
        z * math.sqrt(
            p * (1 - p) / total
            + z2 / (4 * total * total)
        ) / denominator
    )

    return center - margin, center + margin


with open(SOURCE, newline="") as f:
    rows = list(csv.DictReader(f))


required = {
    "payload_size",
    "stream_type",
    "detector",
    "label"
}

if not rows:
    raise SystemExit("ERROR: No input records found.")

if not required.issubset(rows[0].keys()):
    raise SystemExit("ERROR: Unexpected CSV columns.")


clean = defaultdict(list)
stego = defaultdict(list)

for row in rows:

    detector = row["detector"]

    if row["stream_type"] == "clean":
        clean[detector].append(row)

    elif row["stream_type"] == "stego":

        payload = int(row["payload_size"])

        stego[(detector, payload)].append(row)


metrics = []

thresholds = []

print("\n========== S4 V2: CONFUSION MATRIX ==========\n")

print(
    f"{'DETECTOR':<24} {'PAYLOAD':>7} "
    f"{'TP':>4} {'FN':>4} {'FP':>4} {'TN':>4} "
    f"{'TPR':>9} {'FPR':>9}"
)

print("-" * 90)


for detector in sorted(clean):

    clean_rows = clean[detector]

    n_clean = len(clean_rows)

    fp = sum(
        r["label"] == "stego"
        for r in clean_rows
    )

    tn = n_clean - fp

    fpr = fp / n_clean

    fpr_low, fpr_high = wilson_interval(fp, n_clean)

    empirical_threshold = None
    strict_threshold = None

    payloads = sorted(
        payload
        for d, payload in stego
        if d == detector
    )

    for payload in payloads:

        samples = stego[(detector, payload)]

        n_stego = len(samples)

        tp = sum(
            r["label"] == "stego"
            for r in samples
        )

        fn = n_stego - tp

        tpr = tp / n_stego

        tpr_low, tpr_high = wilson_interval(tp, n_stego)

        empirical_pass = (
            tpr >= 0.90 and fpr <= 0.05
        )

        strict_pass = (
            empirical_pass and fpr_high <= 0.05
        )

        if empirical_pass and empirical_threshold is None:
            empirical_threshold = payload

        if strict_pass and strict_threshold is None:
            strict_threshold = payload

        metrics.append({

            "detector": detector,
            "payload_size": payload,

            "TP": tp,
            "FN": fn,
            "FP": fp,
            "TN": tn,

            "n_stego": n_stego,
            "n_clean": n_clean,

            "TPR": tpr,
            "TPR_Wilson95_low": tpr_low,
            "TPR_Wilson95_high": tpr_high,

            "FPR": fpr,
            "FPR_Wilson95_low": fpr_low,
            "FPR_Wilson95_high": fpr_high,

            "empirical_pass": empirical_pass,
            "strict_pass": strict_pass
        })

        print(
            f"{detector:<24} {payload:>7} "
            f"{tp:>4} {fn:>4} {fp:>4} {tn:>4} "
            f"{tpr*100:>8.2f}% {fpr*100:>8.2f}%"
        )

    thresholds.append({

        "detector": detector,

        "clean_samples": n_clean,

        "observed_FP": fp,
        "observed_FPR": fpr,

        "FPR_Wilson95_upper": fpr_high,

        "empirical_threshold": (
            empirical_threshold
            if empirical_threshold is not None
            else "NONE"
        ),

        "strict_threshold": (
            strict_threshold
            if strict_threshold is not None
            else "NONE"
        )
    })


metrics_file = OUT / "payload_metrics.csv"

threshold_file = OUT / "threshold_summary.csv"


if metrics:

    with open(metrics_file, "w", newline="") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=metrics[0].keys()
        )

        writer.writeheader()
        writer.writerows(metrics)


if thresholds:

    with open(threshold_file, "w", newline="") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=thresholds[0].keys()
        )

        writer.writeheader()
        writer.writerows(thresholds)


print("\n========== S4 DETECTION THRESHOLDS ==========\n")

for result in thresholds:

    print("\nDetector:", result["detector"])

    print(
        "Empirical threshold:",
        result["empirical_threshold"]
    )

    print(
        "Strict 95% FPR-constrained threshold:",
        result["strict_threshold"]
    )

    print(
        "Clean controls:",
        result["clean_samples"]
    )

    print(
        "Observed FPR:",
        f'{result["observed_FPR"]*100:.2f}%'
    )

    print(
        "Upper 95% FPR limit:",
        f'{result["FPR_Wilson95_upper"]*100:.2f}%'
    )


print("\n========== OUTPUT FILES ==========")

print(metrics_file)
print(threshold_file)

print("\nS4 V2 analysis completed.")

