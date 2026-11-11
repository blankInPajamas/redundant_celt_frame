
#!/usr/bin/env python3

import csv
import struct
import sys
import re
import math
import hashlib

from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(sys.argv[1])

def parse_fields(line):
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", line))

def load_packets(path):

    data = path.read_bytes()
    packets = []
    offset = 0

    while offset < len(data):

        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if size == 0 or offset + size > len(data):
            raise ValueError("Invalid packet length")

        packets.append(data[offset:offset + size])
        offset += size

    return packets

def entropy(data):

    if not data:
        return 0.0

    counts = Counter(data)
    n = len(data)

    return -sum(
        (c / n) * math.log2(c / n)
        for c in counts.values()
    )

with open(ROOT / "summary.csv") as f:
    rows = list(csv.DictReader(f))

records = []
issues = []
relocation_files = defaultdict(set)

for row in rows:

    version = row["version"]
    file_id = row["id"]

    bitstream = ROOT / row["bitstream"]
    diagnostic = ROOT / row["diagnostics"]

    packets = load_packets(bitstream)

    with open(diagnostic) as f:

        lines = f.readlines()

    events = [
        parse_fields(x)
        for x in lines
        if x.startswith("REDUNDANCY:")
    ]

    finals = {
        int(parse_fields(x)["frame"]): parse_fields(x)
        for x in lines
        if x.startswith("RED_FINAL:")
    }

    if len(packets) != len(finals):
        issues.append(
            f"{file_id} {version}: packet/frame mismatch"
        )

    for event in events:

        if event["celt_to_silk"] != "1":
            continue

        frame = int(event["frame_id"])

        final = finals.get(frame)

        if final is None:
            issues.append(
                f"{file_id} {version}: missing final frame"
            )
            continue

        if final["moved"] != "1":
            issues.append(
                f"{file_id} {version}: relocation not confirmed"
            )
            continue

        packet = packets[frame]

        start = int(final["final_packet_offset"])
        end = int(final["final_packet_end"])
        size = int(final["redundancy_size"])

        if end - start != size:
            issues.append(
                f"{file_id} {version}: offset/size mismatch"
            )
            continue

        if start < 0 or end > len(packet):
            issues.append(
                f"{file_id} {version}: region outside packet"
            )
            continue

        region = packet[start:end]

        if len(region) != size:
            issues.append(
                f"{file_id} {version}: incorrect region length"
            )
            continue

        zero_count = region.count(0)

        zero_suffix = len(region) - len(
            region.rstrip(b"\x00")
        )

        digest = hashlib.sha256(region).hexdigest()

        records.append({
            "id": file_id,
            "genre": row["genre"],
            "version": version,
            "frame": frame,
            "packet_length": len(packet),
            "offset": start,
            "size": size,
            "zero_bytes": zero_count,
            "zero_fraction": round(zero_count / size, 4),
            "zero_suffix": zero_suffix,
            "entropy": round(entropy(region), 5),
            "first16_hex": region[:16].hex(),
            "region_sha256": digest,
            "all_zero": zero_count == size
        })

        relocation_files[version].add(file_id)

output = ROOT / "b7_relocation_regions.csv"

with open(output, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=records[0].keys()
        if records else []
    )

    writer.writeheader()
    writer.writerows(records)

# Compare corresponding regions between versions.

lookup = {
    (r["id"], r["frame"], r["version"]): r
    for r in records
}

paired = 0
identical = 0

for key in sorted({
    (r["id"], r["frame"])
    for r in records
}):

    a = lookup.get((*key, "1.5.2"))
    b = lookup.get((*key, "1.6.1"))

    if a is None or b is None:
        continue

    paired += 1

    if a["region_sha256"] == b["region_sha256"]:
        identical += 1

print("========== B7 REGION AUDIT ==========")
print("Region records:", len(records))
print("1.5.2 relocation files:", len(relocation_files["1.5.2"]))
print("1.6.1 relocation files:", len(relocation_files["1.6.1"]))

print("\nPaired regions:", paired)
print("Byte-identical regions:", identical)

if paired:
    print("Region identity rate:", round(100 * identical / paired, 2), "%")

print("\n========== REGION CHARACTERISTICS ==========")

for version in ("1.5.2", "1.6.1"):

    selected = [
        r for r in records
        if r["version"] == version
    ]

    print("\nOpus", version)
    print("Regions:", len(selected))
    print("Total bytes:", sum(r["size"] for r in selected))
    print("Zero bytes:", sum(r["zero_bytes"] for r in selected))
    print("Completely zero regions:",
          sum(r["all_zero"] for r in selected))
    print("Mean zero fraction:",
          round(
              sum(r["zero_fraction"] for r in selected) /
              len(selected), 4
          ) if selected else 0)

print("\nAudit issues:", len(issues))

for issue in issues:
    print("ISSUE:", issue)

print("\nSaved:", output)
