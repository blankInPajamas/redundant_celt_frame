#!/usr/bin/env python3
"""
Independent, read-only audit of the existing B6-S2 Opus steganalysis streams.

Place this file at:
    experiments/B6_steganalysis/evaluate_b6_v2.py

Run from the project root:
    python3 experiments/B6_steganalysis/evaluate_b6_v2.py

The script does not regenerate or modify any source bitstreams or existing CSVs.
It writes new audit outputs under:
    results/phase_b/B6_audit_v2/
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SIZES = [1, 2, 4, 8, 16, 24, 32]
TAIL_SIZE = 36
MAX_PAYLOAD = 32
EXPECTED_PAYLOAD_BYTE = b"A"
Z_95 = 1.959963984540054


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_packets(path: Path) -> list[bytes]:
    """Parse the project's little-endian uint32-length-prefixed packet file."""
    data = path.read_bytes()
    offset = 0
    packets: list[bytes] = []

    while offset < len(data):
        if len(data) - offset < 4:
            raise ValueError(
                f"{path}: {len(data) - offset} trailing bytes remain before a length field"
            )

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length <= 0:
            raise ValueError(f"{path}: invalid packet length {length}")

        if offset + length > len(data):
            raise ValueError(
                f"{path}: packet length {length} exceeds remaining "
                f"{len(data) - offset} bytes"
            )

        packets.append(data[offset:offset + length])
        offset += length

    if offset != len(data):
        raise ValueError(f"{path}: parser did not consume the complete file")

    return packets


def trailing_zero_count(packet: bytes) -> int:
    count = 0
    for value in reversed(packet):
        if value != 0:
            break
        count += 1
    return count


def shannon_entropy(values: bytes) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
    )


def packet_size_zscore(packets: list[bytes]) -> float:
    sizes = [len(packet) for packet in packets]
    if len(sizes) < 5:
        return 0.0
    mean = sum(sizes) / len(sizes)
    variance = sum((value - mean) ** 2 for value in sizes) / len(sizes)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (max(sizes) - mean) / std


