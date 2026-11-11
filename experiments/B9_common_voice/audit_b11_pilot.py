#!/usr/bin/env python3

import csv
import hashlib
import struct
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path.cwd()
RUN = Path(sys.argv[1]).resolve()

B9 = ROOT / "experiments/B9_common_voice"
SOURCE_ROOT = B9 / "results/b9_full_encoding"
CAPACITY = 36

def sha(data):
    return hashlib.sha256(data).hexdigest()

def file_sha(path):
    return sha(Path(path).read_bytes())

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def flag(value):
    return str(value).lower() in ("true", "1", "yes")

def packets(path):
    data = Path(path).read_bytes()
    result = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"Incomplete header: {path}")

        n = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if n <= 0 or offset + n > len(data):
            raise ValueError(f"Invalid packet framing: {path}")

        result.append(data[offset:offset+n])
        offset += n

    return result

def zero_tail(packet):
    n = 0
    for b in reversed(packet):
        if b != 0:
            break
        n += 1
    return n

def save_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def main():

    manifest = read_csv(RUN / "b11_payload_manifest.csv")
    results = read_csv(RUN / "b11_decoder_results.csv")
    baseline = read_csv(RUN / "b11_baseline_results.csv")
    capacity = read_csv(RUN / "b11_capacity_rejection.csv")
    selection = read_csv(RUN / "b11_pilot_selection.csv")

    failures = []
    packet_audit = []
    capacity_audit = []
    summary = []

    print("========== B11 INDEPENDENT POST-RUN AUDIT ==========")

    # 1. Sample validation
    print("\n[1] PILOT SAMPLE")

    if len(selection) != 20:
        failures.append("Pilot selection is not 20 events")

    for version in ("1.5.2", "1.6.1"):
        group = [r for r in selection if r["encoder"] == version]

        print(f"{version}: {len(group)} events")

        if len(group) != 10:
            failures.append(f"{version}: expected 10 events")

        if len(set(r["recording"] for r in group)) != 10:
            failures.append(f"{version}: duplicate recordings")

        if len(set(r["speaker_sha256"] for r in group)) != 10:
            failures.append(f"{version}: duplicate speakers")

    # 2. Independent bitstream-level verification
    print("\n[2] BITSTREAM INTEGRITY")

    for r in manifest:

        enc = r["encoder"]
        rec = r["recording"]
        frame = int(r["frame"])
        size = int(r["payload_size_bytes"])

        source = (
            SOURCE_ROOT / enc / "bitstreams" / f"{rec}.bin"
        )

        modified = RUN / r["modified_bitstream"]

        original_packets = packets(source)
        modified_packets = packets(modified)

        payload = bytes.fromhex(r["payload_hex"])

        expected_tail = bytes(CAPACITY-size) + payload

        source_hash_ok = (
            file_sha(source) == r["source_bitstream_sha256"]
        )

        modified_hash_ok = (
            file_sha(modified) == r["modified_bitstream_sha256"]
        )

        count_ok = len(original_packets) == len(modified_packets)

        lengths_ok = (
            count_ok and
            [len(p) for p in original_packets] ==
            [len(p) for p in modified_packets]
        )

        target_ok = (
            count_ok
            and modified_packets[frame][-CAPACITY:] == expected_tail
            and modified_packets[frame][:-CAPACITY] ==
                original_packets[frame][:-CAPACITY]
        )

        other_packets_ok = (
            count_ok and all(
                modified_packets[i] == original_packets[i]
                for i in range(len(original_packets))
                if i != frame
            )
        )

        passed = all((
            source_hash_ok,
            modified_hash_ok,
            lengths_ok,
            target_ok,
            other_packets_ok
        ))

        packet_audit.append({
            "encoder": enc,
            "recording": rec,
            "payload_size": size,
            "repetition": r["repetition"],
            "source_hash_ok": source_hash_ok,
            "modified_hash_ok": modified_hash_ok,
            "packet_count_ok": count_ok,
            "packet_lengths_ok": lengths_ok,
            "target_packet_exact": target_ok,
            "other_packets_byte_identical": other_packets_ok,
            "audit_pass": passed
        })

        if not passed:
            failures.append(f"Bitstream audit failed: {enc}/{rec}/{size}")

    print(
        f"Independent bitstream checks: "
        f"{sum(x['audit_pass'] for x in packet_audit)}/"
        f"{len(packet_audit)}"
    )

    # 3. Decoder-level verification
    print("\n[3] DECODER RESULTS")

    groups = defaultdict(list)

    for r in results:

        control = r["control"]

        original_hash = r["original_payload_sha256"]
        wire_hash = r["wire_payload_sha256"]
        extracted_hash = r["extracted_payload_sha256"]

        common = all((
            flag(r["extraction_exact"]),
            flag(r["decoder_pass"]),
            flag(r["pcm_identical"]),
            flag(r["packet_lengths_preserved"]),
            flag(r["integrity_control_pass"]),
            int(r["matching_tail_count"]) == 1,
            int(r["decoded_frames"]) == int(r["expected_frames"])
        ))

        if control == "payload":

            integrity = (
                original_hash == wire_hash == extracted_hash
                and not flag(r["integrity_mismatch_detected"])
                and int(r["bit_flip_count"]) == 0
            )

        elif control == "one_bit_corruption":

            integrity = (
                wire_hash != original_hash
                and extracted_hash == wire_hash
                and flag(r["integrity_mismatch_detected"])
                and int(r["bit_flip_count"]) == 1
            )

        else:
            integrity = False

        passed = common and integrity

        key = (
            r["encoder"],
            r["decoder"],
            int(r["payload_size_bytes"]),
            control
        )

        groups[key].append(passed)

        if not passed:
            failures.append(
                f"Decoder audit failed: {key}, {r['recording']}"
            )

    for key in sorted(groups):
        enc, dec, size, control = key
        values = groups[key]

        summary.append({
            "encoder": enc,
            "decoder": dec,
            "payload_size_bytes": size,
            "control": control,
            "tests": len(values),
            "passed": sum(values),
            "failed": len(values) - sum(values),
            "success_rate_percent": round(
                100 * sum(values) / len(values), 2
            )
        })

    print(f"Decoder records: {len(results)}")
    print(f"Normal payload tests: {sum(r['control']=='payload' for r in results)}")
    print(f"Corruption tests: {sum(r['control']=='one_bit_corruption' for r in results)}")

    # Expected sample counts
    expected = {
        "payload": 720,
        "one_bit_corruption": 240
    }

    for control, count in expected.items():
        actual = sum(r["control"] == control for r in results)

        if actual != count:
            failures.append(
                f"{control}: expected {count}, found {actual}"
            )

    for key, values in groups.items():

        expected_count = 30 if key[3] == "payload" else 10

        if len(values) != expected_count:
            failures.append(
                f"Unexpected group size {key}: {len(values)}"
            )

    # 4. Baseline verification
    print("\n[4] BASELINE")

    baseline_ok = all(
        flag(r["baseline_pass"]) for r in baseline
    )

    if len(baseline) != 40 or not baseline_ok:
        failures.append("Baseline audit failed")

    print(
        f"Baseline: "
        f"{sum(flag(r['baseline_pass']) for r in baseline)}/"
        f"{len(baseline)}"
    )

    # 5. Independent capacity verification
    print("\n[5] PHYSICAL ZERO-TAIL CAPACITY")

    selection_lookup = {
        (r["encoder"], r["recording"]): r
        for r in selection
    }

    for r in capacity:

        enc = r["encoder"]
        rec = r["recording"]

        selected = selection_lookup[(enc, rec)]

        source = (
            SOURCE_ROOT / enc / "bitstreams" / f"{rec}.bin"
        )

        frame = int(selected["frame"])
        original_packets = packets(source)

        tail = zero_tail(original_packets[frame])

        source_hash_ok = (
            file_sha(source) == selected["source_sha256"]
        )

        actual_capacity_ok = (
            tail == CAPACITY and 37 > tail
        )

        guard_ok = (
            flag(r["rejected"])
            and flag(r["source_unchanged"])
        )

        passed = (
            source_hash_ok
            and actual_capacity_ok
            and guard_ok
        )

        capacity_audit.append({
            "encoder": enc,
            "recording": rec,
            "actual_zero_tail_bytes": tail,
            "attempted_payload_bytes": 37,
            "source_hash_ok": source_hash_ok,
            "configured_guard_rejected": guard_ok,
            "physical_capacity_verified": actual_capacity_ok,
            "audit_pass": passed
        })

        if not passed:
            failures.append(f"Capacity audit failed: {enc}/{rec}")

    print(
        f"Independent capacity checks: "
        f"{sum(x['audit_pass'] for x in capacity_audit)}/"
        f"{len(capacity_audit)}"
    )

    # 6. Final counts and outputs
    print("\n[6] FINAL AUDIT")

    if len(manifest) != 360:
        failures.append("Manifest must contain 360 records")

    if len(results) != 960:
        failures.append("Decoder results must contain 960 records")

    if len(capacity) != 20:
        failures.append("Capacity table must contain 20 records")

    save_csv(RUN/"b11_stratified_summary.csv", summary)
    save_csv(RUN/"b11_packet_integrity_audit.csv", packet_audit)
    save_csv(RUN/"b11_independent_capacity_audit.csv", capacity_audit)

    report = [
        "========== B11 INDEPENDENT AUDIT REPORT ==========",
        f"Pilot manifest records: {len(manifest)}",
        f"Decoder records: {len(results)}",
        f"Baseline records: {len(baseline)}",
        f"Capacity records: {len(capacity)}",
        "",
        f"Bitstream audit: {sum(x['audit_pass'] for x in packet_audit)}/{len(packet_audit)}",
        f"Baseline audit: {sum(flag(r['baseline_pass']) for r in baseline)}/{len(baseline)}",
        f"Decoder audit: {sum(sum(v) for v in groups.values())}/{len(results)}",
        f"Physical capacity audit: {sum(x['audit_pass'] for x in capacity_audit)}/{len(capacity_audit)}",
        "",
        f"Failures: {len(failures)}",
        "",
        "AUDIT STATUS: " + ("PASS" if not failures else "FAIL")
    ]

    if failures:
        report.extend(["", "FAILURE DETAILS:"] + failures)

    report_path = RUN/"b11_postrun_audit.txt"
    report_path.write_text("\n".join(report) + "\n")

    checksum = RUN/"b11_postrun_audit_checksums.sha256"

    audit_files = [
        report_path,
        RUN/"b11_stratified_summary.csv",
        RUN/"b11_packet_integrity_audit.csv",
        RUN/"b11_independent_capacity_audit.csv"
    ]

    with open(checksum, "w") as f:
        for p in audit_files:
            f.write(f"{file_sha(p)}  {p.name}\n")

    print("\n".join(report))
    print(f"\nDetailed summary: {RUN/'b11_stratified_summary.csv'}")
    print(f"Audit report: {report_path}")
    print(f"Audit checksums: {checksum}")

    if failures:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
