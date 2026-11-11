#!/usr/bin/env python3
"""Read-only preflight for B11 payload-reliability testing."""

import csv
import hashlib
import struct
import sys
from pathlib import Path

VERSIONS = ("1.5.2", "1.6.1")
TAIL_BYTES = 36
PILOT_PER_VERSION = 10


def read_packets(path):
    data = path.read_bytes()
    packets = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"{path}: incomplete packet-length header")
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if length <= 0 or offset + length > len(data):
            raise ValueError(f"{path}: invalid/truncated packet")
        packets.append(data[offset:offset + length])
        offset += length
    return packets


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def evenly_spaced(rows, count):
    rows = sorted(rows, key=lambda r: r["recording"])
    if len(rows) <= count:
        return rows
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[i] for i in indices]


def main():
    root = Path(__file__).resolve().parents[1]
    b9 = root / "experiments/B9_common_voice"
    base = b9 / "results/b9_full_encoding"
    manifest_path = base / "payload_roundtrip_100speaker/b9_payload_manifest.csv"

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    with manifest_path.open(newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    if len(manifest) != 200:
        raise ValueError(f"Expected 200 manifest rows; found {len(manifest)}")

    source_hash_lines = []
    summaries = []
    pilot_rows = {}

    for version in VERSIONS:
        rows = [r for r in manifest if r["encoder"] == version]
        if len(rows) != 100:
            raise ValueError(f"Encoder {version}: expected 100 rows, found {len(rows)}")
        if len({r["recording"] for r in rows}) != 100:
            raise ValueError(f"Encoder {version}: recording IDs are not unique")
        if len({r["speaker"] for r in rows}) != 100:
            raise ValueError(f"Encoder {version}: speaker IDs are not unique")

        for row in rows:
            payload = bytes.fromhex(row["payload_hex"])
            if len(payload) != TAIL_BYTES:
                raise ValueError(f"{version}/{row['recording']}: payload is not 36 bytes")
            if sha256(payload) != row["payload_sha256"].lower():
                raise ValueError(f"{version}/{row['recording']}: payload SHA256 mismatch")
            if row["extraction_exact"].lower() != "true":
                raise ValueError(f"{version}/{row['recording']}: prior extraction was not exact")
            if row["packet_lengths_preserved"].lower() != "true":
                raise ValueError(f"{version}/{row['recording']}: prior framing audit failed")

            bitstream = base / version / "bitstreams" / f"{row['recording']}.bin"
            if not bitstream.is_file():
                raise FileNotFoundError(bitstream)

            packets = read_packets(bitstream)
            frame = int(row["frame"])
            if not 0 <= frame < len(packets):
                raise ValueError(f"{bitstream}: target frame {frame} is outside packet range")
            packet = packets[frame]
            if len(packet) < TAIL_BYTES or packet[-TAIL_BYTES:] != bytes(TAIL_BYTES):
                raise ValueError(
                    f"{bitstream}: target packet does not end in 36 zero bytes"
                )

            rel = bitstream.relative_to(root)
            source_hash_lines.append(f"{sha256(bitstream.read_bytes())}  {rel}")

        chosen = evenly_spaced(rows, PILOT_PER_VERSION)
        pilot_rows[version] = chosen
        summaries.append(
            f"{version}: {len(rows)} events; 100 unique recordings; "
            f"100 unique speakers; {len(rows)} source bitstreams validated"
        )

    decoder_checks = []
    for version in VERSIONS:
        decoder = root / f"scripts/decode_raw_{version}"
        if not decoder.is_file() or not (decoder.stat().st_mode & 0o111):
            raise ValueError(f"Missing or non-executable decoder: {decoder}")
        if b"B10|mode=" not in decoder.read_bytes():
            raise ValueError(f"Decoder lacks B10 extraction instrumentation: {decoder}")
        decoder_checks.append(f"{version}: instrumented decoder present")

    out_dir = b9 / "results/b11_payload_reliability"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "b11_source_bitstreams.sha256").write_text(
        "\n".join(sorted(source_hash_lines)) + "\n", encoding="utf-8"
    )

    report = [
        "========== B11 PAYLOAD RELIABILITY PREFLIGHT ==========",
        "READ-ONLY CHECK: source bitstreams were not modified.",
        f"Manifest: {manifest_path}",
        f"Manifest records: {len(manifest)}",
        "",
        "========== SOURCE EVENT VALIDATION ==========",
        *summaries,
        "Target packets ending in 36 zero bytes: 200/200",
        "Manifest payload SHA256 checks: 200/200",
        "Source bitstream SHA256 inventory: b11_source_bitstreams.sha256",
        "",
        "========== DECODER VALIDATION ==========",
        *decoder_checks,
        "",
        "========== B11 PILOT SAMPLE ==========",
        f"Selected {PILOT_PER_VERSION} evenly spaced events per encoder version.",
    ]

    for version in VERSIONS:
        report.append(f"{version}:")
        for row in pilot_rows[version]:
            report.append(
                f"  {row['recording']} | frame={row['frame']} | "
                f"speaker_sha256={row['speaker'][:16]}..."
            )

    report += [
        "",
        "Planned pilot: payload sizes 4, 8, 16, 24, 32, and 36 bytes;",
        "3 independent payload repetitions per event-size pair;",
        "both decoder versions; one-bit corruption/integrity controls;",
        "37-byte over-capacity rejection; baseline-versus-modified PCM comparison.",
        "",
        "B11 PREFLIGHT: PASS",
    ]

    report_path = out_dir / "b11_preflight_report.txt"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print("\n".join(report))
    print(f"\nSaved report: {report_path}")
    print(f"Saved source hashes: {out_dir / 'b11_source_bitstreams.sha256'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"B11 PREFLIGHT: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