def blind_signature_hits(
    packets: list[bytes],
    tail_size: int = TAIL_SIZE,
    max_payload: int = MAX_PAYLOAD,
) -> list[dict[str, Any]]:
    """
    Reproduce the current location-blind structural signature:
    [length byte][printable ASCII payload][zero padding] in the final 36 bytes.
    """
    hits: list[dict[str, Any]] = []

    for packet_index, packet in enumerate(packets):
        if len(packet) < tail_size:
            continue

        region = packet[-tail_size:]
        message_length = region[0]

        if not (1 <= message_length <= max_payload):
            continue
        if message_length + 1 > tail_size:
            continue

        payload = region[1:1 + message_length]
        padding = region[1 + message_length:]

        printable = all(32 <= byte < 127 for byte in payload)
        zero_padding = all(byte == 0 for byte in padding)

        if printable and zero_padding:
            hits.append(
                {
                    "packet_index": packet_index,
                    "payload_length": message_length,
                    "payload": payload.decode("ascii"),
                    "zero_padding": len(padding),
                }
            )

    return hits


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (float("nan"), float("nan"))

    p = successes / total
    z2 = Z_95 * Z_95
    denominator = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denominator
    half_width = (
        Z_95
        * math.sqrt(
            p * (1.0 - p) / total
            + z2 / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def pct(value: float) -> str:
    return "" if math.isnan(value) else f"{100.0 * value:.2f}"


def load_b4_extractor(root: Path):
    extractor_path = root / "experiments/B4_payload/extract.py"
    if not extractor_path.exists():
        return None, f"Not found: {extractor_path}"

    spec = importlib.util.spec_from_file_location(
        "b4_extract_for_b6_audit", extractor_path
    )
    if spec is None or spec.loader is None:
        return None, "Could not load B4 extractor module"

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "extract"):
        return None, "B4 extractor does not expose extract()"

    return module.extract, ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit existing B6-S2 clean and stego bitstreams."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Project root (default: inferred from this script's location).",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    stream_dir = root / "logs/phase_b/B6_s2"
    experiment_dir = root / "experiments/B6_steganalysis"
    frame_map_path = stream_dir / "transition_frames.csv"
    payload_verification_path = experiment_dir / "payload_verification.csv"

    output_dir = root / "results/phase_b/B6_audit_v2"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not frame_map_path.exists():
        print(f"ERROR: missing transition map: {frame_map_path}", file=sys.stderr)
        return 2

    frame_rows = read_csv(frame_map_path)
    if not frame_rows:
        print("ERROR: transition_frames.csv is empty", file=sys.stderr)
        return 2

    frame_map: dict[int, int] = {}
    for row in frame_rows:
        source_id = int(row["source_id"])
        target_frame = int(row["target_frame"])
        if source_id in frame_map:
            print(f"ERROR: duplicate source_id in frame map: {source_id}", file=sys.stderr)
            return 2
        frame_map[source_id] = target_frame

    sources = sorted(frame_map)
    if len(sources) != 20:
        print(
            f"WARNING: expected 20 sources from the current experiment; "
            f"found {len(sources)} in the transition map."
        )

    extractor, extractor_note = load_b4_extractor(root)
    if extractor is None:
        print(f"WARNING: actual B4 extractor test unavailable: {extractor_note}")

    payload_rows = read_csv(payload_verification_path)
    payload_verification = {
        (int(row["source_id"]), int(row["payload_size"])): row
        for row in payload_rows
    }

    # Load and validate all stream files before writing any output.
    clean_packets: dict[int, list[bytes]] = {}
    stego_packets: dict[tuple[int, int], list[bytes]] = {}
    missing: list[str] = []

    for source_id in sources:
        clean_path = stream_dir / f"clean_{source_id}.bin"
        if not clean_path.exists():
            missing.append(str(clean_path))
            continue
        clean_packets[source_id] = load_packets(clean_path)

        for payload_size in SIZES:
            stego_path = stream_dir / f"stego_N{payload_size}_{source_id}.bin"
            if not stego_path.exists():
                missing.append(str(stego_path))
                continue
            stego_packets[(source_id, payload_size)] = load_packets(stego_path)

    if missing:
        print(f"ERROR: {len(missing)} expected stream files are missing:")
        for item in missing:
            print(f"  MISSING: {item}")
        return 2

    detailed_rows: list[dict[str, Any]] = []
    issues: list[str] = []

    # Audit each clean stream.
    for source_id in sources:
        packets = clean_packets[source_id]
        target = frame_map[source_id]

        if not (0 <= target < len(packets)):
            issues.append(f"source {source_id}: clean target frame {target} is out of range")
            continue

        packet = packets[target]
        region = packet[-TAIL_SIZE:] if len(packet) >= TAIL_SIZE else b""
        zero_run = trailing_zero_count(packet)
        clean_region_zero = region == bytes(TAIL_SIZE)

        known_tz_label = "stego" if zero_run < TAIL_SIZE else "clean"
        known_nonzero_label = "stego" if any(region) else "clean"
        known_entropy_label = (
            "stego" if shannon_entropy(region) > 0.0 else "clean"
        )

        hits = blind_signature_hits(packets)
        z_score = packet_size_zscore(packets)

        if not clean_region_zero:
            issues.append(
                f"source {source_id}: clean target frame's final {TAIL_SIZE} bytes "
                f"are not all zero"
            )

        detailed_rows.append(
            {
                "source_id": source_id,
                "payload_size": 0,
                "stream_type": "clean",
                "target_frame": target,
                "packet_count": len(packets),
                "clean_tail_zero_count": zero_run,
                "clean_tail_region_all_zero": clean_region_zero,
                "packet_count_matches_clean": True,
                "packet_lengths_match_clean": True,
                "changed_packet_count": 0,
                "changed_packet_indices": "",
                "changed_bytes_in_target_packet": 0,
                "target_prefix_unchanged": True,
                "dynamic_tail_start_matches_fixed_36": (
                    len(packet) - zero_run == len(packet) - TAIL_SIZE
                    if zero_run == TAIL_SIZE
                    else False
                ),
                "embedded_region_matches_expected": True,
                "actual_b4_extractor_matches": "not_applicable",
                "known_trailing_zero_label": known_tz_label,
                "known_nonzero_label": known_nonzero_label,
                "known_entropy_label": known_entropy_label,
                "blind_label": "stego" if hits else "clean",
                "blind_hit_count": len(hits),
                "blind_hit_packet_indices": ";".join(
                    str(hit["packet_index"]) for hit in hits
                ),
                "blind_target_found": False,
                "blind_extra_hits": len(hits),
                "packet_size_zscore": f"{z_score:.8f}",
                "historical_payload_recovery": "not_applicable",
                "historical_decode_ok": "not_applicable",
                "historical_pcm_identical": "not_applicable",
            }
        )

    # Audit every stego stream against its corresponding clean source.
    for source_id in sources:
        clean = clean_packets[source_id]
        target = frame_map[source_id]

        if not (0 <= target < len(clean)):
            continue

        clean_target = clean[target]
        clean_region = clean_target[-TAIL_SIZE:] if len(clean_target) >= TAIL_SIZE else b""
        dynamic_tail_start = len(clean_target) - trailing_zero_count(clean_target)

        for payload_size in SIZES:
            stego = stego_packets[(source_id, payload_size)]
            stego_path = stream_dir / f"stego_N{payload_size}_{source_id}.bin"

            count_match = len(clean) == len(stego)
            lengths_match = (
                count_match
                and [len(p) for p in clean] == [len(p) for p in stego]
            )

            changed_indices = [
                index
                for index, (clean_packet, stego_packet) in enumerate(zip(clean, stego))
                if clean_packet != stego_packet
            ] if count_match else []

            target_valid = target < len(stego)
            stego_target = stego[target] if target_valid else b""
            stego_region = (
                stego_target[-TAIL_SIZE:]
                if len(stego_target) >= TAIL_SIZE
                else b""
            )

            expected_region = (
                bytes([payload_size])
                + EXPECTED_PAYLOAD_BYTE * payload_size
                + bytes(TAIL_SIZE - 1 - payload_size)
            )
            region_matches = stego_region == expected_region

            target_prefix_unchanged = (
                target_valid
                and len(clean_target) >= TAIL_SIZE
                and len(stego_target) >= TAIL_SIZE
                and clean_target[:-TAIL_SIZE] == stego_target[:-TAIL_SIZE]
            )

            changed_bytes_target = (
                sum(a != b for a, b in zip(clean_target, stego_target))
                if target_valid and len(clean_target) == len(stego_target)
                else -1
            )

            only_target_changed = changed_indices == [target]
            dynamic_fixed_match = (
                dynamic_tail_start == len(clean_target) - TAIL_SIZE
                and clean_region == bytes(TAIL_SIZE)
            )

            # The payload format in reproduce_s2.sh is exactly N copies of "A".
            expected_message = "A" * payload_size
            actual_extractor_result = "not_available"
            if extractor is not None:
                try:
                    extracted = extractor(str(stego_path), TAIL_SIZE)
                    actual_extractor_result = (
                        "yes" if extracted == expected_message else "no"
                    )
                except Exception as exc:
                    actual_extractor_result = f"error:{type(exc).__name__}"

            zero_run = trailing_zero_count(stego_target)
            known_tz_label = "stego" if zero_run < TAIL_SIZE else "clean"
            known_nonzero_label = "stego" if any(stego_region) else "clean"
            known_entropy_label = (
                "stego"
                if shannon_entropy(stego_region) > 0.0
                else "clean"
            )

            hits = blind_signature_hits(stego)
            hit_indices = [hit["packet_index"] for hit in hits]
            blind_target_found = target in hit_indices
            z_score = packet_size_zscore(stego)

            verification = payload_verification.get((source_id, payload_size), {})
            historical_recovery = verification.get("recovery_ok", "missing")
            historical_decode = verification.get("decode_ok", "missing")
            historical_pcm = verification.get("pcm_identical", "missing")

            checks = {
                "packet_count": count_match,
                "packet_lengths": lengths_match,
                "only_target_packet_changed": only_target_changed,
                "target_prefix_unchanged": target_prefix_unchanged,
                "dynamic_tail_start_matches_fixed_36": dynamic_fixed_match,
                "embedded_region_matches_expected": region_matches,
                "actual_b4_extractor_matches": actual_extractor_result == "yes",
                "blind_target_found": blind_target_found,
            }

            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                issues.append(
                    f"source {source_id}, payload {payload_size}: "
                    + ", ".join(failed)
                )

            detailed_rows.append(
                {
                    "source_id": source_id,
                    "payload_size": payload_size,
                    "stream_type": "stego",
                    "target_frame": target,
                    "packet_count": len(stego),
                    "clean_tail_zero_count": trailing_zero_count(clean_target),
                    "clean_tail_region_all_zero": clean_region == bytes(TAIL_SIZE),
                    "packet_count_matches_clean": count_match,
                    "packet_lengths_match_clean": lengths_match,
                    "changed_packet_count": len(changed_indices),
                    "changed_packet_indices": ";".join(map(str, changed_indices)),
                    "changed_bytes_in_target_packet": changed_bytes_target,
                    "target_prefix_unchanged": target_prefix_unchanged,
                    "dynamic_tail_start_matches_fixed_36": dynamic_fixed_match,
                    "embedded_region_matches_expected": region_matches,
                    "actual_b4_extractor_matches": actual_extractor_result,
                    "known_trailing_zero_label": known_tz_label,
                    "known_nonzero_label": known_nonzero_label,
                    "known_entropy_label": known_entropy_label,
                    "blind_label": "stego" if hits else "clean",
                    "blind_hit_count": len(hits),
                    "blind_hit_packet_indices": ";".join(map(str, hit_indices)),
                    "blind_target_found": blind_target_found,
                    "blind_extra_hits": max(0, len(hits) - (1 if blind_target_found else 0)),
                    "packet_size_zscore": f"{z_score:.8f}",
                    "historical_payload_recovery": historical_recovery,
                    "historical_decode_ok": historical_decode,
                    "historical_pcm_identical": historical_pcm,
                }
            )

    # Metrics by payload size. Clean controls are the same 20 sources for each size.
    clean_rows = [row for row in detailed_rows if row["stream_type"] == "clean"]
    summary_rows: list[dict[str, Any]] = []

    detector_fields = [
        ("known_trailing_zero", "known_trailing_zero_label"),
        ("known_nonzero_count", "known_nonzero_label"),
        ("known_entropy", "known_entropy_label"),
        ("location_blind_signature", "blind_label"),
    ]

    for payload_size in SIZES:
        stego_rows = [
            row for row in detailed_rows
            if row["stream_type"] == "stego"
            and int(row["payload_size"]) == payload_size
        ]

        summary: dict[str, Any] = {
            "payload_size": payload_size,
            "stego_streams": len(stego_rows),
            "clean_controls": len(clean_rows),
        }

        for detector_name, field in detector_fields:
            tp = sum(row[field] == "stego" for row in stego_rows)
            fn = len(stego_rows) - tp
            fp = sum(row[field] == "stego" for row in clean_rows)
            tn = len(clean_rows) - fp

            tpr = tp / len(stego_rows) if stego_rows else float("nan")
            fpr = fp / len(clean_rows) if clean_rows else float("nan")
            tpr_low, tpr_high = wilson_interval(tp, len(stego_rows))
            fpr_low, fpr_high = wilson_interval(fp, len(clean_rows))

            summary[f"{detector_name}_TP"] = tp
            summary[f"{detector_name}_FN"] = fn
            summary[f"{detector_name}_FP"] = fp
            summary[f"{detector_name}_TN"] = tn
            summary[f"{detector_name}_TPR_pct"] = pct(tpr)
            summary[f"{detector_name}_TPR_Wilson95_low_pct"] = pct(tpr_low)
            summary[f"{detector_name}_TPR_Wilson95_high_pct"] = pct(tpr_high)
            summary[f"{detector_name}_FPR_pct"] = pct(fpr)
            summary[f"{detector_name}_FPR_Wilson95_low_pct"] = pct(fpr_low)
            summary[f"{detector_name}_FPR_Wilson95_high_pct"] = pct(fpr_high)

        summary["correct_target_localizations"] = sum(
            row["blind_target_found"] is True for row in stego_rows
        )
        summary["streams_with_exact_embedded_region"] = sum(
            row["embedded_region_matches_expected"] is True for row in stego_rows
        )
        summary["streams_with_matching_packet_lengths"] = sum(
            row["packet_lengths_match_clean"] is True for row in stego_rows
        )
        summary["streams_with_only_target_packet_changed"] = sum(
            row["changed_packet_count"] == 1
            and row["changed_packet_indices"] == str(row["target_frame"])
            for row in stego_rows
        )
        summary["actual_extractor_matches"] = sum(
            row["actual_b4_extractor_matches"] == "yes" for row in stego_rows
        )
        summary["historical_payload_recovery_yes"] = sum(
            row["historical_payload_recovery"] == "yes" for row in stego_rows
        )
        summary["historical_decode_yes"] = sum(
            row["historical_decode_ok"] == "yes" for row in stego_rows
        )
        summary["historical_pcm_identical_yes"] = sum(
            row["historical_pcm_identical"] == "yes" for row in stego_rows
        )

        # Compare the packet-size z-score for each source's clean/stego pair.
        clean_by_source = {
            int(row["source_id"]): float(row["packet_size_zscore"])
            for row in clean_rows
        }
        equal_z_pairs = 0
        for row in stego_rows:
            source_id = int(row["source_id"])
            if math.isclose(
                float(row["packet_size_zscore"]),
                clean_by_source[source_id],
                rel_tol=0.0,
                abs_tol=1e-10,
            ):
                equal_z_pairs += 1
        summary["packet_size_zscore_equal_to_clean_pairs"] = equal_z_pairs

        summary_rows.append(summary)

    # Write new outputs only; originals are untouched.
    detailed_path = output_dir / "stream_audit.csv"
    summary_path = output_dir / "summary_by_payload.csv"
    issues_path = output_dir / "audit_issues.txt"

    write_csv(detailed_path, detailed_rows)
    write_csv(summary_path, summary_rows)

    if issues:
        issues_path.write_text("\n".join(issues) + "\n", encoding="utf-8")
    else:
        issues_path.write_text(
            "No structural/integrity failures detected by this audit.\n",
            encoding="utf-8",
        )

    # Human-readable console summary.
    print("\n========== B6 V2 AUDIT ==========")
    print(f"Project root: {root}")
    print(f"Sources: {len(sources)}")
    print(f"Clean streams: {len(clean_packets)}")
    print(f"Stego streams: {len(stego_packets)}")
    print(f"Total audited streams: {len(detailed_rows)}")
    print(f"Tail region: {TAIL_SIZE} bytes")
    print(f"Expected payload: ASCII 'A' repeated N times")
    print(f"B4 extractor test: {'available' if extractor else 'unavailable'}")

    print("\nPayload | Known-location TPR | Blind-signature TPR | Blind FPR | "
          "Exact region | Extractor | Packet-size pairs equal")
    print("-" * 112)

    for row in summary_rows:
        print(
            f"{row['payload_size']:>7} | "
            f"{row['known_trailing_zero_TPR_pct']:>7}% | "
            f"{row['location_blind_signature_TPR_pct']:>7}% | "
            f"{row['location_blind_signature_FPR_pct']:>7}% | "
            f"{row['streams_with_exact_embedded_region']:>2}/{row['stego_streams']:<2} | "
            f"{row['actual_extractor_matches']:>2}/{row['stego_streams']:<2} | "
            f"{row['packet_size_zscore_equal_to_clean_pairs']:>2}/{row['stego_streams']:<2}"
        )

    print("\nClean-control false positives:")
    for detector_name, field in detector_fields:
        fp = sum(row[field] == "stego" for row in clean_rows)
        print(f"  {detector_name}: {fp}/{len(clean_rows)}")

    print(f"\nAudit issues: {len(issues)}")
    if issues:
        for issue in issues[:30]:
            print(f"  - {issue}")
        if len(issues) > 30:
            print(f"  ... and {len(issues) - 30} more; see {issues_path}")

    print("\nNew outputs:")
    print(f"  {detailed_path}")
    print(f"  {summary_path}")
    print(f"  {issues_path}")
    print("\nExisting bitstreams and original CSV files were not modified.")

    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
