#!/usr/bin/env python3

import csv
import numpy as np
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

BASE = (
    ROOT /
    "results/phase_b/B8_final_audit/cross_decoder"
)

OUTPUT = (
    ROOT /
    "results/phase_b/B8_final_audit"
)

results = []

print("========== PCM DIFFERENCE ANALYSIS ==========")

for encoder in ["1.5.2", "1.6.1"]:

    for name_path in sorted(
        (ROOT / "data/pcm/librispeech").glob("*.pcm")
    ):

        name = name_path.stem

        a_path = BASE / (
            f"enc{encoder}_dec1.5.2_{name}.pcm"
        )

        b_path = BASE / (
            f"enc{encoder}_dec1.6.1_{name}.pcm"
        )

        assert a_path.exists(), a_path
        assert b_path.exists(), b_path

        a = np.fromfile(a_path, dtype="<i2").astype(np.int32)
        b = np.fromfile(b_path, dtype="<i2").astype(np.int32)

        assert len(a) == len(b)

        diff = a - b
        absolute = np.abs(diff)

        mse = np.mean(diff.astype(np.float64) ** 2)
        rmse = np.sqrt(mse)

        signal_power = np.mean(a.astype(np.float64) ** 2)

        snr = (
            10 * np.log10(signal_power / mse)
            if mse > 0 and signal_power > 0
            else float("inf")
        )

        different = np.count_nonzero(diff)

        result = {
            "recording": name,
            "encoder": encoder,
            "samples": len(a),
            "identical": different == 0,
            "different_samples": int(different),
            "different_percent": different / len(a) * 100,
            "max_abs_difference": int(absolute.max()),
            "mean_abs_difference": float(np.mean(absolute)),
            "rmse": float(rmse),
            "snr_db": float(snr)
        }

        results.append(result)

        print(
            f"{name} | encoder={encoder} | "
            f"different={different}/{len(a)} | "
            f"max_diff={absolute.max()} | "
            f"RMSE={rmse:.6f} | "
            f"SNR={snr:.2f} dB"
        )


csv_path = OUTPUT / "b8_pcm_difference_analysis.csv"

with csv_path.open("w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)


print("\n========== AGGREGATE RESULTS ==========")

for encoder in ["1.5.2", "1.6.1"]:

    subset = [
        x for x in results
        if x["encoder"] == encoder
    ]

    total = sum(x["samples"] for x in subset)

    different = sum(
        x["different_samples"] for x in subset
    )

    print(f"\nENCODER {encoder}")

    print("Recordings:", len(subset))
    print("Total samples:", total)
    print("Different samples:", different)

    print(
        "Different percentage:",
        different / total * 100
    )

    print(
        "Maximum absolute difference:",
        max(x["max_abs_difference"] for x in subset)
    )

    print(
        "Average RMSE:",
        np.mean([x["rmse"] for x in subset])
    )

    print(
        "Average SNR:",
        np.mean([x["snr_db"] for x in subset])
    )

print("\nSaved:", csv_path)

