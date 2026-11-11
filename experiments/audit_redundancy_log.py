#!/usr/bin/env python3

import re
import sys
from pathlib import Path


def audit(log_path):
    path = Path(log_path)
    records = []

    for line in path.read_text(errors="replace").splitlines():

        if "RED_FINAL:" not in line:
            continue

        fields = {
            key: int(value)
            for key, value in re.findall(
                r"([A-Za-z_]+)=(-?\d+)",
                line.split("RED_FINAL:", 1)[1]
            )
        }

        required = {
            "mode",
            "redundancy",
            "celt_to_silk",
            "moved",
            "redundancy_size",
            "packet_return_length"
        }

        if not required.issubset(fields):
            raise ValueError(
                f"Incomplete RED_FINAL record: {line}"
            )

        records.append({
            "frame": fields.get("frame", len(records)),
            **fields
        })

    if not records:
        raise ValueError(f"No RED_FINAL records found in {path}")

    hybrid = [
        r for r in records
        if r["mode"] == 1001
    ]

    events = [
        r for r in records
        if r["redundancy"] == 1
    ]

    transitions = [
        r for r in events
        if r["celt_to_silk"] == 1
    ]

    relocations = [
        r for r in transitions
        if r["moved"] == 1
        and r["redundancy_size"] > 0
    ]

    print("\n===================================")
    print("AUDIT:", path.name)
    print("===================================")

    print("Total encoded frames:", len(records))
    print("Hybrid-mode frames:", len(hybrid))
    print("Actual redundancy events:", len(events))
    print("CELT-to-SILK events:", len(transitions))
    print("Successful relocations:", len(relocations))

    for event in events:
        print("\nActual event:")
        print("Frame:", event["frame"])
        print("Packet length:", event["packet_return_length"])
        print("Redundancy size:", event["redundancy_size"])
        print("Write offset:", event.get("write_packet_offset"))
        print("Final offset:", event.get("final_packet_offset"))


if __name__ == "__main__":

    if len(sys.argv) < 2:
        sys.exit(
            "Usage: python3 audit_redundancy_log.py LOG1 [LOG2 ...]"
        )

    for filename in sys.argv[1:]:
        audit(filename)
