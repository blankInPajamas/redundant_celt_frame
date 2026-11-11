#!/usr/bin/env python3

import csv
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]

PCM_DIR = BASE / "pilot" / "pcm"
SOURCE_MANIFEST = BASE / "pilot" / "pilot_manifest.tsv"

OUT = BASE / "results" / "b9_full_encoding"
INPUT_MANIFEST = OUT / "input_manifest.tsv"
CONFIG_FILE = OUT / "config.json"

FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2

VERSIONS = {
    "1.5.2": ROOT / "scripts/encode_raw_1.5.2",
    "1.6.1": ROOT / "scripts/encode_raw_1.6.1",
}

ENCODER_CONFIG = {
    "mode": "audio",
    "bitrate": 32000,
    "complexity": 10,
    "fec": 0,
    "loss_pct": 0
}

EXPECTED_CONFIG = (
    "CONFIG: mode=audio bitrate=32000 "
    "complexity=10 fec=0 loss_pct=0"
)


def sha256(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def packet_count(path):
    count = 0

    with open(path, "rb") as f:
        while True:
            header = f.read(4)

            if not header:
                break

            if len(header) != 4:
                raise ValueError("Incomplete packet header")

            length = struct.unpack("<i", header)[0]

            if length <= 0:
                raise ValueError("Invalid packet length")

            packet = f.read(length)

            if len(packet) != length:
                raise ValueError("Incomplete packet payload")

            count += 1

    return count


# ==================================================
# STAGE A: INPUT VALIDATION AND MANIFEST FREEZE
# ==================================================

OUT.mkdir(parents=True, exist_ok=True)

print("========== B9 FULL INPUT VALIDATION ==========")

with open(SOURCE_MANIFEST, encoding="utf-8") as f:
    metadata = list(csv.DictReader(f, delimiter="\t"))

if len(metadata) != 5000:
    raise SystemExit(
        f"Expected 5000 metadata rows, found {len(metadata)}"
    )

metadata_by_stem = {}

for row in metadata:
    stem = Path(row["path"]).stem

    if stem in metadata_by_stem:
        raise SystemExit(f"Duplicate metadata recording: {stem}")

    metadata_by_stem[stem] = row

pcm_files = sorted(PCM_DIR.glob("*.pcm"))

if len(pcm_files) != 5000:
    raise SystemExit(
        f"Expected 5000 PCM files, found {len(pcm_files)}"
    )

actual_stems = {p.stem for p in pcm_files}
expected_stems = set(metadata_by_stem)

if actual_stems != expected_stems:
    missing = expected_stems - actual_stems
    extra = actual_stems - expected_stems

    print("Missing PCM:", list(missing)[:10])
    print("Unmatched PCM:", list(extra)[:10])

    raise SystemExit("PCM/MANIFEST MISMATCH")

input_rows = []

for p in pcm_files:

    row = metadata_by_stem[p.stem]
    size = p.stat().st_size

    if size == 0 or size % 2:
        raise SystemExit(f"Invalid PCM size: {p.name}")

    samples = size // 2
    frames, trailing_samples = divmod(samples, FRAME_SAMPLES)

    if frames == 0:
        raise SystemExit(f"No complete frames: {p.name}")

    input_rows.append({
        "recording_id": p.stem,
        "pcm_filename": p.name,
        "original_audio": row["path"],
        "speaker_id": row["client_id"],
        "pcm_bytes": size,
        "samples": samples,
        "complete_frames": frames,
        "trailing_samples": trailing_samples,
        "pcm_sha256": sha256(p)
    })

fields = list(input_rows[0].keys())

with open(INPUT_MANIFEST, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f, fieldnames=fields, delimiter="\t"
    )
    writer.writeheader()
    writer.writerows(input_rows)

encoder_hashes = {
    version: sha256(binary)
    for version, binary in VERSIONS.items()
}

expected_hashes = {
    "1.5.2": "e1d2041039b8c318595e83a4ed04b8dbfec6afc7ba280c9ddf59c16d7496ba1b",
    "1.6.1": "700be2a3f50f1e7e91aea425229626c0aeff36151386f5272510cedfc86ef9a3"
}

if encoder_hashes != expected_hashes:
    raise SystemExit("ENCODER HASH MISMATCH")

config = {
    "dataset": "Common Voice 26.0 American English Male",
    "recordings": 5000,
    "sample_rate": 48000,
    "channels": 1,
    "sample_format": "S16LE",
    "frame_samples": FRAME_SAMPLES,
    "frame_duration_ms": 20,
    "encoder_config": ENCODER_CONFIG,
    "encoder_hashes": encoder_hashes,
    "random_seed": 20261103,
    "input_manifest_sha256": sha256(INPUT_MANIFEST)
}

CONFIG_FILE.write_text(
    json.dumps(config, indent=2),
    encoding="utf-8"
)

print("PCM files:", len(input_rows))
print("Unique speakers:", len({
    r["speaker_id"] for r in input_rows
}))
print("Total complete frames:", sum(
    r["complete_frames"] for r in input_rows
))
print("Total trailing samples:", sum(
    r["trailing_samples"] for r in input_rows
))
print("Manifest:", INPUT_MANIFEST)
print("B9 INPUT FREEZE: PASS")


# ==================================================
# STAGE B: RESUMABLE ENCODING
# ==================================================

def is_complete(version, row, binary_hash, bin_path,
                log_path, marker_path):

    if not all(p.exists() for p in (
        bin_path, log_path, marker_path
    )):
        return False

    try:
        marker = json.loads(marker_path.read_text())

        return (
            marker["input_sha256"] == row["pcm_sha256"]
            and marker["encoder_sha256"] == binary_hash
            and marker["output_sha256"] == sha256(bin_path)
            and marker["log_sha256"] == sha256(log_path)
            and marker["config"] == ENCODER_CONFIG
            and marker["frames"] == row["complete_frames"]
        )

    except Exception:
        return False


def run_one(version, row):

    recording = row["recording_id"]
    binary = VERSIONS[version]
    binary_hash = encoder_hashes[version]

    version_dir = OUT / version

    bin_dir = version_dir / "bitstreams"
    log_dir = version_dir / "diagnostics"
    status_dir = version_dir / "status"

    for directory in (bin_dir, log_dir, status_dir):
        directory.mkdir(parents=True, exist_ok=True)

    bin_path = bin_dir / f"{recording}.bin"
    log_path = log_dir / f"{recording}.log"
    marker_path = status_dir / f"{recording}.json"

    pcm_path = PCM_DIR / row["pcm_filename"]

    if is_complete(
        version, row, binary_hash,
        bin_path, log_path, marker_path
    ):
        return "skipped", version, recording

    for p in (bin_path, log_path, marker_path):
        p.unlink(missing_ok=True)

    tmp_bin = Path(str(bin_path) + ".partial")
    tmp_log = Path(str(log_path) + ".partial")

    tmp_bin.unlink(missing_ok=True)
    tmp_log.unlink(missing_ok=True)

    try:

        with open(tmp_log, "wb") as logfile:

            result = subprocess.run(
                [
                    str(binary),
                    str(pcm_path),
                    str(tmp_bin),
                    "audio",
                    "32000",
                    "10",
                    "0",
                    "0"
                ],
                stdout=logfile,
                stderr=subprocess.STDOUT
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"Encoder exited with {result.returncode}"
            )

        frame_lines = 0
        config_lines = []
        encoded_count = None

        with open(tmp_log, encoding="utf-8",
                  errors="replace") as f:

            for line in f:

                if line.startswith("FRAME "):
                    frame_lines += 1

                if line.startswith("CONFIG:"):
                    config_lines.append(line.strip())

                match = re.search(
                    r"Encoded (\d+) packets", line
                )

                if match:
                    encoded_count = int(match.group(1))

        packets = packet_count(tmp_bin)
        expected = row["complete_frames"]

        if frame_lines != expected:
            raise RuntimeError(
                f"FRAME log mismatch: {frame_lines}/{expected}"
            )

        if config_lines != [EXPECTED_CONFIG]:
            raise RuntimeError("Configuration mismatch")

        if encoded_count != expected:
            raise RuntimeError(
                f"Encoder summary mismatch: {encoded_count}/{expected}"
            )

        if packets != expected:
            raise RuntimeError(
                f"Packet count mismatch: {packets}/{expected}"
            )

        os.replace(tmp_bin, bin_path)
        os.replace(tmp_log, log_path)

        marker = {
            "recording": recording,
            "version": version,
            "input_sha256": row["pcm_sha256"],
            "encoder_sha256": binary_hash,
            "output_sha256": sha256(bin_path),
            "log_sha256": sha256(log_path),
            "frames": expected,
            "packets": packets,
            "config": ENCODER_CONFIG
        }

        temporary_marker = Path(str(marker_path) + ".tmp")

        temporary_marker.write_text(
            json.dumps(marker, indent=2)
        )

        os.replace(temporary_marker, marker_path)

        return "completed", version, recording

    except Exception as exc:

        tmp_bin.unlink(missing_ok=True)

        if tmp_log.exists():
            failed_log = log_dir / f"{recording}.failed.log"
            failed_log.unlink(missing_ok=True)
            os.replace(tmp_log, failed_log)

        failure = status_dir / f"{recording}.failure.txt"
        failure.write_text(str(exc))

        return "failed", version, recording


workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4

if not 1 <= workers <= 8:
    raise SystemExit("Workers must be between 1 and 8")

tasks = [
    (version, row)
    for version in VERSIONS
    for row in input_rows
]

print("\n========== B9 FULL ENCODING ==========")
print("Recordings:", len(input_rows))
print("Versions:", len(VERSIONS))
print("Total encoding jobs:", len(tasks))
print("Workers:", workers)

results = []
completed = 0

with ThreadPoolExecutor(max_workers=workers) as executor:

    futures = [
        executor.submit(run_one, version, row)
        for version, row in tasks
    ]

    for future in as_completed(futures):

        result = future.result()
        results.append(result)

        completed += 1

        if completed % 100 == 0:
            print(
                f"Processed {completed}/{len(tasks)}"
            )

counts = {
    state: sum(r[0] == state for r in results)
    for state in ("completed", "skipped", "failed")
}

summary = {
    "total_jobs": len(tasks),
    "workers": workers,
    **counts
}

(OUT / "run_summary.json").write_text(
    json.dumps(summary, indent=2)
)

print("\n========== B9 ENCODING SUMMARY ==========")

for key, value in summary.items():
    print(f"{key}: {value}")

if counts["failed"]:
    for state, version, recording in results:
        if state == "failed":
            print("FAILED:", version, recording)

    raise SystemExit("B9 FULL ENCODING: FAIL")

if counts["completed"] + counts["skipped"] != len(tasks):
    raise SystemExit("B9 JOB COUNT MISMATCH")

print("\nB9 FULL ENCODING: PASS")
