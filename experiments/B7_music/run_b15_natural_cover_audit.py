#!/usr/bin/env python3

import ast
import csv
import hashlib
import json
import math
import re
import shutil
import struct
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

B7 = ROOT / "logs/phase_b/B7_official_20261103_020241"

DETECTOR_FILE = ROOT / "experiments/B6_steganalysis/detectors.py"

MANIFEST = ROOT / "experiments/B7_music/gtzan_valid_manifest.csv"

RESULTS = B7 / "b7_zero_tail_payload_test/results.csv"

PACKET_AUDIT = (
    B7 / "b7_zero_tail_payload_test/independent_packet_audit.csv"
)

SUMMARY = B7 / "summary.csv"

VERSIONS = ["1.5.2", "1.6.1"]

TAIL_SIZE = 36
MAX_PAYLOAD = 35
MAX_PACKET = 1500

OUTPUT_ROOT = (
    ROOT / "experiments/B7_music/results/b15_natural_cover_audit"
)

RUN = OUTPUT_ROOT / (
    "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")
)

RUN.mkdir(parents=True, exist_ok=False)


def read_csv(path):
    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):

    if not rows:
        raise ValueError(f"No rows to write: {path}")

    with path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024), b""
        ):
            h.update(block)

    return h.hexdigest()


def parse_bitstream(path):

    raw = path.read_bytes()

    packets = []
    offset = 0

    while offset < len(raw):

        if offset + 4 > len(raw):
            raise ValueError(
                f"Truncated packet header: {path}"
            )

        packet_len = struct.unpack_from(
            "=i", raw, offset
        )[0]

        offset += 4

        if not (1 <= packet_len <= MAX_PACKET):
            raise ValueError(
                f"Invalid packet length {packet_len}: {path}"
            )

        if offset + packet_len > len(raw):
            raise ValueError(
                f"Truncated packet data: {path}"
            )

        packets.append(raw[offset:offset + packet_len])

        offset += packet_len

    if not packets:
        raise ValueError(f"No packets found: {path}")

    return packets


def load_exact_detector():

    source = DETECTOR_FILE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    function = next(
        (
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "blind_structural_scan"
        ),
        None
    )

    if function is None:
        raise RuntimeError(
            "blind_structural_scan not found"
        )

    # Compile the original detector function without
    # importing unrelated module dependencies.

    module = ast.Module(
        body=[function],
        type_ignores=[]
    )

    ast.fix_missing_locations(module)

    namespace = {}

    exec(
        compile(
            module,
            str(DETECTOR_FILE),
            "exec"
        ),
        namespace
    )

    return namespace["blind_structural_scan"]


def wilson(successes, total, z=1.959963984540054):

    if total == 0:
        return None, None

    p = successes / total

    denominator = 1 + z*z/total

    centre = (
        p + z*z/(2*total)
    ) / denominator

    margin = (
        z * math.sqrt(
            p*(1-p)/total + z*z/(4*total*total)
        ) / denominator
    )

    return max(0, centre-margin), min(1, centre+margin)


def truth(value):

    return str(value).strip().lower() in (
        "true", "1", "yes"
    )


