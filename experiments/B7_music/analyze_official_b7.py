#!/usr/bin/env python3

import csv
import re
import sys
from pathlib import Path
from collections import defaultdict

if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python3 analyze_official_b7.py OUTPUT_DIRECTORY"
    )

ROOT = Path(sys.argv[1]).resolve()

with open(ROOT / "summary.csv", newline="") as f:
    rows = list(csv.DictReader(f))

if len(rows) != 1998:
    raise SystemExit(f"ERROR: Expected 1998 records, found {len(rows)}")

def fields(line):
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", line))

def analyze_log(path):
    frames = []
    events = []

    with open(path) as f:
        for line in f:
            if line.startswith("RED_FINAL:"):
                frames.append(fields(line))
            elif line.startswith("REDUNDANCY:"):
                events.append(fields(line))

    return frames, events

aggregates = defaultdict(lambda: {
    "files": 0,
    "frames": 0,
    "files_with_events": 0,
    "events": 0,
    "celt_to_silk": 0,
    "relocations": 0
})

event_signatures = {}
issues = []
seen = set()

print("========== B7 INDEPENDENT AUDIT ==========")

for row in rows:

    key = (row["id"], row["version"])

    if key in seen:
        issues.append(f"Duplicate record: {key}")

    seen.add(key)

    version = row["version"]
    genre = row["genre"]
    path = ROOT / row["diagnostics"]

    if not path.exists():
        issues.append(f"Missing diagnostic: {path}")
        continue

    frames, events = analyze_log(path)

    final_map = {
        int(x["frame"]): x for x in frames
    }

    frame_ids = [int(x["frame"]) for x in frames]

    if frame_ids != list(range(len(frame_ids))):
        issues.append(f"Non-contiguous frame IDs: {key}")

    if len(frames) != int(row["frames"]):
        issues.append(f"Frame count mismatch: {key}")

    if len(events) != int(row["redundancy_events"]):
        issues.append(f"Event count mismatch: {key}")

    for event in events:

        fid = int(event["frame_id"])

        if fid not in final_map:
            issues.append(f"Event without final record: {key}, frame {fid}")
            continue

        final = final_map[fid]

        if final["redundancy"] != "1":
            issues.append(f"Redundancy flag mismatch: {key}, frame {fid}")

        if final["celt_to_silk"] != event["celt_to_silk"]:
            issues.append(f"Transition mismatch: {key}, frame {fid}")

    actual_c2s = sum(
        e.get("celt_to_silk") == "1" for e in events
    )

    actual_moved = sum(
        f.get("moved") == "1" for f in frames
    )

    if actual_c2s != int(row["celt_to_silk_events"]):
        issues.append(f"CELT-to-SILK count mismatch: {key}")

    if actual_moved != int(row["successful_relocations"]):
        issues.append(f"Relocation count mismatch: {key}")

    a = aggregates[(version, genre)]

    a["files"] += 1
    a["frames"] += len(frames)
    a["events"] += len(events)
    a["celt_to_silk"] += actual_c2s
    a["relocations"] += actual_moved

    if events:
        a["files_with_events"] += 1

    event_signatures[key] = tuple(
        (
            e["frame_id"],
            e["mode"],
            e["celt_to_silk"],
            e["bytes"]
        )
        for e in events
    )

# Verify 999 unique source recordings.
ids = {r["id"] for r in rows}

if len(ids) != 999:
    issues.append(f"Expected 999 unique files, found {len(ids)}")

for version in ("1.5.2", "1.6.1"):
    count = sum(r["version"] == version for r in rows)
    if count != 999:
        issues.append(f"Incorrect version count: {version} = {count}")

# Genre summary
summary_path = ROOT / "b7_summary_by_genre.csv"

with open(summary_path, "w", newline="") as f:

    columns = [
        "version", "genre", "files", "total_frames",
        "files_with_events", "total_events",
        "celt_to_silk_events", "successful_relocations",
        "events_per_1000_frames"
    ]

    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()

    for (version, genre), a in sorted(aggregates.items()):

        writer.writerow({
            "version": version,
            "genre": genre,
            "files": a["files"],
            "total_frames": a["frames"],
            "files_with_events": a["files_with_events"],
            "total_events": a["events"],
            "celt_to_silk_events": a["celt_to_silk"],
            "successful_relocations": a["relocations"],
            "events_per_1000_frames": (
                round(1000 * a["events"] / a["frames"], 6)
                if a["frames"] else 0
            )
        })

# Cross-version comparison
comparison_path = ROOT / "b7_cross_version_events.csv"

with open(comparison_path, "w", newline="") as f:

    columns = [
        "id", "genre", "events_152", "events_161",
        "signatures_identical", "signature_152", "signature_161"
    ]

    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()

    lookup = {
        (r["id"], r["version"]): r for r in rows
    }

    identical = 0

    for file_id in sorted(ids):

        a = event_signatures.get((file_id, "1.5.2"), ())
        b = event_signatures.get((file_id, "1.6.1"), ())

        same = a == b
        identical += same

        genre = lookup[(file_id, "1.5.2")]["genre"]

        writer.writerow({
            "id": file_id,
            "genre": genre,
            "events_152": len(a),
            "events_161": len(b),
            "signatures_identical": same,
            "signature_152": ";".join(":".join(x) for x in a),
            "signature_161": ";".join(":".join(x) for x in b)
        })

# Final audit
with open(ROOT / "b7_audit_issues.txt", "w") as f:
    f.write("\n".join(issues) if issues else "No audit issues found.\n")

print("Unique recordings:", len(ids))

for version in ("1.5.2", "1.6.1"):

    selected = [
        a for (v, g), a in aggregates.items()
        if v == version
    ]

    print(f"\nOPUS {version}")
    print("Files:", sum(a["files"] for a in selected))
    print("Frames:", sum(a["frames"] for a in selected))
    print("Files with events:",
          sum(a["files_with_events"] for a in selected))
    print("Redundancy events:",
          sum(a["events"] for a in selected))
    print("CELT-to-SILK events:",
          sum(a["celt_to_silk"] for a in selected))
    print("Successful relocations:",
          sum(a["relocations"] for a in selected))

print("\nCross-version identical event signatures:",
      identical, "/", len(ids))

print("\nAudit issues:", len(issues))
print("Genre summary:", summary_path)
print("Cross-version comparison:", comparison_path)
print("Audit report:", ROOT / "b7_audit_issues.txt")

if issues:
    print("\nVALIDATION FAILED")
    sys.exit(1)

print("\nB7 INDEPENDENT VALIDATION PASSED")
