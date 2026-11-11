#!/usr/bin/env python3

import csv
import re
import struct
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
OUT = BASE / "results/b9_full_encoding"
DEST = OUT / "payload_preflight"

VERSIONS = ["1.5.2", "1.6.1"]
THRESHOLDS = [20, 27, 36]

DEST.mkdir(parents=True, exist_ok=True)


def parse_fields(line):
    return {
        k: int(v)
        for k, v in re.findall(r"([A-Za-z_]+)=(-?\d+)", line)
    }


def load_packets(path):
    data = path.read_bytes()
    packets = []
    offset = 0

    while offset < len(data):

        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        length = struct.unpack_from("<i", data, offset)[0]
        offset += 4

        if length <= 0 or offset + length > len(data):
            raise ValueError("Invalid packet length")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


def trailing_zeros(packet):
    count = 0

    for byte in reversed(packet):
        if byte != 0:
            break
        count += 1

    return count


event_rows = []
recording_rows = []

for version in VERSIONS:

    version_dir = OUT / version
    bin_dir = version_dir / "bitstreams"
    log_dir = version_dir / "diagnostics"

    logs = sorted(log_dir.glob("*.log"))

    logs = [
        p for p in logs
        if not p.name.endswith(".failed.log")
    ]

    stats = defaultdict(int)
    event_tails = []

    print(f"\n========== OPUS {version} ==========")

    for log_path in logs:

        recording = log_path.stem
        bin_path = bin_dir / f"{recording}.bin"

        if not bin_path.exists():
            stats["missing_bitstreams"] += 1
            continue

        try:
            packets = load_packets(bin_path)
        except Exception as exc:
            stats["invalid_bitstreams"] += 1
            print("INVALID:", recording, exc)
            continue

        tails = [trailing_zeros(p) for p in packets]

        for threshold in THRESHOLDS:
            stats[f"all_packets_ge_{threshold}"] += sum(
                t >= threshold for t in tails
            )

        events = []
        finals = defaultdict(list)

        with open(log_path, errors="replace") as f:

            for line in f:

                if line.startswith("REDUNDANCY:"):
                    fields = parse_fields(line)

                    if fields.get("celt_to_silk") == 1:
                        events.append(fields)

                elif line.startswith("RED_FINAL:"):
                    fields = parse_fields(line)
                    finals[fields["frame"]].append(fields)

        rec_event_counts = defaultdict(int)

        for event in events:

            frame = event["frame_id"]
            rec_event_counts["cts_events"] += 1
            stats["cts_events"] += 1

            if not 0 <= frame < len(packets):
                stats["invalid_event_frames"] += 1
                continue

            packet = packets[frame]
            tail = tails[frame]

            matching = finals.get(frame, [])

            final = next(
                (
                    x for x in matching
                    if x.get("celt_to_silk") == 1
                ),
                {}
            )

            moved = final.get("moved", 0)
            size = final.get("redundancy_size", -1)

            relocation_ok = (
                moved == 1
                and final.get("celt_to_silk") == 1
                and size == event["bytes"]
                and final.get("final_packet_end") == len(packet)
                and final.get("packet_return_length") == len(packet)
            )

            if not final:
                stats["missing_final_records"] += 1

            if relocation_ok:
                stats["validated_relocations"] += 1

            event_tails.append(tail)

            row = {
                "version": version,
                "recording_id": recording,
                "frame_id": frame,
                "mode": event["mode"],
                "redundancy_bytes": event["bytes"],
                "packet_length": len(packet),
                "trailing_zero_bytes": tail,
                "final_record_found": bool(final),
                "moved": moved,
                "relocation_consistent": relocation_ok,
                "final_packet_offset": final.get(
                    "final_packet_offset", -1
                ),
                "final_packet_end": final.get(
                    "final_packet_end", -1
                )
            }

            for threshold in THRESHOLDS:
                row[f"tail_ge_{threshold}"] = int(
                    tail >= threshold
                )

                if tail >= threshold:
                    stats[f"cts_frames_ge_{threshold}"] += 1
                    rec_event_counts[
                        f"cts_frames_ge_{threshold}"
                    ] += 1

            event_rows.append(row)

        rec_row = {
            "version": version,
            "recording_id": recording,
            "packet_count": len(packets),
            "cts_events": rec_event_counts["cts_events"],
        }

        for threshold in THRESHOLDS:
            rec_row[f"all_packets_ge_{threshold}"] = sum(
                t >= threshold for t in tails
            )

            rec_row[f"cts_frames_ge_{threshold}"] = (
                rec_event_counts[f"cts_frames_ge_{threshold}"]
            )

        recording_rows.append(rec_row)

        stats["recordings"] += 1

    print("Recordings audited:", stats["recordings"])
    print("Missing bitstreams:", stats["missing_bitstreams"])
    print("Invalid bitstreams:", stats["invalid_bitstreams"])
    print("CELT-to-SILK events:", stats["cts_events"])
    print("Validated relocations:", stats["validated_relocations"])

    for threshold in THRESHOLDS:
        print(
            f"CTS event frames with >= {threshold} trailing zeros:",
            stats[f"cts_frames_ge_{threshold}"]
        )

    if event_tails:
        print("Maximum CTS-frame tail:", max(event_tails))
        print(
            "CTS frames with zero tail:",
            sum(t > 0 for t in event_tails),
            "/", len(event_tails)
        )


def write_csv(path, rows):

    if not rows:
        raise SystemExit(f"No results to write: {path}")

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


write_csv(
    DEST / "b9_payload_event_candidates.csv",
    event_rows
)

write_csv(
    DEST / "b9_payload_recording_candidates.csv",
    recording_rows
)

print("\n========== FINAL PAYLOAD PREFLIGHT ==========")
print("Event records:", len(event_rows))
print("Recording records:", len(recording_rows))
print("Output:", DEST)
print("B9 PAYLOAD CANDIDATE AUDIT: COMPLETE")
