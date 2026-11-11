#!/usr/bin/env python3

import csv
import re
from pathlib import Path
from collections import Counter, defaultdict

VERSIONS = ["1.5.2", "1.6.1"]

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = SCRIPT_DIR / "results/b9_full_encoding"
MANIFEST = OUT / "input_manifest.tsv"
AUDIT = OUT / "independent_audit"

AUDIT.mkdir(parents=True, exist_ok=True)

def parse_fields(line):
    return {
        k: int(v)
        for k, v in re.findall(r'(\w+)=(-?\d+)', line)
    }

def write_csv(path, rows):
    if not rows:
        print("WARNING: Empty output:", path)
        return

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)

# --------------------------------------------------
# 1. LOAD FROZEN MANIFEST
# --------------------------------------------------

with open(MANIFEST, newline="") as f:
    manifest = list(csv.DictReader(f, delimiter="\t"))

assert manifest, "Empty input manifest"

recording_ids = [r["recording_id"] for r in manifest]

assert len(recording_ids) == len(set(recording_ids)), \
    "Duplicate recording IDs"

for r in manifest:
    r["complete_frames"] = int(r["complete_frames"])

print("========== B9 MANIFEST ==========")
print("Recordings:", len(manifest))
print("Unique speakers:", len(set(r["speaker_id"] for r in manifest)))
print("Total expected frames:",
      sum(r["complete_frames"] for r in manifest))

# --------------------------------------------------
# 2. INDEPENDENT DIAGNOSTIC AUDIT
# --------------------------------------------------

all_events = []
recording_rows = []
events_by_version_recording = {}

version_checks = {}

for version in VERSIONS:

    print(f"\n========== OPUS {version} ==========")

    diag_dir = OUT / version / "diagnostics"

    log_files = {
        p.stem: p for p in diag_dir.glob("*.log")
    }

    manifest_ids = set(recording_ids)
    log_ids = set(log_files)

    missing_logs = manifest_ids - log_ids
    extra_logs = log_ids - manifest_ids

    version_events = []
    version_recordings = []

    for rec in manifest:

        rid = rec["recording_id"]
        speaker = rec["speaker_id"]
        expected_frames = rec["complete_frames"]

        log_path = log_files.get(rid)

        events = []
        finals = []

        if log_path is not None:

            with open(log_path, errors="replace") as f:
                for line in f:

                    line = line.strip()

                    if line.startswith("REDUNDANCY:"):
                        events.append(parse_fields(line))

                    elif line.startswith("RED_FINAL:"):
                        finals.append(parse_fields(line))

        final_by_frame = defaultdict(list)
        event_by_frame = defaultdict(list)

        for final in finals:
            final_by_frame[final.get("frame", -1)].append(final)

        for event in events:
            event_by_frame[event.get("frame_id", -1)].append(event)

        # Frame completeness
        frame_numbers = [
            x.get("frame", -1) for x in finals
        ]

        unique_frames = set(frame_numbers)

        duplicate_frames = len(frame_numbers) - len(unique_frames)

        missing_frames = len(
            set(range(expected_frames)) - unique_frames
        )

        frame_count_ok = (
            len(finals) == expected_frames
            and len(unique_frames) == expected_frames
            and unique_frames == set(range(expected_frames))
        )

        # Event-to-final matching
        cts_count = 0
        successful_relocations = 0
        consistency_failures = 0
        event_signatures = []

        for event in events:

            frame = event["frame_id"]
            mode = event["mode"]
            cts = event["celt_to_silk"]
            size = event["bytes"]

            matches = final_by_frame.get(frame, [])
            same_frame_events = event_by_frame[frame]

            final = matches[0] if len(matches) == 1 else {}

            issues = []

            if len(matches) != 1:
                issues.append("final_match_count")

            if len(same_frame_events) != 1:
                issues.append("duplicate_event_frame")

            if final:

                if final.get("redundancy") != 1:
                    issues.append("redundancy_flag")

                if final.get("mode") != mode:
                    issues.append("mode_mismatch")

                if final.get("celt_to_silk") != cts:
                    issues.append("direction_mismatch")

                if final.get("redundancy_size") != size:
                    issues.append("size_mismatch")

            relocation_ok = "NA"

            if cts == 1:

                cts_count += 1

                relocation_ok = False

                if final:

                    offset = final.get("final_packet_offset", -1)
                    end = final.get("final_packet_end", -1)
                    packet_length = final.get(
                        "packet_return_length", -1
                    )

                    relocation_ok = (
                        final.get("moved") == 1
                        and offset >= 0
                        and end - offset == size
                        and end <= packet_length
                    )

                if relocation_ok:
                    successful_relocations += 1
                else:
                    issues.append("relocation_failure")

            consistent = len(issues) == 0

            if not consistent:
                consistency_failures += 1

            signature = (frame, mode, cts, size)
            event_signatures.append(signature)

            row = {
                "version": version,
                "recording_id": rid,
                "speaker_id": speaker,
                "event_id": event.get("event", -1),
                "frame_id": frame,
                "mode": mode,
                "celt_to_silk": cts,
                "bytes": size,
                "final_match_count": len(matches),
                "final_redundancy": final.get("redundancy", ""),
                "final_celt_to_silk": final.get("celt_to_silk", ""),
                "final_redundancy_size": final.get(
                    "redundancy_size", ""
                ),
                "moved": final.get("moved", ""),
                "relocation_success": relocation_ok,
                "event_consistent": consistent,
                "issues": ";".join(issues)
            }

            all_events.append(row)
            version_events.append(row)

        # Reverse audit: redundancy finals must have events
        redundancy_finals = [
            x for x in finals if x.get("redundancy") == 1
        ]

        orphan_finals = sum(
            1 for x in redundancy_finals
            if not event_by_frame.get(x.get("frame", -1))
        )

        redundancy_count_ok = (
            len(redundancy_finals) == len(events)
        )

        has_cts = cts_count > 0

        summary = {
            "version": version,
            "recording_id": rid,
            "speaker_id": speaker,
            "expected_frames": expected_frames,
            "actual_final_records": len(finals),
            "unique_final_frames": len(unique_frames),
            "duplicate_final_frames": duplicate_frames,
            "missing_final_frames": missing_frames,
            "frame_count_ok": frame_count_ok,
            "total_redundancy_events": len(events),
            "redundancy_final_records": len(redundancy_finals),
            "orphan_redundancy_finals": orphan_finals,
            "redundancy_count_ok": redundancy_count_ok,
            "celt_to_silk_events": cts_count,
            "successful_relocations": successful_relocations,
            "relocation_failures": cts_count - successful_relocations,
            "consistency_failures": consistency_failures,
            "has_redundancy": int(len(events) > 0),
            "has_celt_to_silk": int(has_cts),
            "events_per_1000_frames": round(
                len(events) / expected_frames * 1000, 4
            ) if expected_frames else 0,
            "cts_per_1000_frames": round(
                cts_count / expected_frames * 1000, 4
            ) if expected_frames else 0,
            "diagnostic_present": int(log_path is not None)
        }

        recording_rows.append(summary)
        version_recordings.append(summary)

        events_by_version_recording[(version, rid)] = event_signatures

    version_checks[version] = {
        "logs": len(log_files),
        "missing_logs": len(missing_logs),
        "extra_logs": len(extra_logs),
        "recordings": version_recordings,
        "events": version_events
    }

