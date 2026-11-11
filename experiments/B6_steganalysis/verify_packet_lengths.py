
#!/usr/bin/env python3

import csv
import sys

sys.path.insert(0, "experiments/B6_steganalysis")

from detectors import load_packets

OUT = "logs/phase_b/B6_s2"

SOURCES = [
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    11, 12, 13, 14, 15, 16, 17, 18, 19, 24
]

SIZES = [1, 2, 4, 8, 16, 24, 32]

results = []

for source in SOURCES:

    clean_path = f"{OUT}/clean_{source}.bin"
    clean = load_packets(clean_path)

    clean_sizes = [len(p) for p in clean]

    for n in SIZES:

        stego_path = f"{OUT}/stego_N{n}_{source}.bin"

        stego = load_packets(stego_path)
        stego_sizes = [len(p) for p in stego]

        same_count = len(clean) == len(stego)
        same_lengths = clean_sizes == stego_sizes

        passed = same_count and same_lengths

        results.append({
            "source_id": source,
            "payload_size": n,
            "clean_packets": len(clean),
            "stego_packets": len(stego),
            "same_packet_count": same_count,
            "same_packet_lengths": same_lengths,
            "passed": passed
        })

        print(
            f"Source={source:2d} "
            f"Payload={n:2d} "
            f"Packets={len(stego)} "
            f"Length_match={passed}"
        )

output = "experiments/B6_steganalysis/packet_length_verification.csv"

with open(output, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)

passed = sum(r["passed"] for r in results)

print("\n========== SUMMARY ==========")
print("Total pairs:", len(results))
print("Passed:", passed)
print("Failed:", len(results) - passed)
print("Result:", output)