def main():

    print("========== B15 NATURAL-COVER AUDIT ==========")

    assert B7.exists()
    assert DETECTOR_FILE.exists()
    assert MANIFEST.exists()
    assert RESULTS.exists()
    assert PACKET_AUDIT.exists()
    assert SUMMARY.exists()

    detector = load_exact_detector()

    print("Detector:", DETECTOR_FILE)
    print("Detector SHA256:", sha256(DETECTOR_FILE))
    print("Packet format: 4-byte native-endian integer + packet")
    print("Tail size:", TAIL_SIZE)
    print("Maximum payload:", MAX_PAYLOAD)

    manifest = read_csv(MANIFEST)
    results = read_csv(RESULTS)
    packet_audit = read_csv(PACKET_AUDIT)
    summary = read_csv(SUMMARY)

    assert len(manifest) == 999, len(manifest)
    assert len(results) == 20, len(results)
    assert len(packet_audit) == 20, len(packet_audit)

    assert len({
        r["filename"] for r in manifest
    }) == 999

    print("\n========== INPUT VALIDATION ==========")
    print("GTZAN manifest:", len(manifest))
    print("Positive-control records:", len(results))
    print("Independent packet audits:", len(packet_audit))

    required_result_fields = [
        "decode_success",
        "payload_recovered",
        "pcm_byte_identical",
        "packet_length_preserved"
    ]

    for r in results:
        for field in required_result_fields:
            assert truth(r[field]), (r, field)

    required_audit_fields = [
        "packet_count_same",
        "packet_lengths_same",
        "file_size_same",
        "original_tail_zero",
        "payload_correct",
        "other_packets_unchanged",
        "target_prefix_unchanged"
    ]

    for r in packet_audit:
        for field in required_audit_fields:
            assert truth(r[field]), (r, field)

    print("Positive-control functional validation: PASS")
    print("Independent packet validation: PASS")

    result_map = {
        (r["version"], r["id"]): r
        for r in results
    }

    audit_map = {
        (r["version"], r["recording"]): r
        for r in packet_audit
    }

    all_rows = []
    positive_rows = []
    input_hash_rows = []

    clean_by_version = {}
    positive_by_version = {}

    for version in VERSIONS:

        print(f"\n========== VERSION {version} ==========")

        clean_dir = B7 / version / "bitstreams"

        stego_dir = (
            B7 / "b7_zero_tail_payload_test"
            / "stego" / version
        )

        clean_files = sorted(
            clean_dir.glob("*.bin")
        )

        stego_files = sorted(
            stego_dir.glob("*.bin")
        )

        assert len(clean_files) == 999, (
            version, len(clean_files)
        )

        assert len(stego_files) == 10, (
            version, len(stego_files)
        )

        summary_ids = {
            r["id"] for r in summary
            if r["version"] == version
        }

        clean_ids = {
            p.stem for p in clean_files
        }

        assert clean_ids == summary_ids, (
            version, "Clean recording inventory mismatch"
        )

        positive_map = {}

        for path in stego_files:

            match = re.match(
                r"^(.*)_f(\d+)$", path.stem
            )

            if not match:
                raise ValueError(
                    f"Unexpected stego filename: {path.name}"
                )

            recording = match.group(1)
            filename_frame = int(match.group(2))

            key = (version, recording)

            if key not in result_map:
                raise ValueError(
                    f"Missing positive result: {key}"
                )

            result = result_map[key]

            expected_frame = int(result["frame"])

            if filename_frame != expected_frame:
                raise ValueError(
                    f"Frame mismatch: {path.name}"
                )

            positive_map[recording] = (
                path, expected_frame
            )

        assert len(positive_map) == 10

        assert set(positive_map) == {
            r["id"] for r in results
            if r["version"] == version
        }

        assert {
            r["recording"] for r in packet_audit
            if r["version"] == version
        } == set(positive_map)

        clean_by_version[version] = {}
        positive_by_version[version] = {}

        # --------------------------------------
        # CLEAN NATURAL MUSIC
        # --------------------------------------

        clean_detected = 0

        for i, path in enumerate(clean_files, 1):

            packets = parse_bitstream(path)

            result = detector(
                packets,
                tail_size=TAIL_SIZE,
                max_payload=MAX_PAYLOAD
            )

            hits = result["hits"]

            detected = bool(hits)

            clean_detected += int(detected)

            recording = path.stem

            clean_by_version[version][recording] = detected

            all_rows.append({
                "version": version,
                "recording": recording,
                "class": "cover",
                "file": str(path.relative_to(ROOT)),
                "packet_count": len(packets),
                "hit_count": len(hits),
                "predicted_label": result["label"],
                "hit_packet_indices_zero_based": ";".join(
                    str(h["packet_index"]) for h in hits
                ),
                "hit_payload_lengths": ";".join(
                    str(h["payload_length"]) for h in hits
                ),
                "expected_frame": "",
                "target_hit_zero_based": "",
                "target_hit_one_based": ""
            })

            input_hash_rows.append({
                "version": version,
                "class": "cover",
                "recording": recording,
                "sha256": sha256(path)
            })

            if i % 100 == 0:
                print(
                    f"Clean scanned: {i}/999"
                )

        # --------------------------------------
        # POSITIVE CONTROLS
        # --------------------------------------

        positive_detected = 0
        target_hit_zero = 0
        target_hit_one = 0

        for recording, (path, frame) in sorted(
            positive_map.items()
        ):

            packets = parse_bitstream(path)

            result = detector(
                packets,
                tail_size=TAIL_SIZE,
                max_payload=MAX_PAYLOAD
            )

            hits = result["hits"]

            detected = bool(hits)

            positive_detected += int(detected)

            indices = {
                h["packet_index"] for h in hits
            }

            # Do not assume the B7 frame numbering convention.
            hit_zero = frame in indices
            hit_one = (frame - 1) in indices

            target_hit_zero += int(hit_zero)
            target_hit_one += int(hit_one)

            positive_by_version[version][recording] = detected

            audit = audit_map[(version, recording)]
            functional = result_map[(version, recording)]

            positive_rows.append({
                "version": version,
                "recording": recording,
                "file": str(path.relative_to(ROOT)),
                "expected_frame_from_manifest": frame,
                "packet_count": len(packets),
                "hit_count": len(hits),
                "detected_anywhere": detected,
                "hit_packet_indices_zero_based": ";".join(
                    str(h["packet_index"]) for h in hits
                ),
                "target_hit_if_frame_zero_based": hit_zero,
                "target_hit_if_frame_one_based": hit_one,
                "payload_recovered": functional["payload_recovered"],
                "pcm_identical": functional["pcm_byte_identical"],
                "packet_lengths_preserved": functional["packet_length_preserved"],
                "independent_payload_correct": audit["payload_correct"],
                "other_packets_unchanged": audit["other_packets_unchanged"],
                "target_prefix_unchanged": audit["target_prefix_unchanged"]
            })

            all_rows.append({
                "version": version,
                "recording": recording,
                "class": "stego_positive_control",
                "file": str(path.relative_to(ROOT)),
                "packet_count": len(packets),
                "hit_count": len(hits),
                "predicted_label": result["label"],
                "hit_packet_indices_zero_based": ";".join(
                    str(h["packet_index"]) for h in hits
                ),
                "hit_payload_lengths": ";".join(
                    str(h["payload_length"]) for h in hits
                ),
                "expected_frame": frame,
                "target_hit_zero_based": hit_zero,
                "target_hit_one_based": hit_one
            })

            input_hash_rows.append({
                "version": version,
                "class": "stego_positive_control",
                "recording": recording,
                "sha256": sha256(path)
            })

        clean_low, clean_high = wilson(
            clean_detected, len(clean_files)
        )

        positive_low, positive_high = wilson(
            positive_detected, len(stego_files)
        )

        print("\nCLEAN NATURAL MUSIC")
        print("Total:", len(clean_files))
        print("False positives:", clean_detected)
        print(
            "FPR:",
            f"{clean_detected/len(clean_files):.6f}"
        )
        print(
            "Wilson 95% CI:",
            f"[{clean_low:.6f}, {clean_high:.6f}]"
        )

        print("\nPOSITIVE CONTROLS")
        print("Total:", len(stego_files))
        print("Detected:", positive_detected)
        print(
            "TPR:",
            f"{positive_detected/len(stego_files):.6f}"
        )
        print(
            "Wilson 95% CI:",
            f"[{positive_low:.6f}, {positive_high:.6f}]"
        )

        print(
            "Target localization, zero-based:",
            target_hit_zero, "/", len(stego_files)
        )

        print(
            "Target localization, one-based:",
            target_hit_one, "/", len(stego_files)
        )

    # ------------------------------------------
    # CROSS-VERSION AGREEMENT
    # ------------------------------------------

    cross_rows = []

    common_clean = (
        set(clean_by_version["1.5.2"])
        & set(clean_by_version["1.6.1"])
    )

    both_clean_detected = sum(
        clean_by_version["1.5.2"][r]
        and clean_by_version["1.6.1"][r]
        for r in common_clean
    )

    only_152 = sum(
        clean_by_version["1.5.2"][r]
        and not clean_by_version["1.6.1"][r]
        for r in common_clean
    )

    only_161 = sum(
        not clean_by_version["1.5.2"][r]
        and clean_by_version["1.6.1"][r]
        for r in common_clean
    )

    neither = sum(
        not clean_by_version["1.5.2"][r]
        and not clean_by_version["1.6.1"][r]
        for r in common_clean
    )

    cross_rows.append({
        "class": "cover",
        "paired_recordings": len(common_clean),
        "both_detected": both_clean_detected,
        "only_1_5_2_detected": only_152,
        "only_1_6_1_detected": only_161,
        "neither_detected": neither
    })

    common_positive = (
        set(positive_by_version["1.5.2"])
        & set(positive_by_version["1.6.1"])
    )

    cross_rows.append({
        "class": "positive_control",
        "paired_recordings": len(common_positive),
        "both_detected": sum(
            positive_by_version["1.5.2"][r]
            and positive_by_version["1.6.1"][r]
            for r in common_positive
        ),
        "only_1_5_2_detected": sum(
            positive_by_version["1.5.2"][r]
            and not positive_by_version["1.6.1"][r]
            for r in common_positive
        ),
        "only_1_6_1_detected": sum(
            not positive_by_version["1.5.2"][r]
            and positive_by_version["1.6.1"][r]
            for r in common_positive
        ),
        "neither_detected": sum(
            not positive_by_version["1.5.2"][r]
            and not positive_by_version["1.6.1"][r]
            for r in common_positive
        )
    })

    # ------------------------------------------
    # SAVE RESULTS
    # ------------------------------------------

    write_csv(
        RUN / "b15_recording_results.csv",
        all_rows
    )

    write_csv(
        RUN / "b15_positive_control_audit.csv",
        positive_rows
    )

    write_csv(
        RUN / "b15_cross_version_agreement.csv",
        cross_rows
    )

    write_csv(
        RUN / "b15_input_bitstream_hashes.csv",
        input_hash_rows
    )

    summary_rows = []

    for version in VERSIONS:

        clean = [
            r for r in all_rows
            if r["version"] == version
            and r["class"] == "cover"
        ]

        positive = [
            r for r in all_rows
            if r["version"] == version
            and r["class"] == "stego_positive_control"
        ]

        fp = sum(
            r["predicted_label"] == "stego"
            for r in clean
        )

        tp = sum(
            r["predicted_label"] == "stego"
            for r in positive
        )

        lo, hi = wilson(fp, len(clean))
        tp_lo, tp_hi = wilson(tp, len(positive))

        summary_rows.append({
            "version": version,
            "clean_recordings": len(clean),
            "false_positives": fp,
            "fpr": fp / len(clean),
            "fpr_wilson_95_low": lo,
            "fpr_wilson_95_high": hi,
            "positive_controls": len(positive),
            "positive_detected": tp,
            "tpr": tp / len(positive),
            "tpr_wilson_95_low": tp_lo,
            "tpr_wilson_95_high": tp_hi
        })

    write_csv(
        RUN / "b15_version_summary.csv",
        summary_rows
    )

    config = {
        "experiment": "B15 natural-cover false-positive audit",
        "b7_run": str(B7),
        "detector_source": str(DETECTOR_FILE),
        "detector_sha256": sha256(DETECTOR_FILE),
        "versions": VERSIONS,
        "clean_recordings_per_version": 999,
        "positive_controls_per_version": 10,
        "tail_size": TAIL_SIZE,
        "max_payload": MAX_PAYLOAD,
        "detector": "blind_structural_scan",
        "blind_packet_scan": True,
        "source_bitstreams_modified": False,
        "packet_length_prefix_bytes": 4,
        "packet_length_byte_order": "native",
        "positive_frame_numbering": "both conventions reported"
    }

    (RUN / "b15_run_config.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8"
    )

    shutil.copy2(
        Path(__file__).resolve(),
        RUN / "b15_run.py"
    )

    report = []

    report.extend([
        "========== B15 INDEPENDENT NATURAL-COVER AUDIT ==========",
        f"Run: {RUN}",
        f"B7 source: {B7}",
        f"Detector SHA256: {sha256(DETECTOR_FILE)}",
        "",
        "DETECTOR CONFIGURATION",
        f"Tail size: {TAIL_SIZE}",
        f"Maximum payload: {MAX_PAYLOAD}",
        "Packet scan: all packets, no target location supplied",
        "",
        "VERSION SUMMARY"
    ])

    for r in summary_rows:

        report.append(
            f"{r['version']}: "
            f"FPR={r['false_positives']}/{r['clean_recordings']} "
            f"({r['fpr']:.6f}), "
            f"95% CI=[{r['fpr_wilson_95_low']:.6f},"
            f"{r['fpr_wilson_95_high']:.6f}]; "
            f"TPR={r['positive_detected']}/{r['positive_controls']} "
            f"({r['tpr']:.6f}), "
            f"95% CI=[{r['tpr_wilson_95_low']:.6f},"
            f"{r['tpr_wilson_95_high']:.6f}]"
        )

    report.extend([
        "",
        "CROSS-VERSION AGREEMENT",
        str(cross_rows),
        "",
        "INTERPRETATION LIMITS",
        "- Clean recordings are GTZAN natural-music covers.",
        "- The same source recordings occur in both encoder groups.",
        "- Positive controls use 10 source recordings per version.",
        "- Positive-control sample size is small.",
        "- Wilson intervals quantify sampling uncertainty.",
        "- The detector specifically targets printable,",
        "  length-prefixed payloads followed by zero padding.",
        "- Results do not establish universal detectability.",
        "- This experiment does not evaluate arbitrary steganographic methods.",
        "- This experiment does not evaluate B14 machine-learning models.",
        "- Original source bitstreams were not modified.",
        "",
        "B15 STATUS: COMPLETE"
    ])

    (RUN / "b15_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    # Output integrity inventory
    checksum_lines = []

    for path in sorted(RUN.iterdir()):

        if path.is_file() and path.name != "b15_checksums.sha256":

            checksum_lines.append(
                f"{sha256(path)}  {path.name}"
            )

    (RUN / "b15_checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8"
    )

    print("\n========== B15 FINAL SUMMARY ==========")

    for r in summary_rows:
        print(r)

    print("\nCross-version agreement:")
    for r in cross_rows:
        print(r)

    print("\nOutput directory:", RUN)
    print("Recording rows:", len(all_rows))
    print("Positive-control rows:", len(positive_rows))
    print("Input hashes:", len(input_hash_rows))
    print("Checksums:", RUN / "b15_checksums.sha256")
    print("\nB15 NATURAL-COVER AUDIT: COMPLETE")


if __name__ == "__main__":
    main()
