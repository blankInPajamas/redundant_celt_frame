#!/usr/bin/env python3

import csv
import hashlib
import json
import os
import struct
import sys

from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
B9 = ROOT / "experiments/B9_common_voice"

SOURCE_ROOT = B9 / "results/b9_full_encoding"

SOURCE_MANIFEST = (
    SOURCE_ROOT /
    "payload_roundtrip_100speaker" /
    "b9_payload_manifest.csv"
)

VERSIONS = ("1.5.2", "1.6.1")
SIZES = (4, 8, 16, 24, 32, 36)

REPETITIONS = 3
CAPACITY = 36

EVENTS_PER_VERSION = 100

EXPECTED_NORMAL = 200 * len(SIZES) * REPETITIONS
EXPECTED_CORRUPTION = 200 * len(SIZES)
EXPECTED_DECODER_RUNS = (
    EXPECTED_NORMAL + EXPECTED_CORRUPTION
) * 2

EXPECTED_BASELINES = 200 * 2
EXPECTED_CAPACITY = 200


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha256(Path(path).read_bytes())


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        raise ValueError("Cannot write empty CSV")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


def read_packets(path):

    data = Path(path).read_bytes()

    packets = []
    offset = 0

    while offset < len(data):

        if offset + 4 > len(data):
            raise ValueError(
                f"Incomplete packet header: {path}"
            )

        length = struct.unpack_from(
            "<I", data, offset
        )[0]

        offset += 4

        if (
            length <= 0
            or offset + length > len(data)
        ):
            raise ValueError(
                f"Invalid packet framing: {path}"
            )

        packets.append(
            data[offset:offset + length]
        )

        offset += length

    return packets


def zero_tail(packet):

    count = 0

    for byte in reversed(packet):

        if byte != 0:
            break

        count += 1

    return count


