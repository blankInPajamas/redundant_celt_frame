#!/usr/bin/env python3
"""
Independent structural and result audit for a completed B12 Opus payload run.

This audit does not trust the B12 PASS label alone. It independently checks:
- the 200-event preflight inventory and original source hashes;
- all payload/corruption manifests and deterministic SHAKE-256 payloads;
- packet framing and exact byte-level modifications in every saved bitstream;
- baseline and modified decoder CSVs against compressed decoder logs;
- recovered tail bytes, SHA256 integrity controls, PCM hashes and capacity tests;
- the run's output checksum inventory.

Audit outputs are written beside the run directory, not inside it, so the
original B12 checksum inventory remains valid.
"""
import argparse
import csv
import gzip
import hashlib
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

VERSIONS = ("1.5.2", "1.6.1")
SIZES = (4, 8, 16, 24, 32, 36)
REPS = (1, 2, 3)
CAPACITY = 36
EXPECTED_EVENTS = 200
EXPECTED_NORMAL = EXPECTED_EVENTS * len(SIZES) * len(REPS)
EXPECTED_CORRUPT = EXPECTED_EVENTS * len(SIZES)
EXPECTED_BASELINES = EXPECTED_EVENTS * len(VERSIONS)
EXPECTED_DECODER_ROWS = (EXPECTED_NORMAL + EXPECTED_CORRUPT) * len(VERSIONS)

ERRORS = []
WARNINGS = []


