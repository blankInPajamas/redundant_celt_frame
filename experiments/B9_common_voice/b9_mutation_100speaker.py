import csv
import re
import struct
import random
import hashlib
import tempfile
import subprocess

from pathlib import Path

ROOT = Path.cwd()
B9 = ROOT / "experiments/B9_common_voice"
OUT = B9 / "results/b9_full_encoding"

RESULT = OUT / "payload_mutation_100speaker"
RESULT.mkdir(parents=True, exist_ok=True)

VERSIONS = ["1.5.2", "1.6.1"]
DECODERS = {
    v: ROOT / f"scripts/decode_raw_{v}"
    for v in VERSIONS
}

N_SPEAKERS = 100
PAYLOAD_SIZE = 36
SEED = 20261103

FINAL_RE = re.compile(
    r"RED_FINAL: frame=(\d+).*?"
    r"redundancy=(\d+).*?"
    r"celt_to_silk=(\d+).*?"
    r"final_packet_offset=(-?\d+).*?"
    r"final_packet_end=(-?\d+).*?"
    r"redundancy_size=(-?\d+).*?"
    r"moved=(\d+)"
)


def read_packets(path):
    data = path.read_bytes()
    packets = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length <= 0 or offset + length > len(data):
            raise ValueError("Invalid packet")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


def write_packets(path, packets):
    with open(path, "wb") as f:
        for packet in packets:
            f.write(struct.pack("<I", len(packet)))
            f.write(packet)


def decode(decoder, bitstream, pcm):
    p = subprocess.run(
        [str(decoder), str(bitstream), str(pcm)],
        capture_output=True
    )
    return p.returncode


# Load speaker mapping
manifest = OUT / "input_manifest.tsv"

with open(manifest) as f:
    rows = csv.DictReader(f, delimiter="\t")
    speaker_map = {
        r["recording_id"]: r["speaker_id"]
        for r in rows
    }


all_candidates = {}
statistics = {}

# Independently inspect every CTS event
for version in VERSIONS:

    candidates = []
    total = 0
    zero = 0
    intermediate = 0
    full36 = 0

    base = OUT / version

    for log in (base / "diagnostics").glob("*.log"):

        recording = log.stem
        bitstream = base / "bitstreams" / f"{recording}.bin"

        if not bitstream.exists():
            continue

        packets = None

        with open(log, errors="replace") as f:

            for line in f:

                m = FINAL_RE.search(line)

                if not m:
                    continue

                frame, redundancy, cts, offset, end, size, moved = (
                    map(int, m.groups())
                )

                if not (
                    redundancy == 1
                    and cts == 1
                    and moved == 1
                ):
                    continue

                total += 1

                if packets is None:
                    packets = read_packets(bitstream)

                if frame >= len(packets):
                    raise ValueError(
                        f"Invalid frame: {recording} {frame}"
                    )

                packet = packets[frame]

                tail = len(packet) - len(packet.rstrip(b"\x00"))

                if tail == 0:
                    zero += 1
                elif tail >= 36:
                    full36 += 1
                else:
                    intermediate += 1

                if (
                    size == 38
                    and offset == len(packet) - 38
                    and end == len(packet)
                    and tail >= PAYLOAD_SIZE
                    and packet[-PAYLOAD_SIZE:] == bytes(PAYLOAD_SIZE)
                ):
                    candidates.append({
                        "version": version,
                        "recording": recording,
                        "speaker": speaker_map.get(recording, ""),
                        "frame": frame
                    })

    statistics[version] = {
        "total": total,
        "zero": zero,
        "intermediate": intermediate,
        "full36": full36,
        "candidates": len(candidates)
    }

    all_candidates[version] = candidates

    print(f"\n========== {version} ==========")
    print("Total CTS events:", total)
    print("Zero trailing bytes:", zero)
    print("1-35 trailing zeros:", intermediate)
    print("36+ trailing zeros:", full36)
    print("Structurally eligible:", len(candidates))

# Select one event per speaker
selected = {}

rng = random.Random(SEED)

for version in VERSIONS:

    candidates = all_candidates[version]
    rng.shuffle(candidates)

    by_speaker = {}

    for c in candidates:
        if c["speaker"]:
            by_speaker.setdefault(c["speaker"], c)

    chosen = list(by_speaker.values())
    rng.shuffle(chosen)

    selected[version] = chosen[:N_SPEAKERS]

    print(
        f"{version}: selected "
        f"{len(selected[version])} unique speakers"
    )

    if len(selected[version]) < N_SPEAKERS:
        print("WARNING: Fewer than 100 eligible speakers")

# Perform mutations and cross-decoder comparisons
results = []

for version in VERSIONS:

    base = OUT / version

    print(f"\n========== TESTING ENCODER {version} ==========")

    for index, candidate in enumerate(selected[version], 1):

        recording = candidate["recording"]
        frame = candidate["frame"]
        speaker = candidate["speaker"]

        original_bin = (
            base / "bitstreams" / f"{recording}.bin"
        )

        packets = read_packets(original_bin)
        original_packet = packets[frame]

        assert original_packet[-36:] == bytes(36)

        payload = hashlib.shake_256(
            f"{SEED}|{version}|{recording}|{frame}".encode()
        ).digest(36)

        modified = list(packets)

        packet = bytearray(original_packet)
        packet[-36:] = payload
        modified[frame] = bytes(packet)

        assert modified[frame][-36:] == payload
        assert [len(p) for p in packets] == [
            len(p) for p in modified
        ]

        with tempfile.TemporaryDirectory(
            dir=RESULT
        ) as temp:

            temp = Path(temp)

            modified_bin = temp / "modified.bin"
            write_packets(modified_bin, modified)

            for decoder_version in VERSIONS:

                decoder = DECODERS[decoder_version]

                baseline_pcm = temp / "baseline.pcm"
                modified_pcm = temp / "modified.pcm"

                rc1 = decode(
                    decoder, original_bin, baseline_pcm
                )

                rc2 = decode(
                    decoder, modified_bin, modified_pcm
                )

                identical = False
                base_size = 0
                modified_size = 0

                if (
                    rc1 == 0
                    and rc2 == 0
                    and baseline_pcm.exists()
                    and modified_pcm.exists()
                ):

                    a = baseline_pcm.read_bytes()
                    b = modified_pcm.read_bytes()

                    base_size = len(a)
                    modified_size = len(b)

                    identical = a == b

                results.append({
                    "encoder": version,
                    "decoder": decoder_version,
                    "recording": recording,
                    "speaker": speaker,
                    "frame": frame,
                    "payload_bytes": 36,
                    "baseline_rc": rc1,
                    "modified_rc": rc2,
                    "baseline_pcm_bytes": base_size,
                    "modified_pcm_bytes": modified_size,
                    "pcm_identical": identical
                })

        if index % 10 == 0:
            print(f"Processed {index}/{len(selected[version])}")

# Save results
output = RESULT / "b9_100speaker_mutation.csv"

with open(output, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)

passed = sum(r["pcm_identical"] for r in results)

print("\n========== FINAL AUDIT ==========")
print("Total decoding comparisons:", len(results))
print("Exact PCM matches:", passed)
print("Failed comparisons:", len(results) - passed)
print("Results:", output)

if passed == len(results):
    print("B9 100-SPEAKER MUTATION AUDIT: PASS")
else:
    print("B9 100-SPEAKER MUTATION AUDIT: INVESTIGATE")
