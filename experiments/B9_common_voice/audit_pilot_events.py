import csv
import re
import sys
from pathlib import Path
from collections import Counter

BASE = Path(sys.argv[1])

PILOT = BASE / "pilot/pilot100_pcm_files.txt"
OUT = BASE / "results/b9_pilot_encoding"

def parse_fields(line):
    return dict(re.findall(r'(\w+)=([^\s]+)', line))

names = PILOT.read_text().splitlines()

event_rows = []
paired_rows = []
version_data = {}

for version in ["1.5.2", "1.6.1"]:

    version_data[version] = {}

    for name in names:

        stem = name.removesuffix(".pcm")

        log = OUT / version / "diagnostics" / f"{stem}.log"

        lines = log.read_text(errors="replace").splitlines()

        events = []
        finals = []

        for line in lines:

            if line.startswith("REDUNDANCY:"):
                events.append(parse_fields(line))

            elif line.startswith("RED_FINAL:"):
                finals.append(parse_fields(line))

        final_map = {}

        for i, f in enumerate(finals):
            key = (f.get("frame"), f.get("mode"))
            final_map.setdefault(key, []).append((i, f))

        used = set()
        signatures = []

        for e in events:

            frame = e.get("frame_id")
            mode = e.get("mode")
            direction = int(e.get("celt_to_silk", -1))
            size = int(e.get("bytes", -1))

            key = (frame, mode)

            candidates = final_map.get(key, [])

            match = next(
                (
                    (i, f) for i, f in candidates
                    if i not in used and f.get("redundancy") == "1"
                ),
                None
            )

            if match:
                idx, final = match
                used.add(idx)
            else:
                final = {}

            final_direction = int(
                final.get("celt_to_silk", -1)
            ) if final else -1

            final_size = int(
                final.get("redundancy_size", -1)
            ) if final else -1

            moved = int(final.get("moved", 0)) if final else 0

            consistent = (
                bool(final)
                and final_direction == direction
                and final_size == size
                and moved in (0, 1)
            )

            if direction == 1:
                signatures.append((frame, mode, size))

            event_rows.append({
                "version": version,
                "recording": name,
                "frame_id": frame,
                "mode": mode,
                "celt_to_silk": direction,
                "redundancy_bytes": size,
                "final_matched": bool(final),
                "final_celt_to_silk": final_direction,
                "final_size": final_size,
                "moved": moved,
                "packet_offset": final.get("final_packet_offset", ""),
                "packet_end": final.get("final_packet_end", ""),
                "consistent": consistent
            })

        version_data[version][name] = {
            "events": events,
            "signatures": signatures,
            "c2s": sum(
                int(e.get("celt_to_silk", 0)) == 1
                for e in events
            ),
            "relocated": sum(
                int(e.get("celt_to_silk", 0)) == 1
                and any(
                    row["version"] == version
                    and row["recording"] == name
                    and row["frame_id"] == e.get("frame_id")
                    and row["moved"] == 1
                    and row["consistent"]
                    for row in event_rows
                )
                for e in events
            )
        }

def save_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

save_csv(
    OUT / "b9_pilot_event_level.csv",
    event_rows
)

print("========== EVENT-LEVEL AUDIT ==========")

for version in ["1.5.2", "1.6.1"]:

    subset = [
        r for r in event_rows
        if r["version"] == version
    ]

    c2s = [r for r in subset if r["celt_to_silk"] == 1]

    print("\nOPUS", version)
    print("Redundancy events:", len(subset))
    print("CELT-to-SILK events:", len(c2s))
    print("Matched final records:",
          sum(r["final_matched"] for r in c2s))
    print("Consistent event records:",
          sum(r["consistent"] for r in c2s))
    print("Successful relocations:",
          sum(r["moved"] == 1 for r in c2s))

print("\n========== CROSS-VERSION MATCHING ==========")

for name in names:

    a = Counter(version_data["1.5.2"][name]["signatures"])
    b = Counter(version_data["1.6.1"][name]["signatures"])

    common = sum((a & b).values())

    paired_rows.append({
        "recording": name,
        "events_152": sum(a.values()),
        "events_161": sum(b.values()),
        "exact_frame_matches": common,
        "unmatched_152": sum((a - b).values()),
        "unmatched_161": sum((b - a).values()),
        "exact_match": a == b
    })

save_csv(
    OUT / "b9_pilot_paired_versions.csv",
    paired_rows
)

print("Paired recordings:", len(paired_rows))
print("Exact event signatures:",
      sum(r["exact_frame_matches"] for r in paired_rows))
print("Exactly matching recordings:",
      sum(r["exact_match"] for r in paired_rows))

print("1.5.2-only events:",
      sum(r["unmatched_152"] for r in paired_rows))

print("1.6.1-only events:",
      sum(r["unmatched_161"] for r in paired_rows))

bad = [
    r for r in event_rows
    if r["celt_to_silk"] == 1 and
    (not r["final_matched"] or not r["consistent"] or r["moved"] != 1)
]

print("\nInconsistent CELT-to-SILK records:", len(bad))

print("\nSaved:")
print(OUT / "b9_pilot_event_level.csv")
print(OUT / "b9_pilot_paired_versions.csv")

if bad:
    raise SystemExit("B9 EVENT-LEVEL AUDIT: FAIL")

print("\nB9 EVENT-LEVEL AUDIT: PASS")
