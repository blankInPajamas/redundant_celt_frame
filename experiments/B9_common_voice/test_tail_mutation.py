import struct
import subprocess
import csv
from pathlib import Path

ROOT = Path.cwd()
B9 = ROOT / "experiments/B9_common_voice"

OUT = B9 / "results/b9_full_encoding"
RESULT = OUT / "payload_mutation_smoke"
RESULT.mkdir(parents=True, exist_ok=True)

REC = "common_voice_en_10056233"
FRAME = 1

VERSIONS = ["1.5.2", "1.6.1"]
TAILS = [1, 2, 4, 8, 16, 32, 36]

DECODERS = {
    v: ROOT / f"scripts/decode_raw_{v}"
    for v in VERSIONS
}

PATTERNS = {
    "all_ff": lambda n: bytes([0xFF] * n),
    "incremental": lambda n: bytes(range(1, n + 1)),
    "alternating": lambda n: bytes(
        [0xAA, 0x55][i % 2] for i in range(n)
    )
}


def read_packets(path):
    data = path.read_bytes()
    packets = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length == 0 or offset + length > len(data):
            raise ValueError("Invalid packet length")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


def write_packets(path, packets):
    with open(path, "wb") as f:
        for packet in packets:
            f.write(struct.pack("<I", len(packet)))
            f.write(packet)


def decode(decoder, bitstream, pcm):
    result = subprocess.run(
        [str(decoder), str(bitstream), str(pcm)],
        capture_output=True,
        text=True
    )

    return result.returncode, result.stderr


def compare_pcm(a, b):
    if len(a) != len(b):
        return False, -1, -1

    if len(a) % 2:
        return False, -1, -1

    samples_a = struct.iter_unpack("<h", a)
    samples_b = struct.iter_unpack("<h", b)

    differences = [
        abs(x[0] - y[0])
        for x, y in zip(samples_a, samples_b)
    ]

    count = sum(x != 0 for x in differences)
    maximum = max(differences, default=0)

    return count == 0, count, maximum


rows = []

for enc_version in VERSIONS:

    source = (
        OUT / enc_version / "bitstreams" /
        f"{REC}.bin"
    )

    packets = read_packets(source)

    assert len(packets) > FRAME

    original = packets[FRAME]

    assert len(original) == 87
    assert original[-36:] == bytes(36)
    assert original[-38:-36] == b"\xff\xfe"

    print(f"\n========== ENCODER {enc_version} ==========")

    for dec_version in VERSIONS:

        decoder = DECODERS[dec_version]

        baseline_bin = RESULT / (
            f"baseline_enc{enc_version}.bin"
        )
        baseline_pcm = RESULT / (
            f"baseline_enc{enc_version}_dec{dec_version}.pcm"
        )

        if not baseline_bin.exists():
            write_packets(baseline_bin, packets)

        rc, err = decode(
            decoder, baseline_bin, baseline_pcm
        )

        if rc != 0:
            raise RuntimeError(
                f"Baseline decoding failed: {err}"
            )

        baseline = baseline_pcm.read_bytes()

        print(
            f"\nDecoder {dec_version}: "
            f"baseline={len(baseline)} bytes"
        )

        for tail in TAILS:

            for pattern_name, pattern_fn in PATTERNS.items():

                modified = list(packets)
                packet = bytearray(original)

                payload = pattern_fn(tail)
                packet[-tail:] = payload

                modified[FRAME] = bytes(packet)

                tag = (
                    f"enc{enc_version}_dec{dec_version}_"
                    f"tail{tail}_{pattern_name}"
                )

                bitstream = RESULT / f"{tag}.bin"
                pcm = RESULT / f"{tag}.pcm"

                write_packets(bitstream, modified)

                rc, err = decode(decoder, bitstream, pcm)

                if rc == 0 and pcm.exists():

                    decoded = pcm.read_bytes()

                    identical, different, max_diff = (
                        compare_pcm(baseline, decoded)
                    )

                else:
                    identical = False
                    different = -1
                    max_diff = -1

                status = (
                    "IDENTICAL"
                    if identical else
                    "DIFFERENT_OR_FAILED"
                )

                print(
                    f"{tag} | {status} | "
                    f"different_samples={different} | "
                    f"max_diff={max_diff}"
                )

                rows.append({
                    "encoder": enc_version,
                    "decoder": dec_version,
                    "tail_bytes": tail,
                    "pattern": pattern_name,
                    "decoder_return": rc,
                    "pcm_identical": identical,
                    "different_samples": different,
                    "max_sample_difference": max_diff
                })


with open(RESULT / "mutation_results.csv", "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=rows[0].keys()
    )

    writer.writeheader()
    writer.writerows(rows)

print("\n========== MUTATION TEST COMPLETE ==========")
print("Tests:", len(rows))
print("Results:", RESULT / "mutation_results.csv")

print(
    "PCM-identical tests:",
    sum(r["pcm_identical"] for r in rows),
    "/", len(rows)
)