def main():

    if not SOURCE_MANIFEST.is_file():
        raise FileNotFoundError(SOURCE_MANIFEST)

    manifest = read_csv(SOURCE_MANIFEST)

    if len(manifest) != 200:
        raise ValueError(
            f"Expected 200 events; found {len(manifest)}"
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    OUT = (
        B9 / "results/b12_payload_reliability"
        / f"preflight_{timestamp}"
    )

    OUT.mkdir(parents=True, exist_ok=False)

    print("========== B12 PREFLIGHT ==========")
    print("READ-ONLY: source bitstreams will not be modified.")
    print("Source manifest:", SOURCE_MANIFEST)
    print("Total source events:", len(manifest))

    event_inventory = []
    source_hashes = []
    summaries = []

    event_keys = set()

    # Validate each encoder version.

    for version in VERSIONS:

        rows = [
            r for r in manifest
            if r["encoder"] == version
        ]

        if len(rows) != EVENTS_PER_VERSION:
            raise ValueError(
                f"{version}: expected 100 events, "
                f"found {len(rows)}"
            )

        recordings = {
            r["recording"] for r in rows
        }

        speakers = {
            r["speaker"] for r in rows
        }

        if len(recordings) != 100:
            raise ValueError(
                f"{version}: recording uniqueness failed"
            )

        if len(speakers) != 100:
            raise ValueError(
                f"{version}: speaker uniqueness failed"
            )

        version_validated = 0

        print(f"\n========== OPUS {version} ==========")

        for index, row in enumerate(rows, 1):

            recording = row["recording"]
            speaker = row["speaker"]
            frame = int(row["frame"])

            key = (version, recording, frame)

            if key in event_keys:
                raise ValueError(
                    f"Duplicate event: {key}"
                )

            event_keys.add(key)

            payload = bytes.fromhex(
                row["payload_hex"]
            )

            if len(payload) != CAPACITY:
                raise ValueError(
                    f"Invalid original payload size: {recording}"
                )

            payload_hash = sha256(payload)

            if payload_hash != row["payload_sha256"].lower():
                raise ValueError(
                    f"Payload hash mismatch: {recording}"
                )

            if (
                row["extracted_sha256"].lower()
                != payload_hash
            ):
                raise ValueError(
                    f"Historical extraction mismatch: {recording}"
                )

            if row["extraction_exact"].lower() != "true":
                raise ValueError(
                    f"Historical extraction failed: {recording}"
                )

            if row["packet_lengths_preserved"].lower() != "true":
                raise ValueError(
                    f"Historical framing failed: {recording}"
                )

            source = (
                SOURCE_ROOT /
                version /
                "bitstreams" /
                f"{recording}.bin"
            )

            if not source.is_file():
                raise FileNotFoundError(source)

            packets = read_packets(source)

            if not 0 <= frame < len(packets):
                raise ValueError(
                    f"Target frame missing: {recording}"
                )

            packet = packets[frame]

            actual_tail = zero_tail(packet)

            if actual_tail != CAPACITY:
                raise ValueError(
                    f"Expected exactly 36 trailing zeros; "
                    f"found {actual_tail}: {recording}"
                )

            source_hash = file_sha(source)

            relative_source = source.relative_to(ROOT)

            source_hashes.append(
                f"{source_hash}  {relative_source}"
            )

            event_inventory.append({

                "encoder": version,
                "recording": recording,
                "speaker_sha256": speaker,
                "frame": frame,

                "source_path": str(relative_source),
                "source_sha256": source_hash,
                "source_bytes": source.stat().st_size,

                "packet_count": len(packets),
                "target_packet_bytes": len(packet),
                "trailing_zero_bytes": actual_tail,

                "original_payload_sha256": payload_hash

            })

            version_validated += 1

            if index % 25 == 0:
                print(
                    f"Validated {index}/100 events"
                )

        summaries.append(
            f"{version}: {version_validated}/100 "
            "events; 100 unique recordings; "
            "100 unique speakers; all source packets validated"
        )

    # Verify both instrumented decoders.

    print("\n========== DECODER VALIDATION ==========")

    decoder_checks = []

    for version in VERSIONS:

        decoder = ROOT / f"scripts/decode_raw_{version}"

        if not decoder.is_file():
            raise FileNotFoundError(decoder)

        if not os.access(decoder, os.X_OK):
            raise PermissionError(decoder)

        binary = decoder.read_bytes()

        if b"B10|mode=" not in binary:
            raise ValueError(
                f"Missing B10 instrumentation: {decoder}"
            )

        decoder_checks.append(
            f"Opus {version}: instrumented decoder verified"
        )

        print(decoder_checks[-1])

    # Freeze source manifest and source bitstream hashes.

    with open(
        OUT / "b12_source_bitstreams.sha256",
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n".join(sorted(source_hashes)) + "\n"
        )

    with open(
        OUT / "b12_source_manifest.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(manifest[0].keys())
        )

        writer.writeheader()
        writer.writerows(manifest)

    write_csv(
        OUT / "b12_event_inventory.csv",
        event_inventory
    )

    config = {

        "experiment": "B12 Full-scale payload reliability",

        "source_manifest": str(
            SOURCE_MANIFEST.relative_to(ROOT)
        ),

        "source_manifest_sha256": file_sha(
            SOURCE_MANIFEST
        ),

        "source_events": 200,

        "events_per_encoder": 100,

        "encoder_versions": list(VERSIONS),

        "decoder_versions": list(VERSIONS),

        "payload_sizes_bytes": list(SIZES),

        "independent_repetitions": REPETITIONS,

        "capacity_bytes": CAPACITY,

        "corruption_design":
            "One bit flipped in repetition 1 "
            "for every event-size pair",

        "integrity_method":
            "Out-of-band SHA256 verification",

        "pcm_comparison":
            "Modified versus baseline within the same decoder",

        "expected_normal_payload_instances":
            EXPECTED_NORMAL,

        "expected_corruption_instances":
            EXPECTED_CORRUPTION,

        "expected_decoder_comparisons":
            EXPECTED_DECODER_RUNS,

        "expected_baseline_decodes":
            EXPECTED_BASELINES,

        "expected_capacity_rejections":
            EXPECTED_CAPACITY,

        "source_bitstreams_modified": False

    }

    with open(
        OUT / "b12_run_config.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(config, f, indent=2)
        f.write("\n")

    # Final report.

    report = [

        "========== B12 PREFLIGHT REPORT ==========",

        "READ-ONLY VALIDATION: PASS",

        f"Source manifest records: {len(manifest)}",

        "",

        "========== SOURCE VALIDATION ==========",

        *summaries,

        f"Total validated events: {len(event_inventory)}",

        "Target packets with exactly 36 trailing zeros: 200/200",

        "Original payload SHA256 validation: 200/200",

        "Historical extraction validation: 200/200",

        "Historical packet framing validation: 200/200",

        "",

        "========== DECODER VALIDATION ==========",

        *decoder_checks,

        "",

        "========== EXPECTED B12 WORKLOAD ==========",

        f"Normal payload instances: {EXPECTED_NORMAL}",

        f"One-bit corruption instances: {EXPECTED_CORRUPTION}",

        f"Decoder comparisons: {EXPECTED_DECODER_RUNS}",

        f"Baseline decoder runs: {EXPECTED_BASELINES}",

        f"37-byte capacity rejection tests: {EXPECTED_CAPACITY}",

        "",

        "Source bitstreams modified: NO",

        "",

        "B12 PREFLIGHT: PASS"

    ]

    report_path = OUT / "b12_preflight_report.txt"

    report_path.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    print("\n".join(report))

    print("\n========== SAVED FILES ==========")

    for path in sorted(OUT.iterdir()):
        print(path.name)

    print("\nPreflight directory:", OUT)


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            f"\nB12 PREFLIGHT: FAIL: {exc}",
            file=sys.stderr
        )

        raise SystemExit(1)

