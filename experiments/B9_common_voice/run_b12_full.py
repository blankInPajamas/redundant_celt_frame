#!/usr/bin/env python3
"""Run the B12 full-scale Common Voice payload-reliability experiment.

B12 expands the validated B11 pilot to all 200 preflight-validated events.
Source bitstreams are read-only. All modified bitstreams are written under
B12's unique run directory.
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B9 = ROOT / "experiments/B9_common_voice"
BASE = B9 / "results/b12_payload_reliability"
SOURCE_ROOT = B9 / "results/b9_full_encoding"
SOURCE_MANIFEST = (
    SOURCE_ROOT / "payload_roundtrip_100speaker" /
    "b9_payload_manifest.csv"
)

VERSIONS = ("1.5.2", "1.6.1")
DECODERS = {v: ROOT / f"scripts/decode_raw_{v}" for v in VERSIONS}
SIZES = (4, 8, 16, 24, 32, 36)
REPS = 3
CAPACITY = 36
TIMEOUT_SECONDS = 120

EXPECTED_EVENTS = 200
EXPECTED_NORMAL_PAYLOADS = EXPECTED_EVENTS * len(SIZES) * REPS
EXPECTED_CORRUPT_PAYLOADS = EXPECTED_EVENTS * len(SIZES)
EXPECTED_BASELINES = EXPECTED_EVENTS * len(VERSIONS)
EXPECTED_DECODER_RUNS = (
    EXPECTED_NORMAL_PAYLOADS + EXPECTED_CORRUPT_PAYLOADS
) * len(VERSIONS)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames=None):
    if fieldnames is None:
        if not rows:
            raise ValueError(f"Cannot infer CSV columns for empty file: {path}")
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path, rows):
    if not rows:
        return
    exists = path.exists()
    with open(path, "a" if exists else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def read_packets(path):
    data = Path(path).read_bytes()
    packets = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"Incomplete packet-length header: {path}")
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if length <= 0 or offset + length > len(data):
            raise ValueError(f"Invalid/truncated packet: {path}")
        packets.append(data[offset:offset + length])
        offset += length
    if not packets:
        raise ValueError(f"No packets found: {path}")
    return packets


def write_packets(path, packets):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for packet in packets:
            f.write(struct.pack("<I", len(packet)))
            f.write(packet)


def zero_tail(packet):
    count = 0
    for byte in reversed(packet):
        if byte != 0:
            break
        count += 1
    return count


def embed(packets, frame, payload):
    if len(payload) > CAPACITY:
        raise ValueError(
            f"Payload {len(payload)} exceeds {CAPACITY}-byte capacity"
        )
    if not 0 < len(payload) <= CAPACITY:
        raise ValueError("Payload size must be between 1 and 36 bytes")
    if not 0 <= frame < len(packets):
        raise ValueError("Target frame is outside packet range")
    if zero_tail(packets[frame]) != CAPACITY:
        raise ValueError("Expected exactly 36 trailing zero bytes")

    modified = list(packets)
    target = bytearray(modified[frame])
    target[-len(payload):] = payload
    modified[frame] = bytes(target)
    return modified


def validate_modified(original, modified, frame, payload):
    packet_count_ok = len(original) == len(modified)
    packet_lengths_ok = (
        packet_count_ok
        and [len(p) for p in original] == [len(p) for p in modified]
    )
    prefix_ok = (
        packet_count_ok
        and modified[frame][:-CAPACITY] == original[frame][:-CAPACITY]
    )
    padding_ok = (
        modified[frame][-CAPACITY:-len(payload)]
        == bytes(CAPACITY - len(payload))
    )
    payload_ok = modified[frame][-len(payload):] == payload
    return {
        "packet_count_preserved": packet_count_ok,
        "packet_lengths_preserved": packet_lengths_ok,
        "target_packet_prefix_preserved": prefix_ok,
        "reserved_zero_padding_preserved": padding_ok,
        "payload_bytes_match": payload_ok,
        "packet_structure_pass": all((
            packet_count_ok, packet_lengths_ok, prefix_ok,
            padding_ok, payload_ok
        )),
    }


def make_payload(enc, rec, frame, size, repetition):
    seed = (
        f"B12-CV26-FULL-v1|{enc}|{rec}|{frame}|{size}|{repetition}"
    )
    payload = hashlib.shake_256(seed.encode("utf-8")).digest(size)
    return seed, payload


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def decode(decoder, bitstream, pcm_path, expected_frames):
    try:
        proc = subprocess.run(
            [str(decoder), str(bitstream), str(pcm_path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        rc = proc.returncode
        log = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        log = (
            f"TIMEOUT after {TIMEOUT_SECONDS} seconds\n"
            f"STDOUT:\n{as_text(exc.stdout)}\n"
            f"STDERR:\n{as_text(exc.stderr)}"
        )
    except Exception as exc:
        rc = 125
        log = f"DECODER EXECUTION ERROR: {type(exc).__name__}: {exc}"

    pcm_path = Path(pcm_path)
    pcm = pcm_path.read_bytes() if pcm_path.is_file() else b""
    match = re.search(r"Decoded\s+(\d+)\s+frames", log)
    frames = int(match.group(1)) if match else -1
    ok = rc == 0 and frames == expected_frames and bool(pcm)
    return rc, log, frames, pcm, ok


def extract_tail(log, wire_payload):
    matches = []
    size = len(wire_payload)
    all_tails = re.findall(r"tail36=([0-9a-fA-F]{72})", log)
    for hex_tail in all_tails:
        tail = bytes.fromhex(hex_tail)
        if (
            tail[:CAPACITY - size] == bytes(CAPACITY - size)
            and tail[CAPACITY - size:] == wire_payload
        ):
            matches.append(tail)
    unique_match = matches[0] if len(matches) == 1 else None
    return unique_match, len(matches), len(all_tails)


def locate_preflight(requested):
    if requested:
        path = Path(requested).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(path)
        return path
    candidates = sorted(
        BASE.glob("preflight_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No B12 preflight directory found under {BASE}"
        )
    return candidates[0]


def load_and_validate_inputs(preflight):
    required = (
        "b12_preflight_report.txt",
        "b12_run_config.json",
        "b12_event_inventory.csv",
        "b12_source_manifest.csv",
        "b12_source_bitstreams.sha256",
    )
    for name in required:
        if not (preflight / name).is_file():
            raise FileNotFoundError(preflight / name)

    report_text = (preflight / "b12_preflight_report.txt").read_text(
        encoding="utf-8"
    )
    if "B12 PREFLIGHT: PASS" not in report_text:
        raise ValueError("Selected preflight report does not record PASS")

    config = json.loads(
        (preflight / "b12_run_config.json").read_text(encoding="utf-8")
    )
    if config.get("source_events") != EXPECTED_EVENTS:
        raise ValueError("Preflight config does not specify 200 events")

    if not SOURCE_MANIFEST.is_file():
        raise FileNotFoundError(SOURCE_MANIFEST)
    if file_sha(SOURCE_MANIFEST) != config.get("source_manifest_sha256"):
        raise ValueError(
            "Original B9 source manifest changed after B12 preflight"
        )

    manifest = read_csv(preflight / "b12_source_manifest.csv")
    original_manifest = read_csv(SOURCE_MANIFEST)
    if manifest != original_manifest:
        raise ValueError(
            "Preflight manifest snapshot differs from current B9 manifest"
        )
    if len(manifest) != EXPECTED_EVENTS:
        raise ValueError(f"Expected 200 manifest rows; found {len(manifest)}")

    manifest_lookup = {}
    for row in manifest:
        key = (row["encoder"], row["recording"])
        if key in manifest_lookup:
            raise ValueError(f"Duplicate source manifest key: {key}")
        manifest_lookup[key] = row

    inventory = read_csv(preflight / "b12_event_inventory.csv")
    if len(inventory) != EXPECTED_EVENTS:
        raise ValueError(
            f"Expected 200 inventory events; found {len(inventory)}"
        )

    hash_map = {}
    checksum_lines = (
        preflight / "b12_source_bitstreams.sha256"
    ).read_text(encoding="utf-8").splitlines()
    for line in checksum_lines:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Malformed source checksum line: {line}")
        digest, relative_path = parts
        if relative_path in hash_map:
            raise ValueError(f"Duplicate source checksum path: {relative_path}")
        hash_map[relative_path] = digest.lower()

    if len(hash_map) != EXPECTED_EVENTS:
        raise ValueError(
            f"Expected 200 source checksums; found {len(hash_map)}"
        )

    events = []
    seen_keys = set()
    version_counts = {v: 0 for v in VERSIONS}
    speakers_by_version = {v: set() for v in VERSIONS}
    recordings_by_version = {v: set() for v in VERSIONS}

    for item in inventory:
        enc = item["encoder"]
        rec = item["recording"]
        frame = int(item["frame"])
        key = (enc, rec, frame)
        if enc not in VERSIONS or key in seen_keys:
            raise ValueError(f"Invalid or duplicate inventory event: {key}")
        seen_keys.add(key)

        row = manifest_lookup.get((enc, rec))
        if row is None:
            raise ValueError(f"Inventory event missing from manifest: {enc}/{rec}")
        if int(row["frame"]) != frame:
            raise ValueError(f"Frame mismatch for {enc}/{rec}")
        if row["speaker"] != item["speaker_sha256"]:
            raise ValueError(f"Speaker hash mismatch for {enc}/{rec}")

        original_payload = bytes.fromhex(row["payload_hex"])
        original_hash = sha(original_payload)
        if len(original_payload) != CAPACITY:
            raise ValueError(f"Historical payload is not 36 bytes: {enc}/{rec}")
        if original_hash != row["payload_sha256"].lower():
            raise ValueError(f"Historical payload SHA256 mismatch: {enc}/{rec}")
        if original_hash != item["original_payload_sha256"].lower():
            raise ValueError(f"Inventory payload hash mismatch: {enc}/{rec}")
        if row["extracted_sha256"].lower() != original_hash:
            raise ValueError(f"Historical extracted hash mismatch: {enc}/{rec}")
        if row["extraction_exact"].lower() != "true":
            raise ValueError(f"Historical extraction flag failed: {enc}/{rec}")
        if row["packet_lengths_preserved"].lower() != "true":
            raise ValueError(f"Historical framing flag failed: {enc}/{rec}")

        relative_source = item["source_path"]
        if relative_source not in hash_map:
            raise ValueError(f"Source path absent from checksum inventory: {relative_source}")
        source = ROOT / relative_source
        if not source.is_file():
            raise FileNotFoundError(source)

        expected_source_hash = item["source_sha256"].lower()
        if hash_map[relative_source] != expected_source_hash:
            raise ValueError(f"Preflight hash inventory mismatch: {relative_source}")
        actual_source_hash = file_sha(source)
        if actual_source_hash != expected_source_hash:
            raise ValueError(f"Source bitstream changed after preflight: {relative_source}")

        packets = read_packets(source)
        if not 0 <= frame < len(packets):
            raise ValueError(f"Target frame outside source packet range: {enc}/{rec}")
        if len(packets) != int(item["packet_count"]):
            raise ValueError(f"Packet count changed after preflight: {enc}/{rec}")
        if len(packets[frame]) != int(item["target_packet_bytes"]):
            raise ValueError(f"Target packet length changed: {enc}/{rec}")
        if zero_tail(packets[frame]) != CAPACITY:
            raise ValueError(f"Target packet no longer has a 36-byte zero tail: {enc}/{rec}")

        speakers_by_version[enc].add(item["speaker_sha256"])
        recordings_by_version[enc].add(rec)
        version_counts[enc] += 1

        events.append({
            "encoder": enc,
            "recording": rec,
            "speaker_sha256": item["speaker_sha256"],
            "frame": frame,
            "source": source,
            "source_path": relative_source,
            "source_sha256": expected_source_hash,
            "packets": packets,
        })

    if len(events) != EXPECTED_EVENTS:
        raise ValueError(f"Expected 200 validated events; found {len(events)}")
    for version in VERSIONS:
        if version_counts[version] != 100:
            raise ValueError(f"{version}: expected 100 events; found {version_counts[version]}")
        if len(recordings_by_version[version]) != 100:
            raise ValueError(f"{version}: recording uniqueness check failed")
        if len(speakers_by_version[version]) != 100:
            raise ValueError(f"{version}: speaker uniqueness check failed")

    for version, decoder in DECODERS.items():
        if not decoder.is_file() or not os.access(decoder, os.X_OK):
            raise FileNotFoundError(f"Missing/non-executable decoder: {decoder}")
        if b"B10|mode=" not in decoder.read_bytes():
            raise ValueError(f"Decoder lacks B10 instrumentation: {decoder}")

    return config, manifest, events


def main():
    parser = argparse.ArgumentParser(
        description="Run B12 full-scale payload reliability validation"
    )
    parser.add_argument(
        "--preflight",
        default=None,
        help="Explicit B12 preflight directory (defaults to newest preflight_*)",
    )
    args = parser.parse_args()

    preflight = locate_preflight(args.preflight)
    print("========== B12 INPUT VALIDATION ==========")
    print("Preflight directory:", preflight)
    preflight_config, source_manifest, events = load_and_validate_inputs(preflight)
    print("Validated source events:", len(events))
    print("Opus 1.5.2 events:", sum(e["encoder"] == "1.5.2" for e in events))
    print("Opus 1.6.1 events:", sum(e["encoder"] == "1.6.1" for e in events))
    print("Both instrumented decoders: PASS")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BASE / f"run_{timestamp}"
    out.mkdir(parents=True, exist_ok=False)
    for directory in (
        "bitstreams", "corrupted_bitstreams", "decode_tmp", "logs"
    ):
        (out / directory).mkdir(parents=True, exist_ok=True)

    source_before = {
        e["source_path"]: e["source_sha256"] for e in events
    }
    with open(out / "b12_source_bitstreams_before.sha256", "w", encoding="utf-8") as f:
        for relative_path, digest in sorted(source_before.items()):
            f.write(f"{digest}  {relative_path}\n")

    config = {
        "experiment": "B12 Full-scale Common Voice payload reliability",
        "preflight_directory": str(preflight),
        "preflight_config_sha256": file_sha(preflight / "b12_run_config.json"),
        "source_manifest_sha256": preflight_config["source_manifest_sha256"],
        "source_events": EXPECTED_EVENTS,
        "events_per_encoder": 100,
        "encoder_versions": list(VERSIONS),
        "decoder_versions": list(VERSIONS),
        "payload_sizes_bytes": list(SIZES),
        "independent_repetitions": REPS,
        "usable_capacity_bytes": CAPACITY,
        "payload_generator": "SHAKE-256 with B12-CV26-FULL-v1 event-specific seed",
        "corruption": "One bit flipped at byte index floor(payload_size/2), repetition 1",
        "integrity": "Out-of-band SHA256 comparison with sender's original payload; not native Opus authentication",
        "pcm_comparison": "Modified versus baseline PCM within the same decoder version",
        "expected_normal_payload_instances": EXPECTED_NORMAL_PAYLOADS,
        "expected_corruption_instances": EXPECTED_CORRUPT_PAYLOADS,
        "expected_baseline_decodes": EXPECTED_BASELINES,
        "expected_decoder_comparisons": EXPECTED_DECODER_RUNS,
        "expected_capacity_tests": EXPECTED_EVENTS,
        "timeout_seconds_per_decode": TIMEOUT_SECONDS,
        "source_bitstreams_modified": False,
        "status": "RUNNING",
    }
    with open(out / "b12_run_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    payload_manifest_path = out / "b12_payload_manifest.csv"
    corruption_manifest_path = out / "b12_corruption_manifest.csv"
    baseline_results_path = out / "b12_baseline_results.csv"
    decoder_results_path = out / "b12_decoder_results.csv"
    capacity_path = out / "b12_capacity_rejection.csv"
    event_summary_path = out / "b12_event_summary.csv"

    all_payload_rows = []
    all_corruption_rows = []
    all_baseline_rows = []
    all_decoder_rows = []
    all_capacity_rows = []
    all_event_summaries = []

    baseline_log_path = out / "logs" / "b12_baseline_decoder_logs.txt.gz"
    decoder_log_path = out / "logs" / "b12_decoder_logs.txt.gz"

    print("\n========== B12 BASELINE DECODING + FULL PAYLOAD TEST ==========")
    print("Expected baseline decodes:", EXPECTED_BASELINES)
    print("Expected modified decoder comparisons:", EXPECTED_DECODER_RUNS)
    print("All modified outputs will remain inside:", out)

    with gzip.open(baseline_log_path, "wt", encoding="utf-8") as baseline_logs, \
         gzip.open(decoder_log_path, "wt", encoding="utf-8") as decoder_logs:

        for event_index, event in enumerate(events, 1):
            enc = event["encoder"]
            rec = event["recording"]
            frame = event["frame"]
            packets = event["packets"]
            expected_frames = len(packets)

            event_baseline_rows = []
            event_payload_rows = []
            event_corruption_rows = []
            event_decoder_rows = []
            event_capacity_rows = []

            baseline_by_decoder = {}

            # Decode the untouched source once with each decoder.
            for decoder_version in VERSIONS:
                decoder = DECODERS[decoder_version]
                with tempfile.TemporaryDirectory(dir=out / "decode_tmp") as td:
                    pcm_path = Path(td) / "baseline.pcm"
                    rc, log, frames, pcm, ok = decode(
                        decoder, event["source"], pcm_path, expected_frames
                    )

                baseline_logs.write(
                    f"\n===== BASELINE encoder={enc} recording={rec} "
                    f"decoder={decoder_version} =====\n{log}\n"
                )
                baseline_by_decoder[decoder_version] = {
                    "pcm": pcm if ok else None,
                    "pcm_bytes": len(pcm),
                    "pcm_sha256": sha(pcm) if pcm else "",
                    "return_code": rc,
                    "frames": frames,
                    "pass": ok,
                }
                event_baseline_rows.append({
                    "encoder": enc,
                    "decoder": decoder_version,
                    "recording": rec,
                    "speaker_sha256": event["speaker_sha256"],
                    "frame": frame,
                    "return_code": rc,
                    "decoded_frames": frames,
                    "expected_frames": expected_frames,
                    "pcm_bytes": len(pcm),
                    "pcm_sha256": sha(pcm) if pcm else "",
                    "baseline_pass": ok,
                    "source_bitstream_sha256": event["source_sha256"],
                })

            # Check that the capacity guard accepts 36 bytes and rejects 37.
            try:
                max_payload_packets = embed(packets, frame, bytes(CAPACITY))
                accepted_36 = (
                    max_payload_packets[frame][-CAPACITY:] == bytes(CAPACITY)
                )
            except Exception:
                accepted_36 = False

            try:
                embed(packets, frame, bytes(CAPACITY + 1))
                rejected_37 = False
            except ValueError:
                rejected_37 = True

            event_capacity_rows.append({
                "encoder": enc,
                "recording": rec,
                "frame": frame,
                "capacity_bytes": CAPACITY,
                "attempted_36_bytes_accepted": accepted_36,
                "attempted_37_bytes_rejected": rejected_37,
                "source_unchanged_at_test": file_sha(event["source"]) == event["source_sha256"],
                "source_bitstream_sha256": event["source_sha256"],
            })

            # Six sizes x three normal repetitions; repetition 1 also gets
            # one corruption control. Each test is decoded by both versions.
            for size in SIZES:
                seen_payloads = set()

                for repetition in range(1, REPS + 1):
                    seed, payload = make_payload(
                        enc, rec, frame, size, repetition
                    )
                    if payload in seen_payloads:
                        raise RuntimeError(
                            f"Payload repetition collision: {enc}/{rec}/{size}B"
                        )
                    seen_payloads.add(payload)

                    modified_packets = embed(packets, frame, payload)
                    bitstream = (
                        out / "bitstreams" / enc / rec /
                        f"payload_{size:02d}B_rep{repetition}.bin"
                    )
                    write_packets(bitstream, modified_packets)
                    reopened = read_packets(bitstream)
                    frame_checks = validate_modified(
                        packets, reopened, frame, payload
                    )
                    if not frame_checks["packet_structure_pass"]:
                        raise RuntimeError(
                            f"Normal packet validation failed: {enc}/{rec}/{size}B/rep{repetition}"
                        )

                    corrupted_path = ""
                    corrupted_hash = ""
                    if repetition == 1:
                        corrupted = bytearray(payload)
                        flip_index = len(corrupted) // 2
                        corrupted[flip_index] ^= 0x01
                        corrupted = bytes(corrupted)
                        bit_flips = sum(
                            (a ^ b).bit_count()
                            for a, b in zip(payload, corrupted)
                        )
                        if bit_flips != 1:
                            raise RuntimeError("Corruption control did not flip exactly one bit")

                        corrupted_packets = embed(packets, frame, corrupted)
                        corrupted_bitstream = (
                            out / "corrupted_bitstreams" / enc / rec /
                            f"corrupt_{size:02d}B_rep1.bin"
                        )
                        write_packets(corrupted_bitstream, corrupted_packets)
                        corrupted_reopened = read_packets(corrupted_bitstream)
                        corrupted_checks = validate_modified(
                            packets, corrupted_reopened, frame, corrupted
                        )
                        if not corrupted_checks["packet_structure_pass"]:
                            raise RuntimeError(
                                f"Corrupted packet validation failed: {enc}/{rec}/{size}B"
                            )

                        corrupted_path = str(corrupted_bitstream.relative_to(out))
                        corrupted_hash = file_sha(corrupted_bitstream)
                        event_corruption_rows.append({
                            "encoder": enc,
                            "recording": rec,
                            "speaker_sha256": event["speaker_sha256"],
                            "frame": frame,
                            "payload_size_bytes": size,
                            "repetition": repetition,
                            "bit_flip_count": bit_flips,
                            "bit_flip_byte_index": flip_index,
                            "original_payload_sha256": sha(payload),
                            "corrupted_payload_sha256": sha(corrupted),
                            "source_bitstream_sha256": event["source_sha256"],
                            "corrupted_bitstream_sha256": corrupted_hash,
                            "packet_lengths_preserved": corrupted_checks["packet_lengths_preserved"],
                            "packet_structure_pass": corrupted_checks["packet_structure_pass"],
                            "corrupted_bitstream": corrupted_path,
                        })

                    modified_hash = file_sha(bitstream)
                    event_payload_rows.append({
                        "encoder": enc,
                        "recording": rec,
                        "speaker_sha256": event["speaker_sha256"],
                        "frame": frame,
                        "payload_size_bytes": size,
                        "repetition": repetition,
                        "payload_seed": seed,
                        "payload_hex": payload.hex(),
                        "payload_sha256": sha(payload),
                        "source_bitstream_sha256": event["source_sha256"],
                        "modified_bitstream_sha256": modified_hash,
                        "packet_count_preserved": frame_checks["packet_count_preserved"],
                        "packet_lengths_preserved": frame_checks["packet_lengths_preserved"],
                        "target_packet_prefix_preserved": frame_checks["target_packet_prefix_preserved"],
                        "reserved_zero_padding_preserved": frame_checks["reserved_zero_padding_preserved"],
                        "payload_bytes_match": frame_checks["payload_bytes_match"],
                        "packet_structure_pass": frame_checks["packet_structure_pass"],
                        "modified_bitstream": str(bitstream.relative_to(out)),
                        "corrupted_bitstream": corrupted_path,
                        "corrupted_bitstream_sha256": corrupted_hash,
                    })

                    tests = [{
                        "control": "payload",
                        "wire_payload": payload,
                        "original_payload": payload,
                        "bitstream": bitstream,
                        "bit_flip_count": 0,
                        "bit_flip_byte_index": "",
                        "checks": frame_checks,
                    }]

                    if repetition == 1:
                        tests.append({
                            "control": "one_bit_corruption",
                            "wire_payload": corrupted,
                            "original_payload": payload,
                            "bitstream": corrupted_bitstream,
                            "bit_flip_count": bit_flips,
                            "bit_flip_byte_index": flip_index,
                            "checks": corrupted_checks,
                        })

                    for test in tests:
                        wire = test["wire_payload"]
                        original = test["original_payload"]
                        original_hash = sha(original)
                        wire_hash = sha(wire)

                        for decoder_version in VERSIONS:
                            decoder = DECODERS[decoder_version]
                            baseline_info = baseline_by_decoder[decoder_version]
                            baseline_pcm = baseline_info["pcm"]

                            with tempfile.TemporaryDirectory(dir=out / "decode_tmp") as td:
                                pcm_path = Path(td) / "modified.pcm"
                                rc, log, frames, pcm, decoder_ok = decode(
                                    decoder,
                                    test["bitstream"],
                                    pcm_path,
                                    expected_frames,
                                )

                            decoder_logs.write(
                                f"\n===== control={test['control']} encoder={enc} "
                                f"recording={rec} size={size}B repetition={repetition} "
                                f"decoder={decoder_version} =====\n{log}\n"
                            )

                            tail, matching_tail_count, total_tail_records = extract_tail(
                                log, wire
                            )
                            recovered = tail[-len(wire):] if tail is not None else b""
                            extracted_hash = sha(recovered) if tail is not None else ""
                            extraction_exact = tail is not None and recovered == wire
                            integrity_mismatch = bool(
                                extracted_hash and extracted_hash != original_hash
                            )

                            if test["control"] == "payload":
                                integrity_pass = (
                                    extraction_exact
                                    and extracted_hash == original_hash
                                    and not integrity_mismatch
                                )
                            else:
                                integrity_pass = (
                                    extraction_exact
                                    and extracted_hash == wire_hash
                                    and integrity_mismatch
                                )

                            checks = test["checks"]
                            event_decoder_rows.append({
                                "control": test["control"],
                                "encoder": enc,
                                "decoder": decoder_version,
                                "recording": rec,
                                "speaker_sha256": event["speaker_sha256"],
                                "frame": frame,
                                "payload_size_bytes": size,
                                "repetition": repetition,
                                "original_payload_sha256": original_hash,
                                "wire_payload_sha256": wire_hash,
                                "bit_flip_count": test["bit_flip_count"],
                                "bit_flip_byte_index": test["bit_flip_byte_index"],
                                "extracted_payload_sha256": extracted_hash,
                                "extraction_exact": extraction_exact,
                                "integrity_mismatch_detected": integrity_mismatch,
                                "integrity_control_pass": integrity_pass,
                                "matching_tail_count": matching_tail_count,
                                "total_tail_records": total_tail_records,
                                "decoder_return_code": rc,
                                "decoded_frames": frames,
                                "expected_frames": expected_frames,
                                "decoder_pass": decoder_ok,
                                "baseline_return_code": baseline_info["return_code"],
                                "baseline_pcm_bytes": baseline_info["pcm_bytes"],
                                "modified_pcm_bytes": len(pcm),
                                "baseline_pcm_sha256": baseline_info["pcm_sha256"],
                                "modified_pcm_sha256": sha(pcm) if pcm else "",
                                "pcm_identical": baseline_pcm is not None and pcm == baseline_pcm,
                                "packet_count_preserved": checks["packet_count_preserved"],
                                "packet_lengths_preserved": checks["packet_lengths_preserved"],
                                "target_packet_prefix_preserved": checks["target_packet_prefix_preserved"],
                                "reserved_zero_padding_preserved": checks["reserved_zero_padding_preserved"],
                                "payload_bytes_match": checks["payload_bytes_match"],
                                "packet_structure_pass": checks["packet_structure_pass"],
                                "source_bitstream_sha256": event["source_sha256"],
                                "test_bitstream_sha256": file_sha(test["bitstream"]),
                                "bitstream": str(test["bitstream"].relative_to(out)),
                            })

            # Append only completed-event records. If the run is interrupted,
            # all previously completed events remain available for auditing.
            event_normal = [r for r in event_decoder_rows if r["control"] == "payload"]
            event_corrupt = [r for r in event_decoder_rows if r["control"] == "one_bit_corruption"]
            event_summary = [{
                "encoder": enc,
                "recording": rec,
                "frame": frame,
                "baseline_decodes_passed": sum(bool(r["baseline_pass"]) for r in event_baseline_rows),
                "baseline_decodes_total": len(event_baseline_rows),
                "normal_decoder_runs": len(event_normal),
                "normal_extractions_exact": sum(bool(r["extraction_exact"]) for r in event_normal),
                "corruption_decoder_runs": len(event_corrupt),
                "corruption_extractions_exact": sum(bool(r["extraction_exact"]) for r in event_corrupt),
                "integrity_controls_passed": sum(bool(r["integrity_control_pass"]) for r in event_corrupt),
                "decoder_runs_passed": sum(bool(r["decoder_pass"]) for r in event_decoder_rows),
                "pcm_comparisons_identical": sum(bool(r["pcm_identical"]) for r in event_decoder_rows),
                "packet_structure_checks_passed": sum(bool(r["packet_structure_pass"]) for r in event_decoder_rows),
            }]

            append_csv(baseline_results_path, event_baseline_rows)
            append_csv(payload_manifest_path, event_payload_rows)
            append_csv(corruption_manifest_path, event_corruption_rows)
            append_csv(decoder_results_path, event_decoder_rows)
            append_csv(capacity_path, event_capacity_rows)
            append_csv(event_summary_path, event_summary)

            all_baseline_rows.extend(event_baseline_rows)
            all_payload_rows.extend(event_payload_rows)
            all_corruption_rows.extend(event_corruption_rows)
            all_decoder_rows.extend(event_decoder_rows)
            all_capacity_rows.extend(event_capacity_rows)
            all_event_summaries.extend(event_summary)

            print(
                f"Processed event {event_index}/{EXPECTED_EVENTS}: "
                f"{enc} {rec} | decoder comparisons={len(event_decoder_rows)}"
            )

    # Verify that every original source bitstream is still byte-identical.
    source_after = {
        e["source_path"]: file_sha(e["source"])
        for e in events
    }
    source_unchanged = source_before == source_after

    with open(out / "b12_source_bitstreams_after.sha256", "w", encoding="utf-8") as f:
        for relative_path, digest in sorted(source_after.items()):
            f.write(f"{digest}  {relative_path}\n")

    normal_results = [r for r in all_decoder_rows if r["control"] == "payload"]
    corrupt_results = [r for r in all_decoder_rows if r["control"] == "one_bit_corruption"]

    baseline_ok = sum(bool(r["baseline_pass"]) for r in all_baseline_rows)
    normal_extraction_ok = sum(bool(r["extraction_exact"]) for r in normal_results)
    corrupt_extraction_ok = sum(bool(r["extraction_exact"]) for r in corrupt_results)
    integrity_ok = sum(bool(r["integrity_control_pass"]) for r in corrupt_results)
    decoder_ok = sum(bool(r["decoder_pass"]) for r in all_decoder_rows)
    pcm_ok = sum(bool(r["pcm_identical"]) for r in all_decoder_rows)
    framing_ok = sum(bool(r["packet_lengths_preserved"]) for r in all_decoder_rows)
    structure_ok = sum(bool(r["packet_structure_pass"]) for r in all_decoder_rows)
    capacity_ok = sum(
        bool(r["attempted_36_bytes_accepted"])
        and bool(r["attempted_37_bytes_rejected"])
        and bool(r["source_unchanged_at_test"])
        for r in all_capacity_rows
    )

    failure_rows = [
        r for r in all_decoder_rows
        if not (
            r["extraction_exact"]
            and r["integrity_control_pass"]
            and r["decoder_pass"]
            and r["pcm_identical"]
            and r["packet_structure_pass"]
        )
    ]
    write_csv(
        out / "b12_failure_records.csv",
        failure_rows,
        fieldnames=list(all_decoder_rows[0].keys()) if all_decoder_rows else None,
    )

    passed = all((
        len(events) == EXPECTED_EVENTS,
        len(all_payload_rows) == EXPECTED_NORMAL_PAYLOADS,
        len(all_corruption_rows) == EXPECTED_CORRUPT_PAYLOADS,
        len(normal_results) == EXPECTED_NORMAL_PAYLOADS * len(VERSIONS),
        len(corrupt_results) == EXPECTED_CORRUPT_PAYLOADS * len(VERSIONS),
        len(all_baseline_rows) == EXPECTED_BASELINES,
        baseline_ok == EXPECTED_BASELINES,
        normal_extraction_ok == EXPECTED_NORMAL_PAYLOADS * len(VERSIONS),
        corrupt_extraction_ok == EXPECTED_CORRUPT_PAYLOADS * len(VERSIONS),
        integrity_ok == EXPECTED_CORRUPT_PAYLOADS * len(VERSIONS),
        decoder_ok == EXPECTED_DECODER_RUNS,
        pcm_ok == EXPECTED_DECODER_RUNS,
        framing_ok == EXPECTED_DECODER_RUNS,
        structure_ok == EXPECTED_DECODER_RUNS,
        len(all_capacity_rows) == EXPECTED_EVENTS,
        capacity_ok == EXPECTED_EVENTS,
        source_unchanged,
    ))

    report = [
        "========== B12 FULL-SCALE PAYLOAD RELIABILITY REPORT ==========",
        f"Run directory: {out}",
        f"Preflight directory: {preflight}",
        f"Source manifest SHA256: {preflight_config['source_manifest_sha256']}",
        "",
        "========== DESIGN ==========",
        "Events: 200 (100 per encoder version)",
        "Encoders: Opus 1.5.2 and 1.6.1",
        "Decoders: Opus 1.5.2 and 1.6.1 (cross-version matrix)",
        "Payload sizes: 4, 8, 16, 24, 32, 36 bytes",
        "Independent repetitions: 3 per event-size pair",
        f"Normal payload instances: {len(all_payload_rows)}",
        f"One-bit corruption instances: {len(all_corruption_rows)}",
        "Integrity check: out-of-band sender SHA256; not native Opus authentication",
        "PCM comparison: modified stream against same-decoder baseline",
        "",
        "========== RESULTS ==========",
        f"Baseline decodes: {baseline_ok}/{len(all_baseline_rows)}",
        f"Uncorrupted extraction: {normal_extraction_ok}/{len(normal_results)}",
        f"Corrupted extraction: {corrupt_extraction_ok}/{len(corrupt_results)}",
        f"Corruption SHA256 integrity controls: {integrity_ok}/{len(corrupt_results)}",
        f"Successful modified decoder runs: {decoder_ok}/{len(all_decoder_rows)}",
        f"Exact PCM matches against same-decoder baseline: {pcm_ok}/{len(all_decoder_rows)}",
        f"Packet lengths preserved: {framing_ok}/{len(all_decoder_rows)}",
        f"Complete packet/target-region checks passed: {structure_ok}/{len(all_decoder_rows)}",
        f"36-byte accepted and 37-byte rejected: {capacity_ok}/{len(all_capacity_rows)}",
        f"Source bitstreams unchanged: {source_unchanged}",
        f"Failure records: {len(failure_rows)}",
        "",
        f"OVERALL B12 FULL-SCALE: {'PASS' if passed else 'FAIL / INVESTIGATION REQUIRED'}",
    ]
    (out / "b12_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    config.update({
        "status": "COMPLETED",
        "overall_pass": passed,
        "actual_normal_payload_instances": len(all_payload_rows),
        "actual_corruption_instances": len(all_corruption_rows),
        "actual_baseline_decodes": len(all_baseline_rows),
        "actual_decoder_comparisons": len(all_decoder_rows),
        "actual_failure_records": len(failure_rows),
        "source_bitstreams_unchanged": source_unchanged,
        "script_sha256": file_sha(Path(__file__)),
    })
    with open(out / "b12_run_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    checksum_path = out / "b12_checksums.sha256"
    with open(checksum_path, "w", encoding="utf-8") as f:
        for path in sorted(
            p for p in out.rglob("*")
            if p.is_file() and p != checksum_path
        ):
            f.write(f"{file_sha(path)}  {path.relative_to(out)}\n")

    print("\n".join(report))
    print("\n========== OUTPUT FILES ==========")
    for path in sorted(out.rglob("*")):
        if path.is_file():
            print(path.relative_to(out), path.stat().st_size, "bytes")
    print("\nChecksums:", checksum_path)
    print("Results directory:", out)

    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"\nB12 FULL RUN ABORTED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