def note(condition, message):
    if not condition:
        ERRORS.append(message)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    if not path.is_file():
        ERRORS.append(f"Missing CSV: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def truth(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_sha_file(path):
    result = {}
    if not path.is_file():
        ERRORS.append(f"Missing checksum file: {path}")
        return result
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            ERRORS.append(f"Malformed checksum line {line_no} in {path}")
            continue
        digest, rel = parts
        rel = rel.strip()
        if rel in result:
            ERRORS.append(f"Duplicate checksum path in {path}: {rel}")
        result[rel] = digest.lower()
    return result


def zero_tail(packet):
    count = 0
    for byte in reversed(packet):
        if byte != 0:
            break
        count += 1
    return count


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


def safe_run_file(run, relative):
    p = (run / relative).resolve()
    if run.resolve() not in p.parents:
        raise ValueError(f"Output path escapes run directory: {relative}")
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def read_gzip_text(path):
    if not path.is_file():
        ERRORS.append(f"Missing compressed decoder log: {path}")
        return ""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_decoder_log(text):
    pattern = re.compile(
        r"^===== control=(payload|one_bit_corruption) "
        r"encoder=(1\.5\.2|1\.6\.1) recording=(\S+) "
        r"size=(\d+)B repetition=(\d+) decoder=(1\.5\.2|1\.6\.1) =====\s*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    blocks = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = (
            m.group(1), m.group(2), m.group(3),
            int(m.group(4)), int(m.group(5)), m.group(6)
        )
        if key in blocks:
            ERRORS.append(f"Duplicate decoder-log block: {key}")
        blocks[key] = text[m.end():end]
    return blocks


def parse_baseline_log(text):
    pattern = re.compile(
        r"^===== BASELINE encoder=(1\.5\.2|1\.6\.1) "
        r"recording=(\S+) decoder=(1\.5\.2|1\.6\.1) =====\s*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    blocks = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = (m.group(1), m.group(2), m.group(3))
        if key in blocks:
            ERRORS.append(f"Duplicate baseline-log block: {key}")
        blocks[key] = text[m.end():end]
    return blocks


def log_frame_count(block):
    m = re.search(r"Decoded\s+(\d+)\s+frames", block)
    return int(m.group(1)) if m else None


def matching_tail_count(block, wire_payload):
    tails = re.findall(r"tail36=([0-9a-fA-F]{72})", block)
    wanted = bytes(CAPACITY - len(wire_payload)) + wire_payload
    matched = 0
    for h in tails:
        try:
            if bytes.fromhex(h) == wanted:
                matched += 1
        except ValueError:
            pass
    return matched, len(tails)


def expected_payload(encoder, recording, frame, size, repetition):
    seed = (
        f"B12-CV26-FULL-v1|{encoder}|{recording}|"
        f"{frame}|{size}|{repetition}"
    )
    payload = hashlib.shake_256(seed.encode("utf-8")).digest(size)
    return seed, payload


def check_bool(row, field, context):
    note(truth(row.get(field, "")), f"{context}: {field} is not true")


def main():
    parser = argparse.ArgumentParser(
        description="Independently audit a completed B12 run directory."
    )
    parser.add_argument("--run", required=True, help="Path to run_YYYYMMDD_HHMMSS")
    args = parser.parse_args()

    run = Path(args.run).expanduser().resolve()
    if not run.is_dir():
        print(f"ERROR: run directory does not exist: {run}", file=sys.stderr)
        return 2

    config_path = run / "b12_run_config.json"
    if not config_path.is_file():
        print(f"ERROR: missing {config_path}", file=sys.stderr)
        return 2

    config = json.loads(config_path.read_text(encoding="utf-8"))
    preflight = Path(config.get("preflight_directory", "")).expanduser().resolve()
    if not preflight.is_dir():
        print(f"ERROR: preflight directory does not exist: {preflight}", file=sys.stderr)
        return 2

    root = None
    for parent in preflight.parents:
        if parent.name == "experiments":
            root = parent.parent
            break
    if root is None:
        print("ERROR: could not infer repository root from preflight path.", file=sys.stderr)
        return 2

    print("========== B12 INDEPENDENT AUDIT ==========")
    print("Run:", run)
    print("Preflight:", preflight)
    print("Repository root:", root)

    # 1. Configuration and preflight provenance.
    note(config.get("status") == "COMPLETED", "Run config status is not COMPLETED")
    note(config.get("overall_pass") is True, "Run config overall_pass is not true")
    note(config.get("source_events") == EXPECTED_EVENTS, "Run config does not specify 200 source events")
    note(config.get("actual_normal_payload_instances") == EXPECTED_NORMAL, "Run config normal payload count mismatch")
    note(config.get("actual_corruption_instances") == EXPECTED_CORRUPT, "Run config corruption count mismatch")
    note(config.get("actual_baseline_decodes") == EXPECTED_BASELINES, "Run config baseline count mismatch")
    note(config.get("actual_decoder_comparisons") == EXPECTED_DECODER_ROWS, "Run config decoder comparison count mismatch")
    note(config.get("actual_failure_records") == 0, "Run config reports nonzero failure records")
    note(config.get("source_bitstreams_unchanged") is True, "Run config source_bitstreams_unchanged is not true")

    preflight_report = preflight / "b12_preflight_report.txt"
    preflight_config_path = preflight / "b12_run_config.json"
    inventory_path = preflight / "b12_event_inventory.csv"
    preflight_manifest_path = preflight / "b12_source_manifest.csv"
    preflight_hash_path = preflight / "b12_source_bitstreams.sha256"

    note(preflight_report.is_file(), "Missing B12 preflight report")
    if preflight_report.is_file():
        note("B12 PREFLIGHT: PASS" in preflight_report.read_text(encoding="utf-8", errors="replace"),
             "Preflight report does not contain B12 PREFLIGHT: PASS")

    pre_cfg = {}
    if preflight_config_path.is_file():
        pre_cfg = json.loads(preflight_config_path.read_text(encoding="utf-8"))
        note(pre_cfg.get("source_events") == EXPECTED_EVENTS,
             "Preflight config source_events is not 200")
        note(pre_cfg.get("source_manifest_sha256") == config.get("source_manifest_sha256"),
             "Run/preflight source manifest hashes differ")
        note(sha_file(preflight_config_path) == config.get("preflight_config_sha256"),
             "Preflight config SHA256 differs from run config")

    original_manifest = (
        root / "experiments/B9_common_voice/results/b9_full_encoding/"
        "payload_roundtrip_100speaker/b9_payload_manifest.csv"
    )
    original_manifest_rows = []
    original_manifest_lookup = {}
    if original_manifest.is_file():
        note(sha_file(original_manifest) == config.get("source_manifest_sha256"),
             "Original B9 source manifest SHA256 mismatch")
        original_manifest_rows = read_csv(original_manifest)
        if preflight_manifest_path.is_file():
            note(read_csv(preflight_manifest_path) == original_manifest_rows,
                 "Preflight source-manifest snapshot differs from original B9 manifest")
        for source_row in original_manifest_rows:
            source_key = (source_row.get("encoder", ""), source_row.get("recording", ""))
            note(source_key not in original_manifest_lookup,
                 f"Duplicate event in original B9 manifest: {source_key}")
            original_manifest_lookup[source_key] = source_row
        note(len(original_manifest_rows) == EXPECTED_EVENTS,
             f"Original B9 manifest rows={len(original_manifest_rows)}, expected 200")
    else:
        ERRORS.append(f"Missing original B9 source manifest: {original_manifest}")

    inventory = read_csv(inventory_path)
    note(len(inventory) == EXPECTED_EVENTS, f"Preflight inventory rows={len(inventory)}, expected 200")

    inventory_by_key = {}
    recordings_by_version = defaultdict(set)
    speakers_by_version = defaultdict(set)
    for row in inventory:
        enc, rec = row.get("encoder", ""), row.get("recording", "")
        key = (enc, rec)
        note(enc in VERSIONS, f"Unexpected encoder in inventory: {enc}")
        note(key not in inventory_by_key, f"Duplicate preflight event: {key}")
        inventory_by_key[key] = row
        recordings_by_version[enc].add(rec)
        speakers_by_version[enc].add(row.get("speaker_sha256", ""))

    for enc in VERSIONS:
        note(len([r for r in inventory if r.get("encoder") == enc]) == 100,
             f"{enc}: inventory does not contain 100 events")
        note(len(recordings_by_version[enc]) == 100, f"{enc}: recording IDs are not unique")
        note(len(speakers_by_version[enc]) == 100, f"{enc}: speaker IDs are not unique")

    for key, event_row in inventory_by_key.items():
        source_row = original_manifest_lookup.get(key)
        note(source_row is not None, f"Preflight event missing from original B9 manifest: {key}")
        if source_row:
            note(source_row.get("speaker") == event_row.get("speaker_sha256"),
                 f"Preflight speaker differs from original manifest: {key}")
            note(int(source_row.get("frame", -1)) == int(event_row.get("frame", -2)),
                 f"Preflight frame differs from original manifest: {key}")
            try:
                old_payload = bytes.fromhex(source_row.get("payload_hex", ""))
                note(len(old_payload) == CAPACITY,
                     f"Historical payload is not 36 bytes: {key}")
                note(sha_bytes(old_payload) == source_row.get("payload_sha256", "").lower(),
                     f"Historical payload hash mismatch: {key}")
                note(sha_bytes(old_payload) == event_row.get("original_payload_sha256", "").lower(),
                     f"Preflight historical payload hash mismatch: {key}")
            except Exception as exc:
                ERRORS.append(f"Cannot validate historical payload for {key}: {exc}")
            note(truth(source_row.get("extraction_exact", "")),
                 f"Historical extraction flag failed: {key}")
            note(truth(source_row.get("packet_lengths_preserved", "")),
                 f"Historical packet-length flag failed: {key}")

    # 2. Verify preflight source hashes and original packet streams.
    preflight_hashes = parse_sha_file(preflight_hash_path)
    note(len(preflight_hashes) == EXPECTED_EVENTS,
         f"Preflight source checksum entries={len(preflight_hashes)}, expected 200")
    source_packets = {}
    source_hashes = {}
    for key, row in inventory_by_key.items():
        enc, rec = key
        rel = row.get("source_path", "")
        expected_hash = row.get("source_sha256", "").lower()
        source = root / rel
        if not source.is_file():
            ERRORS.append(f"Missing source bitstream: {source}")
            continue
        actual_hash = sha_file(source)
        note(actual_hash == expected_hash, f"Source bitstream hash mismatch: {enc}/{rec}")
        note(preflight_hashes.get(rel, "") == expected_hash,
             f"Preflight checksum inventory mismatch: {enc}/{rec}")
        source_hashes[rel] = expected_hash
        try:
            packets = read_packets(source)
            source_packets[key] = packets
            frame = int(row["frame"])
            note(len(packets) == int(row["packet_count"]),
                 f"Source packet count mismatch: {enc}/{rec}")
            note(0 <= frame < len(packets), f"Target frame out of range: {enc}/{rec}")
            if 0 <= frame < len(packets):
                note(len(packets[frame]) == int(row["target_packet_bytes"]),
                     f"Target packet size mismatch: {enc}/{rec}")
                note(zero_tail(packets[frame]) == CAPACITY,
                     f"Source does not have exactly a 36-byte zero tail: {enc}/{rec}")
        except Exception as exc:
            ERRORS.append(f"Cannot parse source packets {enc}/{rec}: {exc}")

    # Source before/after inventories and actual source files.
    before = parse_sha_file(run / "b12_source_bitstreams_before.sha256")
    after = parse_sha_file(run / "b12_source_bitstreams_after.sha256")
    note(before == source_hashes, "B12 source-before hashes do not match preflight/current sources")
    note(after == source_hashes, "B12 source-after hashes do not match preflight/current sources")

    # 3. Load all result tables.
    payload_rows = read_csv(run / "b12_payload_manifest.csv")
    corruption_rows = read_csv(run / "b12_corruption_manifest.csv")
    baseline_rows = read_csv(run / "b12_baseline_results.csv")
    decoder_rows = read_csv(run / "b12_decoder_results.csv")
    capacity_rows = read_csv(run / "b12_capacity_rejection.csv")
    event_rows = read_csv(run / "b12_event_summary.csv")
    failure_rows = read_csv(run / "b12_failure_records.csv")

    note(len(payload_rows) == EXPECTED_NORMAL,
         f"Payload manifest rows={len(payload_rows)}, expected {EXPECTED_NORMAL}")
    note(len(corruption_rows) == EXPECTED_CORRUPT,
         f"Corruption manifest rows={len(corruption_rows)}, expected {EXPECTED_CORRUPT}")
    note(len(baseline_rows) == EXPECTED_BASELINES,
         f"Baseline rows={len(baseline_rows)}, expected {EXPECTED_BASELINES}")
    note(len(decoder_rows) == EXPECTED_DECODER_ROWS,
         f"Decoder rows={len(decoder_rows)}, expected {EXPECTED_DECODER_ROWS}")
    note(len(capacity_rows) == EXPECTED_EVENTS,
         f"Capacity rows={len(capacity_rows)}, expected 200")
    note(len(event_rows) == EXPECTED_EVENTS,
         f"Event summary rows={len(event_rows)}, expected 200")
    note(len(failure_rows) == 0, f"Failure-record rows={len(failure_rows)}, expected 0")

    # 4. Independently reconstruct every normal payload and inspect each saved bitstream.
    payload_lookup = {}
    normal_paths = set()
    for row in payload_rows:
        enc, rec = row.get("encoder", ""), row.get("recording", "")
        try:
            size = int(row["payload_size_bytes"])
            rep = int(row["repetition"])
            frame = int(row["frame"])
        except Exception:
            ERRORS.append(f"Invalid numeric payload fields: {row}")
            continue
        key = (enc, rec, size, rep)
        note(key not in payload_lookup, f"Duplicate payload manifest key: {key}")
        payload_lookup[key] = row
        event = inventory_by_key.get((enc, rec))
        note(event is not None, f"Payload references unknown event: {enc}/{rec}")
        if event is None or (enc, rec) not in source_packets:
            continue
        note(size in SIZES, f"Unexpected payload size: {key}")
        note(rep in REPS, f"Unexpected payload repetition: {key}")
        note(frame == int(event["frame"]), f"Payload frame mismatch: {key}")
        note(row.get("speaker_sha256") == event.get("speaker_sha256"),
             f"Payload speaker mismatch: {key}")
        note(row.get("source_bitstream_sha256", "").lower() == event.get("source_sha256", "").lower(),
             f"Payload source hash mismatch: {key}")

        seed, expected_payload_bytes = expected_payload(enc, rec, frame, size, rep)
        actual_payload = bytes.fromhex(row.get("payload_hex", ""))
        note(row.get("payload_seed") == seed, f"Payload seed mismatch: {key}")
        note(actual_payload == expected_payload_bytes, f"SHAKE-256 payload mismatch: {key}")
        note(row.get("payload_sha256", "").lower() == sha_bytes(expected_payload_bytes),
             f"Payload SHA256 mismatch: {key}")

        for field in (
            "packet_count_preserved", "packet_lengths_preserved",
            "target_packet_prefix_preserved", "reserved_zero_padding_preserved",
            "payload_bytes_match", "packet_structure_pass"
        ):
            check_bool(row, field, f"Payload manifest {key}")

        rel = row.get("modified_bitstream", "")
        try:
            bitstream = safe_run_file(run, rel)
            normal_paths.add(rel)
            actual_bit_hash = sha_file(bitstream)
            note(actual_bit_hash == row.get("modified_bitstream_sha256", "").lower(),
                 f"Modified bitstream SHA256 mismatch: {key}")
            original = source_packets[(enc, rec)]
            modified = read_packets(bitstream)
            note(len(modified) == len(original), f"Packet count changed: {key}")
            if len(modified) == len(original):
                note([len(x) for x in modified] == [len(x) for x in original],
                     f"Packet lengths changed: {key}")
                note(all(modified[i] == original[i] for i in range(len(original)) if i != frame),
                     f"Non-target packet changed: {key}")
                note(modified[frame][:-CAPACITY] == original[frame][:-CAPACITY],
                     f"Target packet prefix changed: {key}")
                note(modified[frame][-CAPACITY:-size] == bytes(CAPACITY-size),
                     f"Unused reserved tail is not zero: {key}")
                note(modified[frame][-size:] == expected_payload_bytes,
                     f"Embedded payload bytes differ: {key}")
        except Exception as exc:
            ERRORS.append(f"Normal bitstream audit failed for {key}: {exc}")

    expected_payload_keys = {
        (enc, rec, size, rep)
        for (enc, rec) in inventory_by_key
        for size in SIZES for rep in REPS
    }
    note(set(payload_lookup) == expected_payload_keys,
         "Payload manifest key set does not equal the complete 200x6x3 design")
    note(len(normal_paths) == EXPECTED_NORMAL,
         f"Unique normal bitstream files={len(normal_paths)}, expected {EXPECTED_NORMAL}")
    normal_disk_files = {
        str(p.relative_to(run)) for p in (run / "bitstreams").rglob("*.bin")
    } if (run / "bitstreams").is_dir() else set()
    note(normal_disk_files == normal_paths,
         "Normal bitstream directory contents differ from payload manifest paths")

    # 5. Reconstruct every one-bit corruption and inspect each corrupted bitstream.
    corruption_lookup = {}
    corruption_paths = set()
    corrupted_payloads = {}
    for row in corruption_rows:
        enc, rec = row.get("encoder", ""), row.get("recording", "")
        try:
            size = int(row["payload_size_bytes"])
            rep = int(row["repetition"])
            frame = int(row["frame"])
        except Exception:
            ERRORS.append(f"Invalid numeric corruption fields: {row}")
            continue
        key = (enc, rec, size)
        note(key not in corruption_lookup, f"Duplicate corruption manifest key: {key}")
        corruption_lookup[key] = row
        normal = payload_lookup.get((enc, rec, size, 1))
        event = inventory_by_key.get((enc, rec))
        note(normal is not None, f"Corruption lacks repetition-1 normal payload: {key}")
        note(event is not None, f"Corruption references unknown event: {key}")
        if normal is None or event is None or (enc, rec) not in source_packets:
            continue
        original_payload = bytes.fromhex(normal["payload_hex"])
        corrupted = bytearray(original_payload)
        flip_index = len(corrupted) // 2
        corrupted[flip_index] ^= 0x01
        corrupted = bytes(corrupted)
        corrupted_payloads[key] = corrupted
        flips = sum((a ^ b).bit_count() for a, b in zip(original_payload, corrupted))
        note(rep == 1, f"Corruption repetition is not 1: {key}")
        note(frame == int(event["frame"]), f"Corruption frame mismatch: {key}")
        note(int(row.get("bit_flip_count", -1)) == 1 and flips == 1,
             f"Corruption did not flip exactly one bit: {key}")
        note(int(row.get("bit_flip_byte_index", -1)) == flip_index,
             f"Corruption byte index mismatch: {key}")
        note(row.get("original_payload_sha256", "").lower() == sha_bytes(original_payload),
             f"Corruption original payload hash mismatch: {key}")
        note(row.get("corrupted_payload_sha256", "").lower() == sha_bytes(corrupted),
             f"Corruption payload hash mismatch: {key}")
        note(row.get("source_bitstream_sha256", "").lower() == event.get("source_sha256", "").lower(),
             f"Corruption source hash mismatch: {key}")
        check_bool(row, "packet_lengths_preserved", f"Corruption manifest {key}")
        check_bool(row, "packet_structure_pass", f"Corruption manifest {key}")

        rel = row.get("corrupted_bitstream", "")
        try:
            bitstream = safe_run_file(run, rel)
            corruption_paths.add(rel)
            note(sha_file(bitstream) == row.get("corrupted_bitstream_sha256", "").lower(),
                 f"Corrupted bitstream SHA256 mismatch: {key}")
            original = source_packets[(enc, rec)]
            modified = read_packets(bitstream)
            note(len(modified) == len(original), f"Corrupted packet count changed: {key}")
            if len(modified) == len(original):
                note([len(x) for x in modified] == [len(x) for x in original],
                     f"Corrupted packet lengths changed: {key}")
                note(all(modified[i] == original[i] for i in range(len(original)) if i != frame),
                     f"Corruption changed a non-target packet: {key}")
                note(modified[frame][:-CAPACITY] == original[frame][:-CAPACITY],
                     f"Corruption changed target prefix: {key}")
                note(modified[frame][-CAPACITY:-size] == bytes(CAPACITY-size),
                     f"Corruption unused tail is not zero: {key}")
                note(modified[frame][-size:] == corrupted,
                     f"Corrupted payload bytes differ from one-bit flip: {key}")
        except Exception as exc:
            ERRORS.append(f"Corrupted bitstream audit failed for {key}: {exc}")

    expected_corruption_keys = {
        (enc, rec, size)
        for (enc, rec) in inventory_by_key
        for size in SIZES
    }
    note(set(corruption_lookup) == expected_corruption_keys,
         "Corruption manifest key set does not equal the complete 200x6 design")
    note(len(corruption_paths) == EXPECTED_CORRUPT,
         f"Unique corrupted bitstream files={len(corruption_paths)}, expected {EXPECTED_CORRUPT}")
    corrupt_disk_files = {
        str(p.relative_to(run)) for p in (run / "corrupted_bitstreams").rglob("*.bin")
    } if (run / "corrupted_bitstreams").is_dir() else set()
    note(corrupt_disk_files == corruption_paths,
         "Corrupted bitstream directory contents differ from corruption manifest paths")

    # 6. Baseline result rows and independent baseline-log cross-check.
    baseline_lookup = {}
    for row in baseline_rows:
        key = (row.get("encoder", ""), row.get("recording", ""), row.get("decoder", ""))
        note(key not in baseline_lookup, f"Duplicate baseline result: {key}")
        baseline_lookup[key] = row
        event = inventory_by_key.get(key[:2])
        note(event is not None, f"Baseline references unknown event: {key}")
        check_bool(row, "baseline_pass", f"Baseline {key}")
        note(int(row.get("return_code", -1)) == 0, f"Baseline return code failed: {key}")
        if event:
            note(int(row.get("decoded_frames", -1)) == int(event["packet_count"]),
                 f"Baseline decoded frame count mismatch: {key}")
            note(int(row.get("expected_frames", -1)) == int(event["packet_count"]),
                 f"Baseline expected frame count mismatch: {key}")
        note(int(row.get("pcm_bytes", 0)) > 0, f"Baseline PCM is empty: {key}")
        note(bool(row.get("pcm_sha256", "")), f"Baseline PCM SHA256 missing: {key}")

    expected_baseline_keys = {
        (enc, rec, dec)
        for enc, rec in inventory_by_key
        for dec in VERSIONS
    }
    note(set(baseline_lookup) == expected_baseline_keys,
         "Baseline result key set is incomplete or contains extras")

    baseline_log_text = read_gzip_text(run / "logs/b12_baseline_decoder_logs.txt.gz")
    baseline_log_blocks = parse_baseline_log(baseline_log_text)
    note(len(baseline_log_blocks) == EXPECTED_BASELINES,
         f"Baseline log blocks={len(baseline_log_blocks)}, expected 400")
    note(set(baseline_log_blocks) == expected_baseline_keys,
         "Baseline log keys do not match baseline result keys")
    for key, block in baseline_log_blocks.items():
        row = baseline_lookup.get(key)
        if row:
            frames = log_frame_count(block)
            note(frames == int(row["decoded_frames"]),
                 f"Baseline log frame count disagrees with CSV: {key}")

    # 7. Decoder results: validate each row, then independently parse log tails.
    decoder_lookup = {}
    for row in decoder_rows:
        control = row.get("control", "")
        enc, rec, dec = row.get("encoder", ""), row.get("recording", ""), row.get("decoder", "")
        try:
            size = int(row["payload_size_bytes"])
            rep = int(row["repetition"])
        except Exception:
            ERRORS.append(f"Invalid decoder-result numeric fields: {row}")
            continue
        key = (control, enc, rec, size, rep, dec)
        note(key not in decoder_lookup, f"Duplicate decoder result: {key}")
        decoder_lookup[key] = row
        event = inventory_by_key.get((enc, rec))
        base = baseline_lookup.get((enc, rec, dec))
        note(event is not None, f"Decoder result references unknown event: {key}")
        note(dec in VERSIONS, f"Unexpected decoder version: {key}")
        note(base is not None, f"Missing baseline row for decoder result: {key}")
        if event:
            note(int(row.get("expected_frames", -1)) == int(event["packet_count"]),
                 f"Decoder expected frame count mismatch: {key}")
            note(int(row.get("decoded_frames", -1)) == int(event["packet_count"]),
                 f"Decoder frame count mismatch: {key}")
        note(int(row.get("decoder_return_code", -1)) == 0, f"Decoder return code failed: {key}")
        check_bool(row, "decoder_pass", f"Decoder {key}")
        check_bool(row, "extraction_exact", f"Decoder {key}")
        check_bool(row, "integrity_control_pass", f"Decoder {key}")
        check_bool(row, "pcm_identical", f"Decoder {key}")
        for field in (
            "packet_count_preserved", "packet_lengths_preserved",
            "target_packet_prefix_preserved", "reserved_zero_padding_preserved",
            "payload_bytes_match", "packet_structure_pass"
        ):
            check_bool(row, field, f"Decoder {key}")

        if base:
            note(row.get("baseline_pcm_sha256", "").lower() == base.get("pcm_sha256", "").lower(),
                 f"Baseline PCM hash differs between tables: {key}")
            note(int(row.get("baseline_pcm_bytes", -1)) == int(base.get("pcm_bytes", -2)),
                 f"Baseline PCM byte count differs between tables: {key}")
            note(int(row.get("baseline_return_code", -1)) == int(base.get("return_code", -2)),
                 f"Baseline return code differs between tables: {key}")
            note(row.get("modified_pcm_sha256", "").lower() == base.get("pcm_sha256", "").lower(),
                 f"Modified PCM hash differs from baseline: {key}")
            note(int(row.get("modified_pcm_bytes", -1)) == int(base.get("pcm_bytes", -2)),
                 f"Modified PCM byte count differs from baseline: {key}")

        if control == "payload":
            payload = payload_lookup.get((enc, rec, size, rep))
            note(payload is not None, f"Missing normal payload for decoder row: {key}")
            if payload:
                wire = bytes.fromhex(payload["payload_hex"])
                expected_path = payload.get("modified_bitstream", "")
                expected_hash = payload.get("modified_bitstream_sha256", "").lower()
                note(row.get("bitstream", "") == expected_path, f"Normal decoder bitstream path mismatch: {key}")
                note(row.get("test_bitstream_sha256", "").lower() == expected_hash,
                     f"Normal decoder bitstream hash mismatch: {key}")
                note(row.get("original_payload_sha256", "").lower() == sha_bytes(wire),
                     f"Normal original payload hash mismatch: {key}")
                note(row.get("wire_payload_sha256", "").lower() == sha_bytes(wire),
                     f"Normal wire payload hash mismatch: {key}")
                note(row.get("extracted_payload_sha256", "").lower() == sha_bytes(wire),
                     f"Normal extracted payload hash mismatch: {key}")
                note(not truth(row.get("integrity_mismatch_detected", "")),
                     f"Normal payload incorrectly flagged as mismatch: {key}")
                note(int(row.get("bit_flip_count", -1)) == 0,
                     f"Normal payload has nonzero bit-flip count: {key}")
        elif control == "one_bit_corruption":
            corrupt = corruption_lookup.get((enc, rec, size))
            payload = payload_lookup.get((enc, rec, size, 1))
            note(rep == 1, f"Corruption decoder repetition is not 1: {key}")
            note(corrupt is not None, f"Missing corruption manifest for decoder row: {key}")
            if corrupt and payload:
                wire = corrupted_payloads.get((enc, rec, size), b"")
                expected_path = corrupt.get("corrupted_bitstream", "")
                expected_hash = corrupt.get("corrupted_bitstream_sha256", "").lower()
                note(row.get("bitstream", "") == expected_path, f"Corrupt decoder bitstream path mismatch: {key}")
                note(row.get("test_bitstream_sha256", "").lower() == expected_hash,
                     f"Corrupt decoder bitstream hash mismatch: {key}")
                note(row.get("original_payload_sha256", "").lower() == payload.get("payload_sha256", "").lower(),
                     f"Corrupt original payload hash mismatch: {key}")
                note(row.get("wire_payload_sha256", "").lower() == sha_bytes(wire),
                     f"Corrupt wire payload hash mismatch: {key}")
                note(row.get("extracted_payload_sha256", "").lower() == sha_bytes(wire),
                     f"Corrupt extracted payload hash mismatch: {key}")
                check_bool(row, "integrity_mismatch_detected", f"Corruption decoder {key}")
                note(int(row.get("bit_flip_count", -1)) == 1,
                     f"Corruption decoder bit-flip count is not 1: {key}")
        else:
            ERRORS.append(f"Unexpected decoder control: {key}")

    expected_decoder_keys = set()
    for enc, rec in inventory_by_key:
        for size in SIZES:
            for rep in REPS:
                for dec in VERSIONS:
                    expected_decoder_keys.add(("payload", enc, rec, size, rep, dec))
            for dec in VERSIONS:
                expected_decoder_keys.add(("one_bit_corruption", enc, rec, size, 1, dec))
    note(set(decoder_lookup) == expected_decoder_keys,
         "Decoder result key set is incomplete or contains extras")

    decoder_log_text = read_gzip_text(run / "logs/b12_decoder_logs.txt.gz")
    decoder_log_blocks = parse_decoder_log(decoder_log_text)
    note(len(decoder_log_blocks) == EXPECTED_DECODER_ROWS,
         f"Decoder log blocks={len(decoder_log_blocks)}, expected {EXPECTED_DECODER_ROWS}")
    note(set(decoder_log_blocks) == expected_decoder_keys,
         "Decoder log keys do not match decoder result keys")

    for key, block in decoder_log_blocks.items():
        row = decoder_lookup.get(key)
        if not row:
            continue
        frames = log_frame_count(block)
        note(frames == int(row["decoded_frames"]),
             f"Decoder log frame count disagrees with CSV: {key}")
        control, enc, rec, size, rep, dec = key
        if control == "payload":
            payload_row = payload_lookup.get((enc, rec, size, rep))
            wire = bytes.fromhex(payload_row["payload_hex"]) if payload_row else b""
        else:
            wire = corrupted_payloads.get((enc, rec, size), b"")
        matches, total = matching_tail_count(block, wire) if wire else (0, 0)
        note(matches == 1, f"Decoder log does not contain exactly one matching payload tail: {key}")
        note(int(row.get("matching_tail_count", -1)) == matches,
             f"CSV matching-tail count disagrees with log: {key}")
        note(int(row.get("total_tail_records", -1)) == total,
             f"CSV total-tail count disagrees with log: {key}")

    # 8. Capacity and event-summary tables.
    capacity_keys = set()
    for row in capacity_rows:
        key = (row.get("encoder", ""), row.get("recording", ""))
        note(key not in capacity_keys, f"Duplicate capacity row: {key}")
        capacity_keys.add(key)
        check_bool(row, "attempted_36_bytes_accepted", f"Capacity {key}")
        check_bool(row, "attempted_37_bytes_rejected", f"Capacity {key}")
        check_bool(row, "source_unchanged_at_test", f"Capacity {key}")
        event = inventory_by_key.get(key)
        note(event is not None, f"Capacity row references unknown event: {key}")
        if event:
            note(int(row.get("capacity_bytes", -1)) == CAPACITY,
                 f"Capacity is not 36 bytes: {key}")
            note(int(row.get("frame", -1)) == int(event["frame"]),
                 f"Capacity frame mismatch: {key}")
            note(row.get("source_bitstream_sha256", "").lower() == event.get("source_sha256", "").lower(),
                 f"Capacity source hash mismatch: {key}")
    note(capacity_keys == set(inventory_by_key),
         "Capacity table does not cover exactly the 200 source events")

    event_summary_keys = set()
    for row in event_rows:
        key = (row.get("encoder", ""), row.get("recording", ""))
        event_summary_keys.add(key)
        expected_values = {
            "baseline_decodes_passed": 2,
            "baseline_decodes_total": 2,
            "normal_decoder_runs": 36,
            "normal_extractions_exact": 36,
            "corruption_decoder_runs": 12,
            "corruption_extractions_exact": 12,
            "integrity_controls_passed": 12,
            "decoder_runs_passed": 48,
            "pcm_comparisons_identical": 48,
            "packet_structure_checks_passed": 48,
        }
        for field, expected in expected_values.items():
            try:
                note(int(row.get(field, -1)) == expected,
                     f"Event summary {key}: {field} expected {expected}, got {row.get(field)}")
            except Exception:
                ERRORS.append(f"Event summary invalid numeric field {key}: {field}")
    note(event_summary_keys == set(inventory_by_key),
         "Event summary does not cover exactly the 200 source events")

    # 9. Verify the run's own checksum inventory.
    checksum_map = parse_sha_file(run / "b12_checksums.sha256")
    checksum_ok = 0
    for rel, expected in checksum_map.items():
        try:
            target = safe_run_file(run, rel)
            actual = sha_file(target)
            if actual == expected:
                checksum_ok += 1
            else:
                ERRORS.append(f"Output checksum mismatch: {rel}")
        except Exception as exc:
            ERRORS.append(f"Output checksum verification failed for {rel}: {exc}")
    note(len(checksum_map) > 0, "B12 checksum inventory is empty")

    # 10. Produce grouped results and a separate audit report.
    grouped = defaultdict(list)
    for row in decoder_rows:
        try:
            key = (
                row["encoder"], row["decoder"],
                int(row["payload_size_bytes"]), row["control"]
            )
            grouped[key].append(row)
        except Exception:
            pass

    audit_dir = run.parent / f"audit_{run.name}"
    suffix = 1
    while audit_dir.exists():
        audit_dir = run.parent / f"audit_{run.name}_{suffix}"
        suffix += 1
    audit_dir.mkdir(parents=True)

    summary_rows = []
    for enc in VERSIONS:
        for dec in VERSIONS:
            for size in SIZES:
                normal = grouped.get((enc, dec, size, "payload"), [])
                corrupt = grouped.get((enc, dec, size, "one_bit_corruption"), [])
                summary_rows.append({
                    "encoder": enc,
                    "decoder": dec,
                    "payload_size_bytes": size,
                    "normal_decoder_runs": len(normal),
                    "normal_extraction_passes": sum(truth(r.get("extraction_exact")) for r in normal),
                    "normal_pcm_identical": sum(truth(r.get("pcm_identical")) for r in normal),
                    "corruption_decoder_runs": len(corrupt),
                    "corruption_extraction_passes": sum(truth(r.get("extraction_exact")) for r in corrupt),
                    "integrity_controls_passes": sum(truth(r.get("integrity_control_pass")) for r in corrupt),
                    "corruption_pcm_identical": sum(truth(r.get("pcm_identical")) for r in corrupt),
                })

    summary_path = audit_dir / "b12_independent_audit_by_encoder_decoder_size.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    recording_overlap = len(
        {r["recording"] for r in inventory if r["encoder"] == VERSIONS[0]}
        & {r["recording"] for r in inventory if r["encoder"] == VERSIONS[1]}
    )
    speaker_overlap = len(
        {r["speaker_sha256"] for r in inventory if r["encoder"] == VERSIONS[0]}
        & {r["speaker_sha256"] for r in inventory if r["encoder"] == VERSIONS[1]}
    )

    WARNINGS.extend([
        "The SHA256 integrity check is out-of-band; it is not native Opus authentication.",
        "The corruption controls deliberately flip one payload bit; they are not a random-channel-noise or error-correction experiment.",
        "PCM equality demonstrates identical decoder output for these tests; it is not a subjective listening test.",
        "Payload repetitions are repeated trials within each recording/frame, not 3,600 independent recordings.",
    ])
    if recording_overlap < EXPECTED_EVENTS // 2 or speaker_overlap < EXPECTED_EVENTS // 2:
        WARNINGS.append(
            "The two encoder-version event sets are not fully paired. Avoid attributing "
            "between-version differences to the encoder alone without a matched-recording design."
        )

    report_lines = [
        "========== B12 INDEPENDENT AUDIT REPORT ==========",
        f"Run directory: {run}",
        f"Preflight directory: {preflight}",
        f"Audit status: {'PASS' if not ERRORS else 'FAIL'}",
        "",
        "========== RECOMPUTED COUNTS ==========",
        f"Preflight events: {len(inventory)}",
        f"Normal payload manifest rows: {len(payload_rows)}",
        f"Corruption manifest rows: {len(corruption_rows)}",
        f"Baseline rows: {len(baseline_rows)}",
        f"Decoder result rows: {len(decoder_rows)}",
        f"Capacity rows: {len(capacity_rows)}",
        f"Event summary rows: {len(event_rows)}",
        f"Failure rows: {len(failure_rows)}",
        f"Baseline log blocks: {len(baseline_log_blocks)}",
        f"Decoder log blocks: {len(decoder_log_blocks)}",
        f"Output checksums verified: {checksum_ok}/{len(checksum_map)}",
        "",
        "========== CROSS-VERSION SAMPLE OVERLAP ==========",
        f"Recording-ID overlap between encoder groups: {recording_overlap}",
        f"Speaker-ID overlap between encoder groups: {speaker_overlap}",
        "",
        "========== ERRORS ==========",
    ]
    report_lines.extend([f"- {e}" for e in ERRORS] if ERRORS else ["None"])
    report_lines.extend(["", "========== INTERPRETATION WARNINGS =========="])
    report_lines.extend([f"- {w}" for w in WARNINGS])
    report_lines.extend([
        "",
        "The audit validates saved bitstreams, manifests, hashes, decoder logs and result tables.",
        "It does not establish steganographic undetectability, native Opus authentication,",
        "error correction, resistance to arbitrary transcoding, or generalization beyond",
        "the tested Common Voice sample and the two instrumented decoder builds.",
    ])

    report_path = audit_dir / "b12_independent_audit_report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n".join(report_lines))
    print("\nGrouped summary:", summary_path)
    print("Audit report:", report_path)

    if ERRORS:
        print(f"\nB12 INDEPENDENT AUDIT: FAIL ({len(ERRORS)} issues)")
        return 2
    print("\nB12 INDEPENDENT AUDIT: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"B12 INDEPENDENT AUDIT ABORTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