# --------------------------------------------------
# 3. RECORDING-LEVEL SUMMARY
# --------------------------------------------------

write_csv(
    AUDIT / "b9_full_event_level.csv",
    all_events
)

write_csv(
    AUDIT / "b9_full_recording_summary.csv",
    recording_rows
)

# --------------------------------------------------
# 4. SPEAKER-LEVEL SUMMARY
# --------------------------------------------------

speaker_agg = defaultdict(lambda: {
    "recordings": 0,
    "frames": 0,
    "redundancy_events": 0,
    "cts_events": 0,
    "recordings_with_cts": 0
})

for row in recording_rows:

    key = (row["version"], row["speaker_id"])
    s = speaker_agg[key]

    s["recordings"] += 1
    s["frames"] += row["expected_frames"]
    s["redundancy_events"] += row["total_redundancy_events"]
    s["cts_events"] += row["celt_to_silk_events"]
    s["recordings_with_cts"] += row["has_celt_to_silk"]

speaker_rows = []

for (version, speaker), s in sorted(speaker_agg.items()):

    speaker_rows.append({
        "version": version,
        "speaker_id": speaker,
        "recordings": s["recordings"],
        "total_frames": s["frames"],
        "redundancy_events": s["redundancy_events"],
        "celt_to_silk_events": s["cts_events"],
        "recordings_with_cts": s["recordings_with_cts"],
        "has_celt_to_silk": int(s["cts_events"] > 0),
        "cts_events_per_1000_frames": round(
            s["cts_events"] / s["frames"] * 1000, 4
        ) if s["frames"] else 0
    })

write_csv(
    AUDIT / "b9_full_speaker_summary.csv",
    speaker_rows
)

# --------------------------------------------------
# 5. CROSS-VERSION EVENT COMPARISON
# --------------------------------------------------

paired_rows = []

