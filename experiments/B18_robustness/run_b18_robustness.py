#!/usr/bin/env python3
"""B18: controlled robustness and failure-mode evaluation.

Reads frozen B12 cover/stego bitstreams, creates new transformed copies, and
tests payload extraction, packet framing, decoder completion, and selected
decode/re-encode transformations. Original B9/B12 files are read-only.

B12 conditions:
  payload sizes: 32 and 36 bytes
  repetition: 1 (one trial per underlying event)
  200 unique events: 100 per encoder version

Transformations:
  payload_bitflip
  target_marker_bitflip
  noncarrier_packet_bitflip
  drop_carrier_packet
  drop_preceding_packet
  swap_carrier_adjacent
  truncate_carrier_packet
  malformed_target_length

Codec re-encoding:
  20-event exploratory subset (10 per source encoder), 36-byte condition,
  re-encoded at 16/32/64 kbps using the corresponding Opus encoder binary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B9 = ROOT / "experiments/B9_common_voice"
B12 = B9 / "results/b12_payload_reliability/run_20261104_020705"
B12_MANIFEST = B12 / "b12_payload_manifest.csv"
B12_EXPECTED_SHA256 = (
    "e993cd21001ff1d16467f8bab65ef5fb"
    "4dbaa2138a3b8aeb95cc0084b9e8c9b8"
)
VERSIONS = ("1.5.2", "1.6.1")
PAYLOAD_SIZES = (32, 36)
REPETITION = 1
TAIL_CAPACITY = 36
BITRATES = (16000, 32000, 64000)
DECODER_SAMPLE_PER_VERSION = 10
REENCODE_SAMPLE_PER_VERSION = 10

ENCODERS = {v: ROOT / f"scripts/encode_raw_{v}" for v in VERSIONS}
DECODERS = {v: ROOT / f"scripts/decode_raw_{v}" for v in VERSIONS}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_packets(raw: bytes, label: str):
    packets = []
    offset = 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError(f"{label}: incomplete 4-byte packet header")
        n = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if n <= 0 or offset + n > len(raw):
            raise ValueError(f"{label}: invalid packet length {n}")
        packets.append(raw[offset:offset+n])
        offset += n
    if not packets:
        raise ValueError(f"{label}: no packets")
    return packets


def serialize_packets(packets):
    out = bytearray()
    for packet in packets:
        if not packet:
            raise ValueError("Cannot serialize an empty packet")
        out.extend(struct.pack("<I", len(packet)))
        out.extend(packet)
    return bytes(out)


def write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_checksums(directory: Path):
    target = directory / "b18_checksums.sha256"
    lines = []
    for path in sorted(p for p in directory.rglob("*")
                       if p.is_file() and p != target):
        lines.append(f"{sha256_file(path)}  {path.relative_to(directory)}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_modified_path(row, b12_run):
    rel = Path(row["modified_bitstream"])
    path = (b12_run / rel).resolve()
    if not path.is_relative_to(b12_run.resolve()):
        raise ValueError(f"Modified bitstream path escapes B12: {rel}")
    return path


def make_transformation(name, source_packets, frame, expected_tail):
    """Return (raw_bytes, expected_carrier_index, note)."""
    packets = [bytes(p) for p in source_packets]
    n = len(packets)
    if frame < 0 or frame >= n:
        raise ValueError("Target frame outside packet list")

    if name == "target_marker_bitflip":
        if len(packets[frame]) < TAIL_CAPACITY + 1:
            raise ValueError("Target packet too short for marker-byte mutation")
        p = bytearray(packets[frame])
        p[-TAIL_CAPACITY-1] ^= 0x01
        packets[frame] = bytes(p)
        return serialize_packets(packets), frame, "Flipped one bit in byte immediately before the 36-byte tail"

    if name == "noncarrier_packet_bitflip":
        other = 0 if frame != 0 else 1
        if other >= n or len(packets[other]) == 0:
            raise ValueError("No non-carrier packet available for bit-flip control")
        p = bytearray(packets[other])
        p[-1] ^= 0x01
        packets[other] = bytes(p)
        return serialize_packets(packets), frame, f"Flipped one bit in non-carrier packet index {other}"

    if name == "drop_carrier_packet":
        del packets[frame]
        return serialize_packets(packets), None, "Removed the carrier packet"

    if name == "drop_preceding_packet":
        if n < 2:
            raise ValueError("Need at least two packets for packet-loss test")
        if frame > 0:
            del packets[frame-1]
            return serialize_packets(packets), frame-1, "Dropped packet immediately before carrier; carrier index shifted by -1"
        del packets[1]
        return serialize_packets(packets), frame, "Carrier was first packet; dropped following non-carrier packet"

    if name == "swap_carrier_adjacent":
        if n < 2:
            raise ValueError("Need at least two packets for reorder test")
        if frame + 1 < n:
            packets[frame], packets[frame+1] = packets[frame+1], packets[frame]
            current = frame + 1
            note = "Swapped carrier with following packet"
        else:
            packets[frame-1], packets[frame] = packets[frame], packets[frame-1]
            current = frame - 1
            note = "Swapped carrier with preceding packet"
        return serialize_packets(packets), current, note

    if name == "truncate_carrier_packet":
        if len(packets[frame]) <= 1:
            raise ValueError("Carrier packet too short to truncate")
        packets[frame] = packets[frame][:-1]
        return serialize_packets(packets), frame, "Removed final byte of carrier packet and updated packet length"

    if name == "malformed_target_length":
        raw = bytearray(serialize_packets(packets))
        offset = sum(4 + len(p) for p in packets[:frame])
        raw[offset:offset+4] = b"\x00\x00\x00\x00"
        return bytes(raw), frame, "Set carrier packet's 4-byte length field to zero"

    raise ValueError(f"Unknown transformation: {name}")


def apply_payload_bitflip(source_packets, frame, payload_size):
    packets = [bytes(p) for p in source_packets]
    p = bytearray(packets[frame])
    pad = TAIL_CAPACITY - payload_size
    index = len(p) - TAIL_CAPACITY + pad + payload_size // 2
    p[index] ^= 0x01
    packets[frame] = bytes(p)
    return serialize_packets(packets), frame, "Flipped exactly one bit in the middle payload byte"


def payload_location(packets, frame, expected_tail):
    at_expected = (
        frame is not None and 0 <= frame < len(packets)
        and len(packets[frame]) >= TAIL_CAPACITY
        and packets[frame][-TAIL_CAPACITY:] == expected_tail
    )
    anywhere = [
        i for i, p in enumerate(packets)
        if len(p) >= TAIL_CAPACITY and p[-TAIL_CAPACITY:] == expected_tail
    ]
    return bool(at_expected), anywhere


def run_decoder(decoder: Path, bitstream: Path, expected_packets: int, temp_root: Path):
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b18_dec_", dir=temp_root) as td:
        pcm = Path(td) / "decoded.pcm"
        try:
            proc = subprocess.run(
                [str(decoder), str(bitstream), str(pcm)],
                capture_output=True, text=True, timeout=180,
            )
            log = (proc.stdout or "") + "\n" + (proc.stderr or "")
            match = re.search(r"Decoded\s+(\d+)\s+frames", log)
            decoded_frames = int(match.group(1)) if match else -1
            hard_error = (
                "opus_decode failed" in log
                or "Invalid packet length" in log
                or "File open failed" in log
            )
            exists = pcm.is_file()
            pcm_size = pcm.stat().st_size if exists else 0
            pcm_hash = sha256_file(pcm) if exists else ""
            complete = (
                proc.returncode == 0 and not hard_error
                and exists and decoded_frames == expected_packets
            )
            return {
                "returncode": proc.returncode,
                "decoded_frames": decoded_frames,
                "expected_frames": expected_packets,
                "decode_complete": complete,
                "pcm_bytes": pcm_size,
                "pcm_sha256": pcm_hash,
                "error_excerpt": " | ".join(
                    line.strip() for line in log.splitlines()
                    if ("failed" in line.lower() or "invalid" in line.lower()
                        or "error" in line.lower())
                )[:500],
                "log_excerpt": " | ".join(log.splitlines())[-1000:],
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -999, "decoded_frames": -1,
                "expected_frames": expected_packets, "decode_complete": False,
                "pcm_bytes": 0, "pcm_sha256": "",
                "error_excerpt": "decoder timeout", "log_excerpt": "decoder timeout",
            }


def run_encoder(encoder: Path, pcm_path: Path, out_path: Path, bitrate: int):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(encoder), str(pcm_path), str(out_path), "audio",
         str(bitrate), "10", "0", "0"],
        capture_output=True, text=True, timeout=300,
    )
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"Encoder failed ({encoder.name}, {bitrate} bps): "
            f"return={proc.returncode}; {log[-1200:]}"
        )
    return log


def exact_tail_found(raw_path: Path, expected_tail: bytes):
    packets = read_packets(raw_path.read_bytes(), str(raw_path))
    hits = [
        i for i, packet in enumerate(packets)
        if len(packet) >= TAIL_CAPACITY
        and packet[-TAIL_CAPACITY:] == expected_tail
    ]
    return packets, hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b12-run", type=Path, default=B12)
    parser.add_argument("--decoder-sample-per-version", type=int,
                        default=DECODER_SAMPLE_PER_VERSION)
    parser.add_argument("--reencode-sample-per-version", type=int,
                        default=REENCODE_SAMPLE_PER_VERSION)
    parser.add_argument("--skip-codec-reencode", action="store_true")
    args = parser.parse_args()

    if args.decoder_sample_per_version < 1 or args.decoder_sample_per_version > 100:
        raise ValueError("--decoder-sample-per-version must be between 1 and 100")
    if args.reencode_sample_per_version < 1 or args.reencode_sample_per_version > 100:
        raise ValueError("--reencode-sample-per-version must be between 1 and 100")

    b12_run = args.b12_run.expanduser().resolve()
    manifest_path = b12_run / "b12_payload_manifest.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest_hash = sha256_file(manifest_path)
    if manifest_hash != B12_EXPECTED_SHA256:
        raise ValueError(
            "B12 manifest SHA-256 mismatch. "
            f"Expected {B12_EXPECTED_SHA256}; got {manifest_hash}"
        )

    for version in VERSIONS:
        for tool in (ENCODERS[version], DECODERS[version]):
            if not tool.is_file() or not tool.stat().st_mode & 0o111:
                raise FileNotFoundError(f"Missing or non-executable tool: {tool}")

    print("========== B18 INPUT PREFLIGHT ==========")
    print("Project:", ROOT)
    print("B12 run:", b12_run)
    print("B12 manifest SHA256: PASS")
    for version in VERSIONS:
        print(f"{version} encoder SHA256: {sha256_file(ENCODERS[version])}")
        print(f"{version} decoder SHA256: {sha256_file(DECODERS[version])}")

    manifest = read_csv(manifest_path)
    if len(manifest) != 3600:
        raise ValueError(f"Expected 3,600 B12 manifest rows, found {len(manifest)}")

    selected = [
        r for r in manifest
        if int(r["payload_size_bytes"]) in PAYLOAD_SIZES
        and int(r["repetition"]) == REPETITION
    ]
    if len(selected) != 400:
        raise ValueError(f"Expected 400 selected B12 rows, found {len(selected)}")

    # Verify one unique event per encoder/recording/frame/size and 100 per encoder.
    event_keys = set()
    for row in selected:
        key = (
            row["encoder"], row["recording"], int(row["frame"]),
            int(row["payload_size_bytes"]),
        )
        if key in event_keys:
            raise ValueError(f"Duplicate B18 event row: {key}")
        event_keys.add(key)
    for version in VERSIONS:
        for size in PAYLOAD_SIZES:
            count = sum(
                r["encoder"] == version
                and int(r["payload_size_bytes"]) == size
                for r in selected
            )
            if count != 100:
                raise ValueError(f"Expected 100 events for {version}/{size}B; got {count}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = ROOT / "experiments/B18_robustness/results" / f"run_{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    transformed_root = out / "transformed_bitstreams"
    reencoded_root = out / "reencoded_bitstreams"
    temp_root = out / "tmp"
    temp_root.mkdir()

    transformation_names = (
        "payload_bitflip",
        "target_marker_bitflip",
        "noncarrier_packet_bitflip",
        "drop_carrier_packet",
        "drop_preceding_packet",
        "swap_carrier_adjacent",
        "truncate_carrier_packet",
        "malformed_target_length",
    )

    transformation_rows = []
    input_hash_rows = []
    transformed_lookup = {}
    event_lookup = {}
    print("\n========== B18 SOURCE VALIDATION ==========")

    # Validate frozen B12 inputs and construct the controlled mutation matrix.
    for idx, row in enumerate(selected, 1):
        version = row["encoder"]
        recording = row["recording"]
        frame = int(row["frame"])
        size = int(row["payload_size_bytes"])
        payload = bytes.fromhex(row["payload_hex"])
        expected_tail = bytes(TAIL_CAPACITY-size) + payload
        if len(payload) != size or sha256_bytes(payload) != row["payload_sha256"]:
            raise ValueError(f"Payload hash/length mismatch: {version}/{recording}/{size}")

        source_path = (
            B9 / "results/b9_full_encoding" / version / "bitstreams" / f"{recording}.bin"
        )
        stego_path = safe_modified_path(row, b12_run)
        if not source_path.is_file() or not stego_path.is_file():
            raise FileNotFoundError(f"Missing source/stego bitstream: {recording}")
        source_raw = source_path.read_bytes()
        stego_raw = stego_path.read_bytes()
        if sha256_bytes(source_raw) != row["source_bitstream_sha256"]:
            raise ValueError(f"Source SHA mismatch: {source_path}")
        if sha256_bytes(stego_raw) != row["modified_bitstream_sha256"]:
            raise ValueError(f"Stego SHA mismatch: {stego_path}")

        cover_packets = read_packets(source_raw, str(source_path))
        stego_packets = read_packets(stego_raw, str(stego_path))
        if frame >= len(cover_packets) or frame >= len(stego_packets):
            raise ValueError(f"Carrier frame out of range: {recording}")
        if cover_packets[frame][-TAIL_CAPACITY:] != bytes(TAIL_CAPACITY):
            raise ValueError(f"Clean carrier tail is not 36 zero bytes: {recording}")
        if stego_packets[frame][-TAIL_CAPACITY:] != expected_tail:
            raise ValueError(f"Stego carrier tail mismatch: {recording}/{size}B")
        if stego_packets[frame][:-TAIL_CAPACITY] != cover_packets[frame][:-TAIL_CAPACITY]:
            raise ValueError(f"Carrier prefix changed in frozen B12 file: {recording}")
        if len(cover_packets) != len(stego_packets):
            raise ValueError(f"Packet count mismatch in frozen B12 file: {recording}")
        if [len(p) for p in cover_packets] != [len(p) for p in stego_packets]:
            raise ValueError(f"Packet lengths mismatch in frozen B12 file: {recording}")
        if any(
            cover_packets[i] != stego_packets[i]
            for i in range(len(cover_packets)) if i != frame
        ):
            raise ValueError(f"Non-carrier packets differ in frozen B12 file: {recording}")

        key = (version, recording, size)
        event_lookup[key] = {
            "row": row, "source_path": source_path, "stego_path": stego_path,
            "cover_packets": cover_packets, "stego_packets": stego_packets,
            "payload": payload, "expected_tail": expected_tail, "frame": frame,
        }
        input_hash_rows.append({
            "encoder": version, "recording": recording, "frame": frame,
            "payload_size_bytes": size, "repetition": REPETITION,
            "source_sha256": sha256_bytes(source_raw),
            "stego_sha256": sha256_bytes(stego_raw),
            "payload_sha256": sha256_bytes(payload),
            "source_packet_count": len(cover_packets),
            "stego_packet_count": len(stego_packets),
            "baseline_payload_exact": True,
            "baseline_other_packets_identical": True,
        })

        # Generate all transformations independently from the frozen stego stream.
        for transform in transformation_names:
            if transform == "payload_bitflip":
                transformed_raw, current_index, note = apply_payload_bitflip(
                    stego_packets, frame, size
                )
            else:
                transformed_raw, current_index, note = make_transformation(
                    transform, stego_packets, frame, expected_tail
                )

            rel_dir = Path(version) / recording / f"{size:02d}B"
            transformed_path = transformed_root / rel_dir / f"{transform}.bin"
            write_bytes(transformed_path, transformed_raw)
            transformed_lookup[(version, recording, size, transform)] = transformed_path

            parse_valid = True
            parsed = None
            parse_error = ""
            try:
                parsed = read_packets(transformed_raw, transform)
            except Exception as exc:
                parse_valid = False
                parse_error = str(exc)

            if parse_valid:
                at_expected, anywhere = payload_location(parsed, frame, expected_tail)
                packet_count = len(parsed)
                packet_lengths_preserved = (
                    packet_count == len(stego_packets)
                    and [len(p) for p in parsed] == [len(p) for p in stego_packets]
                )
            else:
                at_expected, anywhere = False, []
                packet_count = ""
                packet_lengths_preserved = False

            transformation_rows.append({
                "encoder": version,
                "recording": recording,
                "frame_original": frame,
                "carrier_frame_after_transform": (
                    current_index if current_index is not None else ""
                ),
                "payload_size_bytes": size,
                "payload_sha256": sha256_bytes(payload),
                "transformation": transform,
                "transformation_note": note,
                "parser_valid": parse_valid,
                "parse_error": parse_error,
                "packet_count_original": len(stego_packets),
                "packet_count_after": packet_count,
                "packet_count_preserved": (
                    parse_valid and len(parsed) == len(stego_packets)
                ),
                "packet_lengths_preserved": packet_lengths_preserved,
                "payload_exact_at_original_index": at_expected,
                "payload_exact_anywhere": bool(anywhere),
                "payload_exact_packet_indices": ";".join(map(str, anywhere)),
                "transformed_bitstream": str(transformed_path.relative_to(out)),
                "transformed_sha256": sha256_bytes(transformed_raw),
            })

        if idx % 40 == 0:
            print(f"Validated and transformed {idx}/400 B12 rows")

    if len(event_lookup) != 400:
        raise ValueError(f"Expected 400 event-size combinations, got {len(event_lookup)}")
    print("Frozen B12 source/stego validation: PASS")
    print("Transformation cases:", len(transformation_rows))

    # Decoder testing on a deterministic 10-event subset per source encoder.
    print("\n========== B18 DECODER FAILURE-MODE SAMPLE ==========")
    decoder_rows = []
    sample_keys = []
    for version in VERSIONS:
        keys = sorted(
            (k for k in event_lookup if k[0] == version and k[2] == 36),
            key=lambda k: k[1],
        )
        chosen = keys[:args.decoder_sample_per_version]
        if len(chosen) != args.decoder_sample_per_version:
            raise ValueError(f"Not enough decoder sample events for {version}")
        sample_keys.extend(chosen)

    decode_variants = (
        "cover", "stego",
        "payload_bitflip", "target_marker_bitflip",
        "noncarrier_packet_bitflip", "drop_carrier_packet",
        "drop_preceding_packet", "swap_carrier_adjacent",
        "truncate_carrier_packet",
    )
    pcm_pair_lookup = {}
    for event_no, key in enumerate(sample_keys, 1):
        version, recording, size = key
        item = event_lookup[key]
        variants = []
        variants.append(("cover", item["source_path"], len(item["cover_packets"])))
        variants.append(("stego", item["stego_path"], len(item["stego_packets"])))
        for transform in decode_variants[2:]:
            path = transformed_lookup[(version, recording, size, transform)]
            packets = read_packets(path.read_bytes(), str(path))
            variants.append((transform, path, len(packets)))

        for variant, path, packet_count in variants:
            for decoder_version in VERSIONS:
                result = run_decoder(
                    DECODERS[decoder_version], path, packet_count, temp_root
                )
                decoder_rows.append({
                    "source_encoder": version,
                    "recording": recording,
                    "payload_size_bytes": size,
                    "variant": variant,
                    "decoder_version": decoder_version,
                    "packet_count_expected": packet_count,
                    **result,
                })
                if variant in ("cover", "stego"):
                    pcm_pair_lookup[(version, recording, decoder_version, variant)] = result
        if event_no % 5 == 0:
            print(f"Decoded {event_no}/{len(sample_keys)} sampled events")

    pcm_pair_rows = []
    for key in sample_keys:
        version, recording, size = key
        for decoder_version in VERSIONS:
            cover = pcm_pair_lookup[(version, recording, decoder_version, "cover")]
            stego = pcm_pair_lookup[(version, recording, decoder_version, "stego")]
            pcm_pair_rows.append({
                "source_encoder": version,
                "recording": recording,
                "decoder_version": decoder_version,
                "cover_decode_complete": cover["decode_complete"],
                "stego_decode_complete": stego["decode_complete"],
                "cover_pcm_sha256": cover["pcm_sha256"],
                "stego_pcm_sha256": stego["pcm_sha256"],
                "same_decoder_pcm_identical": (
                    bool(cover["pcm_sha256"])
                    and cover["pcm_sha256"] == stego["pcm_sha256"]
                ),
            })

    # Codec-level re-encoding on a small, explicitly exploratory 20-event subset.
    reencode_rows = []
    if not args.skip_codec_reencode:
        print("\n========== B18 DECODE / RE-ENCODE TRANSFORMATIONS ==========")
        reencode_keys = []
        for version in VERSIONS:
            version_keys = sorted(
                (k for k in event_lookup if k[0] == version and k[2] == 36),
                key=lambda k: k[1],
            )
            reencode_keys.extend(version_keys[:args.reencode_sample_per_version])
        for event_no, key in enumerate(reencode_keys, 1):
            version, recording, size = key
            item = event_lookup[key]
            payload = item["payload"]
            expected_tail = item["expected_tail"]

            with tempfile.TemporaryDirectory(prefix="b18_codec_", dir=temp_root) as td:
                td = Path(td)
                cover_pcm = td / "cover.pcm"
                stego_pcm = td / "stego.pcm"

                cover_decode = subprocess.run(
                    [str(DECODERS[version]), str(item["source_path"]), str(cover_pcm)],
                    capture_output=True, text=True, timeout=180,
                )
                stego_decode = subprocess.run(
                    [str(DECODERS[version]), str(item["stego_path"]), str(stego_pcm)],
                    capture_output=True, text=True, timeout=180,
                )
                def parse_decode(proc, pcm_path, expected):
                    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
                    match = re.search(r"Decoded\s+(\d+)\s+frames", log)
                    frames = int(match.group(1)) if match else -1
                    ok = (
                        proc.returncode == 0 and pcm_path.is_file()
                        and frames == expected
                        and "opus_decode failed" not in log
                        and "Invalid packet length" not in log
                    )
                    return ok, frames
                cover_ok, cover_frames = parse_decode(
                    cover_decode, cover_pcm, len(item["cover_packets"])
                )
                stego_ok, stego_frames = parse_decode(
                    stego_decode, stego_pcm, len(item["stego_packets"])
                )
                if not (cover_ok and stego_ok):
                    reencode_rows.append({
                        "source_encoder": version, "recording": recording,
                        "payload_size_bytes": size, "bitrate": "",
                        "cover_pcm_decode_complete": cover_ok,
                        "stego_pcm_decode_complete": stego_ok,
                        "cover_stego_pcm_identical": False,
                        "reencoded_bitstreams_identical": False,
                        "payload_exact_in_reencoded_cover": False,
                        "payload_exact_in_reencoded_stego": False,
                        "reencoded_cover_decode_complete": False,
                        "reencoded_stego_decode_complete": False,
                        "status": "SKIPPED_ORIGINAL_DECODE_FAILURE",
                    })
                    continue

                cover_pcm_hash = sha256_file(cover_pcm)
                stego_pcm_hash = sha256_file(stego_pcm)
                pcm_identical = cover_pcm_hash == stego_pcm_hash

                for bitrate in BITRATES:
                    clean_out = (
                        reencoded_root / version / recording / f"{bitrate}bps" / "cover.bin"
                    )
                    stego_out = (
                        reencoded_root / version / recording / f"{bitrate}bps" / "stego.bin"
                    )
                    clean_log = run_encoder(ENCODERS[version], cover_pcm, clean_out, bitrate)
                    stego_log = run_encoder(ENCODERS[version], stego_pcm, stego_out, bitrate)

                    clean_packets, clean_hits = exact_tail_found(clean_out, expected_tail)
                    stego_packets, stego_hits = exact_tail_found(stego_out, expected_tail)
                    clean_hash = sha256_file(clean_out)
                    stego_hash = sha256_file(stego_out)

                    clean_dec = run_decoder(
                        DECODERS[version], clean_out, len(clean_packets), temp_root
                    )
                    stego_dec = run_decoder(
                        DECODERS[version], stego_out, len(stego_packets), temp_root
                    )

                    reencode_rows.append({
                        "source_encoder": version,
                        "recording": recording,
                        "payload_size_bytes": size,
                        "payload_sha256": sha256_bytes(payload),
                        "bitrate": bitrate,
                        "cover_pcm_decode_complete": cover_ok,
                        "stego_pcm_decode_complete": stego_ok,
                        "cover_pcm_sha256": cover_pcm_hash,
                        "stego_pcm_sha256": stego_pcm_hash,
                        "cover_stego_pcm_identical": pcm_identical,
                        "reencoded_cover_sha256": clean_hash,
                        "reencoded_stego_sha256": stego_hash,
                        "reencoded_bitstreams_identical": clean_hash == stego_hash,
                        "payload_exact_in_reencoded_cover": bool(clean_hits),
                        "payload_exact_in_reencoded_stego": bool(stego_hits),
                        "payload_hit_packets_cover": ";".join(map(str, clean_hits)),
                        "payload_hit_packets_stego": ";".join(map(str, stego_hits)),
                        "reencoded_cover_decode_complete": clean_dec["decode_complete"],
                        "reencoded_stego_decode_complete": stego_dec["decode_complete"],
                        "reencoded_cover_packet_count": len(clean_packets),
                        "reencoded_stego_packet_count": len(stego_packets),
                        "encoder_config_log": (clean_log + "\n" + stego_log)[-1000:],
                        "status": "COMPLETE",
                    })
            if event_no % 5 == 0:
                print(f"Completed codec re-encoding sample {event_no}/{len(sample_keys)}")

    # Summaries.
    summary_rows = []
    for version in VERSIONS:
        for size in PAYLOAD_SIZES:
            subset = [
                r for r in transformation_rows
                if r["encoder"] == version and int(r["payload_size_bytes"]) == size
            ]
            for transform in transformation_names:
                group = [r for r in subset if r["transformation"] == transform]
                n = len(group)
                summary_rows.append({
                    "encoder": version,
                    "payload_size_bytes": size,
                    "transformation": transform,
                    "n_events": n,
                    "parser_valid_n": sum(bool(r["parser_valid"]) for r in group),
                    "payload_exact_at_original_index_n": sum(
                        bool(r["payload_exact_at_original_index"]) for r in group
                    ),
                    "payload_exact_anywhere_n": sum(
                        bool(r["payload_exact_anywhere"]) for r in group
                    ),
                    "packet_count_preserved_n": sum(
                        bool(r["packet_count_preserved"]) for r in group
                    ),
                    "packet_lengths_preserved_n": sum(
                        bool(r["packet_lengths_preserved"]) for r in group
                    ),
                })

    # Save all tabular outputs.
    write_csv(out / "b18_input_hashes.csv", input_hash_rows)
    write_csv(out / "b18_transformation_results.csv", transformation_rows)
    write_csv(out / "b18_transformation_summary.csv", summary_rows)
    write_csv(out / "b18_decoder_results.csv", decoder_rows)
    write_csv(out / "b18_pcm_pair_audit.csv", pcm_pair_rows)
    if reencode_rows:
        write_csv(out / "b18_codec_reencode_results.csv", reencode_rows)

    config = {
        "experiment": "B18 controlled robustness and failure-mode evaluation",
        "b12_run": str(b12_run),
        "b12_manifest_sha256": manifest_hash,
        "payload_sizes_bytes": list(PAYLOAD_SIZES),
        "repetition": REPETITION,
        "unique_events": 200,
        "events_per_encoder": 100,
        "transformation_types": list(transformation_names),
        "transformation_cases": len(transformation_rows),
        "decoder_sample_per_encoder": args.decoder_sample_per_version,
        "decoder_versions": list(VERSIONS),
        "codec_reencode_sample_per_encoder": (
            0 if args.skip_codec_reencode else args.reencode_sample_per_version
        ),
        "codec_reencode_bitrates": list(BITRATES),
        "codec_reencode_mode": "audio",
        "codec_reencode_complexity": 10,
        "codec_reencode_fec": 0,
        "codec_reencode_packet_loss_percent": 0,
        "source_bitstreams_modified": False,
        "frozen_b12_modified_bitstreams_modified": False,
        "new_transformed_copies_only": True,
        "encoder_binary_sha256": {
            version: sha256_file(ENCODERS[version]) for version in VERSIONS
        },
        "decoder_binary_sha256": {
            version: sha256_file(DECODERS[version]) for version in VERSIONS
        },
    }
    (out / "b18_run_config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    report = [
        "========== B18 ROBUSTNESS AND FAILURE-MODE EVALUATION ==========",
        f"Project: {ROOT}",
        f"Output: {out}",
        f"B12 manifest SHA256: {manifest_hash}",
        "Frozen B9/B12 input bitstreams modified: NO",
        "All transformations were written to new B18 files.",
        f"Selected B12 rows: {len(selected)}",
        "Unique underlying recording events: 200 (100 per encoder)",
        "Payload sizes tested: 32 and 36 bytes",
        f"Transformation cases: {len(transformation_rows)}",
        "",
        "========== TRANSFORMATION SUMMARY ==========",
    ]
    for row in summary_rows:
        n = int(row["n_events"])
        report.append(
            f"{row['encoder']} | {row['payload_size_bytes']}B | "
            f"{row['transformation']} | n={n} | "
            f"parser_valid={row['parser_valid_n']}/{n} | "
            f"payload_at_original_index={row['payload_exact_at_original_index_n']}/{n} | "
            f"payload_anywhere={row['payload_exact_anywhere_n']}/{n} | "
            f"packet_count_preserved={row['packet_count_preserved_n']}/{n}"
        )
    report += [
        "",
        "========== DECODER SAMPLE ==========",
        f"Decoder result rows: {len(decoder_rows)}",
        f"Clean/stego same-decoder PCM pair rows: {len(pcm_pair_rows)}",
        f"Same-decoder PCM-identical pairs: {sum(bool(r['same_decoder_pcm_identical']) for r in pcm_pair_rows)}/{len(pcm_pair_rows)}",
    ]
    if reencode_rows:
        completed = [r for r in reencode_rows if r.get("status") == "COMPLETE"]
        report += [
            "",
            "========== CODEC RE-ENCODING SAMPLE ==========",
            f"Re-encoding result rows: {len(reencode_rows)}",
            f"Completed bitrate trials: {len(completed)}",
            f"Cover/stego decoded PCM identical: {sum(bool(r.get('cover_stego_pcm_identical')) for r in completed)}/{len(completed)}",
            f"Re-encoded cover/stego bitstreams identical: {sum(bool(r.get('reencoded_bitstreams_identical')) for r in completed)}/{len(completed)}",
            f"Exact payload present after re-encoding (stego outputs): {sum(bool(r.get('payload_exact_in_reencoded_stego')) for r in completed)}/{len(completed)}",
            f"Re-encoded stego streams decoded completely: {sum(bool(r.get('reencoded_stego_decode_complete')) for r in completed)}/{len(completed)}",
        ]
    else:
        report += ["", "Codec re-encoding skipped by command-line option."]
    report += [
        "",
        "========== INTERPRETATION LIMITS ==========",
        "- B18 evaluates controlled transformations of the tested B12 bitstreams.",
        "- The 32B and 36B labels follow the B12 manifest; do not equate these labels automatically with application-layer capacity.",
        "- Packet deletion, reordering, truncation and byte flips are controlled file-level packet-sequence mutations, not a full RTP/network simulation.",
        "- A carrier packet that moves may retain the exact payload even when manifest-assisted extraction at its old index fails.",
        "- A bit flip in the payload tests integrity failure, not native Opus error correction.",
        "- Re-encoding is an audio-domain transformation; payload loss is expected because the decoder outputs PCM rather than the original redundant-frame bytes.",
        "- Codec re-encoding uses a small exploratory subset and should not be generalized to every Opus configuration.",
        "- Decoder completion and exact payload recovery are reported as separate outcomes.",
    ]
    (out / "b18_report.txt").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )

    # Remove temporary PCM and logs; preserve transformed and re-encoded bitstreams.
    shutil.rmtree(temp_root, ignore_errors=True)
    write_checksums(out)

    print("\n========== B18 FINAL SUMMARY ==========")
    for row in summary_rows:
        if row["payload_size_bytes"] == 36:
            print(
                f"{row['encoder']} | {row['transformation']} | "
                f"payload at original index "
                f"{row['payload_exact_at_original_index_n']}/{row['n_events']} | "
                f"payload anywhere {row['payload_exact_anywhere_n']}/{row['n_events']}"
            )
    print("\nB18 ROBUSTNESS EVALUATION: COMPLETE")
    print("Output:", out)
    print("Report:", out / "b18_report.txt")
    print("Checksums:", out / "b18_checksums.sha256")


if __name__ == "__main__":
    main()
