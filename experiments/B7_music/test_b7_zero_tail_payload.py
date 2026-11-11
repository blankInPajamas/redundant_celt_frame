#!/usr/bin/env python3

import csv
import hashlib
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

OUT = ROOT / "logs/phase_b/B7_official_20261103_020241"

TEST = OUT / "b7_zero_tail_payload_test"

MESSAGE = b"B7-MUSIC-TAIL-CHANNEL-TEST-2026-001"
BLOCK = bytes([len(MESSAGE)]) + MESSAGE

assert len(MESSAGE) == 35
assert len(BLOCK) == 36


def fields(line):
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", line))


def load_packets(path):

    data = path.read_bytes()
    packets = []
    off = 0

    while off < len(data):

        if off + 4 > len(data):
            raise ValueError("Bad packet header")

        n = struct.unpack_from("<I", data, off)[0]
        off += 4

        if n <= 0 or off + n > len(data):
            raise ValueError("Bad packet length")

        packets.append(bytearray(data[off:off+n]))
        off += n

    return packets


def save_packets(path, packets):

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("wb") as f:
        for p in packets:
            f.write(struct.pack("<I", len(p)))
            f.write(p)


def decode(decoder, stream, pcm):

    pcm.parent.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [str(decoder), str(stream), str(pcm)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
    )

    return p.returncode == 0 and pcm.exists()


if TEST.exists():
    raise SystemExit(f"Output already exists: {TEST}")

TEST.mkdir(parents=True)

with (OUT / "summary.csv").open(newline="") as f:
    summaries = {
        (r["version"], r["id"]): r
        for r in csv.DictReader(f)
    }

with (OUT / "b7_relocation_regions.csv").open(newline="") as f:
    all_regions = list(csv.DictReader(f))

region_map = {
    (r["version"], r["id"], int(r["frame"])): r
    for r in all_regions
}

candidates = [
    r for r in all_regions
    if r["version"] == "1.5.2"
    and int(r["zero_suffix"]) == 36
]

if len(candidates) != 10:
    raise SystemExit(
        f"Expected 10 candidates, found {len(candidates)}"
    )

results = []
baseline_cache = {}

for seed in candidates:

    file_id = seed["id"]
    frame = int(seed["frame"])

    for version in ("1.5.2", "1.6.1"):

        row = region_map[(version, file_id, frame)]
        s = summaries[(version, file_id)]

        stream = OUT / s["bitstream"]
        log = OUT / s["diagnostics"]

        decoder = ROOT / "scripts" / f"decode_raw_{version}"

        if not decoder.exists():
            raise FileNotFoundError(decoder)

        final = next(
            (
                fields(x)
                for x in log.read_text(errors="replace").splitlines()
                if x.startswith("RED_FINAL:")
                and int(fields(x).get("frame", "-1")) == frame
            ),
            None
        )

        if not final:
            raise ValueError("Missing RED_FINAL")

        if not (
            final.get("redundancy") == "1"
            and final.get("celt_to_silk") == "1"
            and final.get("moved") == "1"
        ):
            raise ValueError("Invalid relocation event")

        packets = load_packets(stream)
        pkt = packets[frame]

        start = int(final["final_packet_offset"])
        end = int(final["final_packet_end"])
        size = int(final["redundancy_size"])

        if (
            size != 38
            or end != len(pkt)
            or end - start != 38
            or start + 2 != end - 36
            or int(final["packet_return_length"]) != len(pkt)
        ):
            raise ValueError("Unexpected packet geometry")

        if hashlib.sha256(
            bytes(pkt[start:end])
        ).hexdigest() != row["region_sha256"]:
            raise ValueError("Region hash mismatch")

        if bytes(pkt[-36:]) != bytes(36):
            raise ValueError("Expected 36 zero bytes")

        key = (version, file_id)

        if key not in baseline_cache:

            base_pcm = (
                TEST / "baseline" / version / f"{file_id}.pcm"
            )

            if not decode(decoder, stream, base_pcm):
                raise RuntimeError("Baseline decoding failed")

            baseline_cache[key] = base_pcm

        modified = [bytearray(p) for p in packets]

        modified[frame][-36:] = BLOCK

        stego = (
            TEST / "stego" / version
            / f"{file_id}_f{frame}.bin"
        )

        stego_pcm = (
            TEST / "decoded" / version
            / f"{file_id}_f{frame}.pcm"
        )

        save_packets(stego, modified)

        ok = decode(decoder, stego, stego_pcm)

        recovered = (
            bytes(load_packets(stego)[frame][-36:]) == BLOCK
        )

        identical = (
            ok
            and baseline_cache[key].read_bytes()
            == stego_pcm.read_bytes()
        )

        results.append({
            "version": version,
            "id": file_id,
            "frame": frame,
            "decode_success": ok,
            "payload_recovered": recovered,
            "pcm_byte_identical": identical,
            "packet_length_preserved": True
        })


result_file = TEST / "results.csv"

with result_file.open("w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(results[0])
    )

    writer.writeheader()
    writer.writerows(results)


print("========== B7 ZERO-TAIL PAYLOAD TEST ==========")
print("Trials:", len(results))

for col in (
    "decode_success",
    "payload_recovered",
    "pcm_byte_identical",
    "packet_length_preserved"
):

    print(
        f"{col}: "
        f"{sum(r[col] for r in results)}/{len(results)}"
    )

print("Results:", result_file)

for version in ("1.5.2", "1.6.1"):

    subset = [
        r for r in results
        if r["version"] == version
    ]

    print(
        version,
        "PCM-identical:",
        sum(r["pcm_byte_identical"] for r in subset),
        "/",
        len(subset)
    )

