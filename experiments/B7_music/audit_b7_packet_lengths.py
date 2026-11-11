import csv
import struct
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

OUT = ROOT / "logs/phase_b/B7_official_20261103_020241"
TEST = OUT / "b7_zero_tail_payload_test"

MESSAGE = b"B7-MUSIC-TAIL-CHANNEL-TEST-2026-001"
PAYLOAD = bytes([len(MESSAGE)]) + MESSAGE


def packets(path):
    data = path.read_bytes()
    result = []
    offset = 0

    while offset < len(data):
        n = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if n <= 0 or offset + n > len(data):
            raise ValueError(f"Invalid framing: {path}")

        result.append(data[offset:offset+n])
        offset += n

    return result


with (OUT / "summary.csv").open(newline="") as f:
    summary = {
        (r["version"], r["id"]): r
        for r in csv.DictReader(f)
    }

with (TEST / "results.csv").open(newline="") as f:
    results = list(csv.DictReader(f))

audit = []

for r in results:

    version = r["version"]
    name = r["id"]
    frame = int(r["frame"])

    original = OUT / summary[(version, name)]["bitstream"]

    stego = (
        TEST / "stego" / version /
        f"{name}_f{frame}.bin"
    )

    a = packets(original)
    b = packets(stego)

    count_ok = len(a) == len(b)

    lengths_ok = (
        count_ok
        and [len(p) for p in a] == [len(p) for p in b]
    )

    file_size_ok = original.stat().st_size == stego.stat().st_size

    payload_ok = (
        b[frame][-36:] == PAYLOAD
    )

    original_tail_zero = (
        a[frame][-36:] == bytes(36)
    )

    other_packets_unchanged = all(
        a[i] == b[i]
        for i in range(len(a))
        if i != frame
    )

    target_prefix_unchanged = (
        a[frame][:-36] == b[frame][:-36]
    )

    audit.append({
        "version": version,
        "recording": name,
        "packet_count_same": count_ok,
        "packet_lengths_same": lengths_ok,
        "file_size_same": file_size_ok,
        "original_tail_zero": original_tail_zero,
        "payload_correct": payload_ok,
        "other_packets_unchanged": other_packets_unchanged,
        "target_prefix_unchanged": target_prefix_unchanged
    })


output = TEST / "independent_packet_audit.csv"

with output.open("w", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=list(audit[0])
    )
    writer.writeheader()
    writer.writerows(audit)


print("========== INDEPENDENT B7 PACKET AUDIT ==========")
print("Total:", len(audit))

for key in audit[0]:
    if key in ("version", "recording"):
        continue

    passed = sum(x[key] for x in audit)
    print(f"{key}: {passed}/{len(audit)}")

print("Saved:", output)
