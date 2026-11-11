#!/usr/bin/env python3

import csv
import hashlib
import subprocess
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

SOURCE = ROOT / "logs/phase_b/B8_instrumented_20261103_012056"

INPUT = ROOT / "data/pcm/librispeech"

OUTPUT = ROOT / "results/phase_b/B8_final_audit/cross_decoder"

VERSIONS = ["1.5.2", "1.6.1"]

OUTPUT.mkdir(parents=True, exist_ok=True)

rows = list(csv.DictReader(
    (SOURCE / "b8_instrumented_summary.csv").open()
))

assert len(rows) == 40

results = []

def sha256(path):

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


print("========== B8 CROSS-DECODER VALIDATION ==========")

for row in rows:

    name = row["file"]
    encoder = row["version"]

    stream = SOURCE / f"{name}_{encoder}.bin"
    source_pcm = INPUT / f"{name}.pcm"

    assert stream.exists(), stream
    assert source_pcm.exists(), source_pcm

    expected_size = source_pcm.stat().st_size

    outputs = {}

    for decoder in VERSIONS:

        decoder_bin = ROOT / f"scripts/decode_raw_{decoder}"

        assert decoder_bin.exists(), decoder_bin

        destination = (
            OUTPUT /
            f"enc{encoder}_dec{decoder}_{name}.pcm"
        )

        log_path = (
            OUTPUT /
            f"enc{encoder}_dec{decoder}_{name}.log"
        )

        result = subprocess.run(
            [
                str(decoder_bin),
                str(stream),
                str(destination)
            ],
            capture_output=True,
            text=True,
            timeout=120
        )

        log_path.write_text(
            "STDOUT:\n" + result.stdout +
            "\nSTDERR:\n" + result.stderr
        )

        success = (
            result.returncode == 0
            and destination.exists()
            and destination.stat().st_size > 0
        )

        actual_size = (
            destination.stat().st_size
            if destination.exists()
            else 0
        )

        correct_size = actual_size == expected_size

        outputs[decoder] = destination if success else None

        results.append({
            "recording": name,
            "encoder": encoder,
            "decoder": decoder,
            "return_code": result.returncode,
            "decode_success": success,
            "expected_pcm_bytes": expected_size,
            "actual_pcm_bytes": actual_size,
            "pcm_length_correct": correct_size,
            "pcm_sha256": sha256(destination)
                if success else "",
            "cross_decoder_identical": ""
        })

        print(
            f"{name} | encoder={encoder} "
            f"decoder={decoder} "
            f"success={success} "
            f"bytes={actual_size}"
        )

    # Compare cross-decoder output with the same-version reference.
    reference = outputs.get(encoder)

    for decoder in VERSIONS:

        if decoder == encoder:
            continue

        candidate = outputs.get(decoder)

        identical = (
            reference is not None
            and candidate is not None
            and reference.read_bytes() == candidate.read_bytes()
        )

        for result in results:

            if (
                result["recording"] == name
                and result["encoder"] == encoder
                and result["decoder"] == decoder
            ):
                result["cross_decoder_identical"] = identical


# Save detailed results.

csv_path = OUTPUT / "b8_cross_decoder_results.csv"

with csv_path.open("w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)


# Summarize.

total = len(results)

successful = sum(
    r["decode_success"] for r in results
)

correct_lengths = sum(
    r["pcm_length_correct"] for r in results
)

cross_tests = [
    r for r in results
    if r["decoder"] != r["encoder"]
]

identical = sum(
    r["cross_decoder_identical"] is True
    for r in cross_tests
)

print("\n========== FINAL SUMMARY ==========")

print("Total decoding operations:", total)
print("Successful decodes:", successful, "/", total)
print("Correct PCM lengths:", correct_lengths, "/", total)

print(
    "Cross-version PCM identical:",
    identical, "/", len(cross_tests)
)

for encoder in VERSIONS:

    for decoder in VERSIONS:

        subset = [
            r for r in results
            if r["encoder"] == encoder
            and r["decoder"] == decoder
        ]

        passed = sum(r["decode_success"] for r in subset)

        print(
            f"Encoder {encoder} -> Decoder {decoder}: "
            f"{passed}/{len(subset)}"
        )

print("\nSaved:", csv_path)

if successful != 80:
    raise SystemExit("FAIL: Not all decoding operations succeeded.")

if correct_lengths != 80:
    raise SystemExit("FAIL: Incorrect PCM output length.")

if identical != 40:
    raise SystemExit("FAIL: Cross-version PCM mismatch.")

print("\nB8 CROSS-DECODER VALIDATION: PASS")