for rec in manifest:

    rid = rec["recording_id"]
    speaker = rec["speaker_id"]

    sig15 = Counter(
        events_by_version_recording.get(("1.5.2", rid), [])
    )

    sig16 = Counter(
        events_by_version_recording.get(("1.6.1", rid), [])
    )

    cts15 = Counter({
        sig: count for sig, count in sig15.items()
        if sig[2] == 1
    })

    cts16 = Counter({
        sig: count for sig, count in sig16.items()
        if sig[2] == 1
    })

    shared = cts15 & cts16
    only15 = cts15 - cts16
    only16 = cts16 - cts15

    def format_signatures(counter):
        return ";".join(
            f"{sig[0]}:{sig[1]}:{sig[3]}(x{count})"
            for sig, count in sorted(counter.items())
        )

    paired_rows.append({
        "recording_id": rid,
        "speaker_id": speaker,
        "events_1_5_2": sum(sig15.values()),
        "events_1_6_1": sum(sig16.values()),
        "cts_events_1_5_2": sum(cts15.values()),
        "cts_events_1_6_1": sum(cts16.values()),
        "shared_cts_events": sum(shared.values()),
        "only_1_5_2_cts_events": sum(only15.values()),
        "only_1_6_1_cts_events": sum(only16.values()),
        "exact_event_signature_match": int(sig15 == sig16),
        "exact_cts_signature_match": int(cts15 == cts16),
        "shared_cts_signatures": format_signatures(shared),
        "only_1_5_2_signatures": format_signatures(only15),
        "only_1_6_1_signatures": format_signatures(only16)
    })

write_csv(
    AUDIT / "b9_full_paired_versions.csv",
    paired_rows
)

# --------------------------------------------------
# 6. FINAL AUDIT REPORT
# --------------------------------------------------

report = []

report.append("========== B9 INDEPENDENT AUDIT ==========")
report.append(f"Manifest recordings: {len(manifest)}")
report.append(
    f"Unique speakers: {len(set(r['speaker_id'] for r in manifest))}"
)

overall_pass = True

for version in VERSIONS:

    check = version_checks[version]
    rows = check["recordings"]
    events = check["events"]

    total_events = sum(
        r["total_redundancy_events"] for r in rows
    )

    total_cts = sum(
        r["celt_to_silk_events"] for r in rows
    )

    total_relocated = sum(
        r["successful_relocations"] for r in rows
    )

    files_with_cts = sum(
        r["has_celt_to_silk"] for r in rows
    )

    frame_failures = sum(
        not r["frame_count_ok"] for r in rows
    )

    count_failures = sum(
        not r["redundancy_count_ok"] for r in rows
    )

    orphan_finals = sum(
        r["orphan_redundancy_finals"] for r in rows
    )

    consistency_failures = sum(
        r["consistency_failures"] for r in rows
    )

    relocation_failures = total_cts - total_relocated

    version_pass = (
        check["logs"] == len(manifest)
        and check["missing_logs"] == 0
        and check["extra_logs"] == 0
        and frame_failures == 0
        and count_failures == 0
        and orphan_finals == 0
        and consistency_failures == 0
        and relocation_failures == 0
    )

    overall_pass = overall_pass and version_pass

    report.extend([
        "",
        f"----- OPUS {version} -----",
        f"Diagnostic files: {check['logs']}",
        f"Missing logs: {check['missing_logs']}",
        f"Extra logs: {check['extra_logs']}",
        f"Total redundancy events: {total_events}",
        f"CELT-to-SILK events: {total_cts}",
        f"Successful relocations: {total_relocated}",
        f"Recordings with CELT-to-SILK events: {files_with_cts}",
        f"Frame validation failures: {frame_failures}",
        f"Redundancy count failures: {count_failures}",
        f"Orphan final records: {orphan_finals}",
        f"Event consistency failures: {consistency_failures}",
        f"Relocation failures: {relocation_failures}",
        f"Version audit: {'PASS' if version_pass else 'FAIL'}"
    ])

# Cross-version summary
exact_events = sum(
    r["exact_event_signature_match"] for r in paired_rows
)

exact_cts = sum(
    r["exact_cts_signature_match"] for r in paired_rows
)

shared_cts = sum(r["shared_cts_events"] for r in paired_rows)

only15 = sum(r["only_1_5_2_cts_events"] for r in paired_rows)
only16 = sum(r["only_1_6_1_cts_events"] for r in paired_rows)

report.extend([
    "",
    "========== CROSS-VERSION COMPARISON ==========",
    f"Paired recordings: {len(paired_rows)}",
    f"Exact all-event signature matches: {exact_events}",
    f"Exact CELT-to-SILK signature matches: {exact_cts}",
    f"Shared CELT-to-SILK events: {shared_cts}",
    f"Opus 1.5.2-only CELT-to-SILK events: {only15}",
    f"Opus 1.6.1-only CELT-to-SILK events: {only16}",
    "",
    "========== FINAL RESULT ==========",
    f"B9 INDEPENDENT AUDIT: {'PASS' if overall_pass else 'FAIL'}"
])

report_text = "\n".join(report)

(AUDIT / "b9_full_audit_report.txt").write_text(
    report_text + "\n"
)

print("\n" + report_text)

print("\n========== OUTPUT FILES ==========")

for p in sorted(AUDIT.glob("*")):
    print(p.name, p.stat().st_size, "bytes")

if not overall_pass:
    raise SystemExit(1)
