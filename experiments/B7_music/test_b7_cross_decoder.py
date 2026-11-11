#!/usr/bin/env python3

import csv
import subprocess
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

OUT = ROOT / "logs/phase_b/B7_official_20261103_020241"

TEST = OUT / "b7_zero_tail_payload_test"

CROSS = TEST / "b7_cross_decoder_test"

if CROSS.exists():
    raise SystemExit(f"Output already exists: {CROSS}")

CROSS.mkdir(parents=True)

decoders = {
    "1.5.2": ROOT / "scripts/decode_raw_1.5.2",
    "1.6.1": ROOT / "scripts/decode_raw_1.6.1"
}

for decoder in decoders.values():
    if not decoder.is_file():
        raise FileNotFoundError(decoder)

with (OUT / "summary.csv").open(newline="") as f:
    summary = {
        (r["version"], r["id"]): r
        for r in csv.DictReader(f)
    }

with (TEST / "results.csv").open(newline="") as f:
    tests = list(csv.DictReader(f))

if len(tests) != 20:
    raise SystemExit(f"Expected 20 B7 cases, found {len(tests)}")


def decode(decoder, stream, output, log):

    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [str(decoder), str(stream), str(output)],
        capture_output=True,
        text=True
    )

    log.write_text(
        f"Return code: {p.returncode}\n"
        f"STDOUT:\n{p.stdout}\n"
        f"STDERR:\n{p.stderr}\n"
    )

    return (
        p.returncode == 0
        and output.is_file()
        and output.stat().st_size > 0
    )


results = []

for item in tests:

    enc = item["version"]
    recording = item["id"]
    frame = int(item["frame"])

    clean = OUT / summary[(enc, recording)]["bitstream"]

    stego = (
        TEST / "stego" / enc /
        f"{recording}_f{frame}.bin"
    )

    if not clean.is_file() or not stego.is_file():
        raise FileNotFoundError(f"Missing stream: {recording}")

    for dec, decoder in decoders.items():

        tag = f"enc{enc}_dec{dec}_{recording}"

        clean_pcm = CROSS / "pcm" / f"{tag}_clean.pcm"
        stego_pcm = CROSS / "pcm" / f"{tag}_stego.pcm"

        clean_log = CROSS / "logs" / f"{tag}_clean.log"
        stego_log = CROSS / "logs" / f"{tag}_stego.log"

        clean_ok = decode(
            decoder, clean, clean_pcm, clean_log
        )

        stego_ok = decode(
            decoder, stego, stego_pcm, stego_log
        )

        identical = (
            clean_ok
            and stego_ok
            and clean_pcm.read_bytes() == stego_pcm.read_bytes()
        )

        results.append({
            "encoder_version": enc,
            "decoder_version": dec,
            "recording": recording,
            "frame": frame,
            "clean_decode_success": clean_ok,
            "stego_decode_success": stego_ok,
            "pcm_byte_identical": identical,
            "clean_pcm_bytes": (
                clean_pcm.stat().st_size if clean_ok else 0
            ),
            "stego_pcm_bytes": (
                stego_pcm.stat().st_size if stego_ok else 0
            )
        })


output = CROSS / "cross_decoder_results.csv"

with output.open("w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(results[0])
    )

    writer.writeheader()
    writer.writerows(results)


print("========== B7 CROSS-DECODER VALIDATION ==========")
print("Total tests:", len(results))

for metric in (
    "clean_decode_success",
    "stego_decode_success",
    "pcm_byte_identical"
):

    passed = sum(r[metric] for r in results)

    print(f"{metric}: {passed}/{len(results)}")

print("\n========== VERSION MATRIX ==========")

for enc in decoders:

    for dec in decoders:

        subset = [
            r for r in results
            if r["encoder_version"] == enc
            and r["decoder_version"] == dec
        ]

        print(
            f"Encoder {enc} -> Decoder {dec}: "
            f"Decode "
            f"{sum(r['stego_decode_success'] for r in subset)}/"
            f"{len(subset)}, "
            f"PCM identical "
            f"{sum(r['pcm_byte_identical'] for r in subset)}/"
            f"{len(subset)}"
        )

print("\nResults:", output)
