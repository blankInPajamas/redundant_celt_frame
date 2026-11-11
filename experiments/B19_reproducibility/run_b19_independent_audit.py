#!/usr/bin/env python3
"""B19 independent reproducibility and evidence-integrity audit.

Read-only audit of frozen B17/B17-supplementary/B18/B12 evidence.
Also performs the previously omitted malformed-target-length decoder check
on the same 20-recording B18 decoder sample (both decoder versions).

No models are trained, no thresholds are tuned, and no B9/B12/B17/B18
source artifacts are modified. New audit outputs go under experiments/B19.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import subprocess
import tempfile
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import confusion_matrix, roc_auc_score

ROOT = Path.home() / "research/redundant_celt_frame_steganography"
B9 = ROOT / "experiments/B9_common_voice"
B12_DEFAULT = B9 / "results/b12_payload_reliability/run_20261104_020705"
B17_DEFAULT = ROOT / "experiments/B17_cross_domain/results/b17_music_cross_domain/run_20261106_005837"
B17_SUPP_DEFAULT = ROOT / "experiments/B17_cross_domain/results/b17_supplementary_audit/run_20261106_012816"
B18_DEFAULT = ROOT / "experiments/B18_robustness/results/run_20261106_012823_895999"

B12_MANIFEST_SHA256 = "e993cd21001ff1d16467f8bab65ef5fb4dbaa2138a3b8aeb95cc0084b9e8c9b8"
VERSIONS = ("1.5.2", "1.6.1")
DECODERS = {v: ROOT / f"scripts/decode_raw_{v}" for v in VERSIONS}
TAIL_CAPACITY = 36
EXPECTED_TRANSFORMS = (
    "payload_bitflip",
    "target_marker_bitflip",
    "noncarrier_packet_bitflip",
    "drop_carrier_packet",
    "drop_preceding_packet",
    "swap_carrier_adjacent",
    "truncate_carrier_packet",
    "malformed_target_length",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def truth(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def add_check(checks, name, passed, detail):
    checks.append({
        "check": name,
        "status": "PASS" if passed else "FAIL",
        "detail": str(detail),
    })


def verify_checksum_manifest(directory: Path, manifest_name: str, checks, label):
    manifest = directory / manifest_name
    if not manifest.is_file():
        add_check(checks, f"{label} checksum manifest", False, f"Missing {manifest}")
        return 0, 1
    verified = 0
    failures = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        expected, rel = parts
        rel = rel.lstrip("*")
        path = (directory / rel).resolve()
        exists = path.is_file() and path.is_relative_to(directory.resolve())
        actual = sha256_file(path) if exists else ""
        if exists and actual == expected:
            verified += 1
        else:
            failures.append(
                f"{rel}: " + ("missing/outside run directory" if not exists else "SHA256 mismatch")
            )
    add_check(
        checks, f"{label} checksum manifest",
        not failures,
        f"{verified} verified; {len(failures)} failures"
        + (("; " + "; ".join(failures[:5])) if failures else ""),
    )
    return verified, len(failures)


def parse_packets(raw: bytes):
    packets = []
    offset = 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError("incomplete 4-byte packet header")
        n = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if n <= 0:
            raise ValueError(f"invalid zero/negative packet length: {n}")
        if offset + n > len(raw):
            raise ValueError(f"packet length {n} exceeds remaining bytes")
        packets.append(raw[offset:offset+n])
        offset += n
    if not packets:
        raise ValueError("no packets")
    return packets


def safe_child(root: Path, relative: str):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes expected root: {relative}")
    return path


def audit_b17(b17: Path, checks):
    verify_checksum_manifest(b17, "b17_checksums.sha256", checks, "B17 original")
    metrics_path = b17 / "b17_cross_domain_metrics.csv"
    predictions_path = b17 / "b17_music_predictions.csv"
    metrics = read_csv(metrics_path)
    predictions = read_csv(predictions_path)
    add_check(checks, "B17 metric row count", len(metrics) == 40, f"rows={len(metrics)}")
    add_check(
        checks, "B17 prediction row count",
        len(predictions) == 40360, f"rows={len(predictions)}"
    )

    for row in predictions:
        row["training_payload_size_bytes"] = int(row["training_payload_size_bytes"])
        row["y_true"] = int(row["y_true"])
        row["y_pred"] = int(row["y_pred"])
        row["y_score"] = float(row["y_score"])

    recomputed = []
    failures = []
    for metric in metrics:
        size = int(metric["training_payload_size_bytes"])
        encoder = metric["test_encoder"]
        model = metric["model"]
        feature_group = metric["feature_group"]
        subset = [
            r for r in predictions
            if r["training_payload_size_bytes"] == size
            and r["test_encoder"] == encoder
            and r["model"] == model
            and r["feature_group"] == feature_group
        ]
        if not subset:
            failures.append(f"empty prediction group {encoder}/{model}/{size}/{feature_group}")
            continue
        y = np.asarray([r["y_true"] for r in subset], dtype=int)
        score = np.asarray([r["y_score"] for r in subset], dtype=float)
        pred = np.asarray([r["y_pred"] for r in subset], dtype=int)
        if len(set(y)) != 2:
            failures.append(f"single-class group {encoder}/{model}/{size}/{feature_group}")
            continue
        auc = float(roc_auc_score(y, score))
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        auc_ok = abs(auc - float(metric["roc_auc"])) <= 1e-10
        cm_ok = (tn, fp, fn, tp) == tuple(
            int(metric[k]) for k in ("tn", "fp", "fn", "tp")
        )
        recomputed.append({
            "training_payload_size_bytes": size,
            "test_encoder": encoder,
            "model": model,
            "feature_group": feature_group,
            "n_predictions": len(subset),
            "recomputed_auc": auc,
            "stored_auc": float(metric["roc_auc"]),
            "auc_match": auc_ok,
            "confusion_matrix_match": cm_ok,
        })
        if not auc_ok or not cm_ok:
            failures.append(
                f"metric mismatch {encoder}/{model}/{size}/{feature_group}: "
                f"AUC={auc_ok}, confusion={cm_ok}"
            )
    add_check(
        checks, "B17 metrics independently recomputed",
        len(recomputed) == 40 and not failures,
        f"{len(recomputed)}/40 groups matched"
        + (("; " + "; ".join(failures[:5])) if failures else ""),
    )
    return recomputed, predictions


def audit_b17_supplementary(b17_supp: Path, b17_predictions, checks):
    verify_checksum_manifest(
        b17_supp, "b17_supplementary_checksums.sha256",
        checks, "B17 supplementary"
    )
    summary = read_csv(b17_supp / "b17_supplementary_summary.csv")
    pairs = read_csv(b17_supp / "b17_paired_score_audit.csv")
    genre = read_csv(b17_supp / "b17_genre_stratified_metrics.csv")
    add_check(checks, "B17 supplementary summary rows", len(summary) == 4, f"rows={len(summary)}")
    add_check(checks, "B17 matched-pair rows", len(pairs) == 40, f"rows={len(pairs)}")

    pair_failures = []
    for s in summary:
        encoder, model = s["test_encoder"], s["model"]
        subset = [
            p for p in pairs
            if p["test_encoder"] == encoder and p["model"] == model
        ]
        if len(subset) != 10:
            pair_failures.append(f"{encoder}/{model}: pair count={len(subset)}")
            continue
        deltas = [
            float(p["positive_score"]) - float(p["clean_score"])
            for p in subset
        ]
        higher = sum(d > 0 for d in deltas)
        mean_delta = float(np.mean(deltas))
        if higher != int(s["matched_positive_higher"]):
            pair_failures.append(f"{encoder}/{model}: matched direction count mismatch")
        if abs(mean_delta - float(s["mean_paired_score_delta"])) > 1e-10:
            pair_failures.append(f"{encoder}/{model}: mean paired delta mismatch")

        labels, scores = [], []
        for p in subset:
            labels.extend((0, 1))
            scores.extend((float(p["clean_score"]), float(p["positive_score"])))
        matched_auc = float(roc_auc_score(labels, scores))
        if abs(matched_auc - float(s["matched_only_auc"])) > 1e-10:
            pair_failures.append(f"{encoder}/{model}: matched-only AUC mismatch")

        # Independently recompute hip-hop-only AUC from the frozen predictions.
        hip = [
            p for p in b17_predictions
            if int(p["training_payload_size_bytes"]) == 36
            and p["test_encoder"] == encoder
            and p["model"] == model
            and p["feature_group"] == "global_without_packet_geometry"
            and p["recording"].split("__", 1)[0] == "hiphop"
        ]
        hy = np.asarray([p["y_true"] for p in hip], dtype=int)
        hs = np.asarray([p["y_score"] for p in hip], dtype=float)
        if len(set(hy)) != 2:
            pair_failures.append(f"{encoder}/{model}: hip-hop subset lacks both classes")
        else:
            hip_auc = float(roc_auc_score(hy, hs))
            if abs(hip_auc - float(s["hiphop_only_auc"])) > 1e-10:
                pair_failures.append(f"{encoder}/{model}: hip-hop AUC mismatch")

    add_check(
        checks, "B17 supplementary statistics independently recomputed",
        len(summary) == 4 and not pair_failures,
        "4 conditions checked"
        + (("; " + "; ".join(pair_failures[:8])) if pair_failures else ""),
    )
    add_check(
        checks, "B17 positive-control genre scope",
        all(r["genre"] == "hiphop" for r in genre if int(r["n_positive"]) > 0),
        "All genre rows containing positives should be hip-hop",
    )
    return summary, pairs, genre


def audit_b18(b12: Path, b18: Path, checks):
    verify_checksum_manifest(b18, "b18_checksums.sha256", checks, "B18")
    manifest_path = b12 / "b12_payload_manifest.csv"
    manifest_hash = sha256_file(manifest_path)
    add_check(
        checks, "B12 manifest SHA256",
        manifest_hash == B12_MANIFEST_SHA256,
        f"actual={manifest_hash}",
    )
    manifest = read_csv(manifest_path)
    selected = [
        r for r in manifest
        if int(r["payload_size_bytes"]) in (32, 36)
        and int(r["repetition"]) == 1
    ]
    add_check(checks, "B12 selected row count", len(selected) == 400, f"rows={len(selected)}")

    source_failures = []
    for row in selected:
        version, recording = row["encoder"], row["recording"]
        source = B9 / "results/b9_full_encoding" / version / "bitstreams" / f"{recording}.bin"
        stego = safe_child(b12, row["modified_bitstream"])
        if not source.is_file() or not stego.is_file():
            source_failures.append(f"missing {version}/{recording}")
            continue
        if sha256_file(source) != row["source_bitstream_sha256"]:
            source_failures.append(f"source SHA mismatch {version}/{recording}")
        if sha256_file(stego) != row["modified_bitstream_sha256"]:
            source_failures.append(f"stego SHA mismatch {version}/{recording}")
    add_check(
        checks, "B12 source/stego bitstreams revalidated",
        not source_failures,
        f"{len(selected)} manifest rows checked; {len(source_failures)} failures"
        + (("; " + "; ".join(source_failures[:5])) if source_failures else ""),
    )

    transform_rows = read_csv(b18 / "b18_transformation_results.csv")
    summary_rows = read_csv(b18 / "b18_transformation_summary.csv")
    add_check(
        checks, "B18 transformation row count",
        len(transform_rows) == 3200, f"rows={len(transform_rows)}"
    )
    add_check(
        checks, "B18 transformation summary row count",
        len(summary_rows) == 32, f"rows={len(summary_rows)}"
    )

    manifest_by_key = {
        (r["encoder"], r["recording"], int(r["payload_size_bytes"])): r
        for r in selected
    }
    transformed_failures = []
    group_counts = Counter()
    recomputed_counts = defaultdict(Counter)

    for row in transform_rows:
        version = row["encoder"]
        recording = row["recording"]
        size = int(row["payload_size_bytes"])
        transform = row["transformation"]
        key = (version, recording, size)
        source_row = manifest_by_key.get(key)
        group_counts[(version, size, transform)] += 1
        if source_row is None:
            transformed_failures.append(f"no B12 row for {key}")
            continue

        path = safe_child(b18, row["transformed_bitstream"])
        if not path.is_file():
            transformed_failures.append(f"missing transformed file {row['transformed_bitstream']}")
            continue
        raw = path.read_bytes()
        if sha256_bytes(raw) != row["transformed_sha256"]:
            transformed_failures.append(f"transformed SHA mismatch {row['transformed_bitstream']}")

        parse_valid = True
        packets = None
        try:
            packets = parse_packets(raw)
        except Exception:
            parse_valid = False

        if parse_valid != truth(row["parser_valid"]):
            transformed_failures.append(f"parser flag mismatch {key}/{transform}")
        recomputed_counts[(version, size, transform)]["parser_valid"] += int(parse_valid)

        payload = bytes.fromhex(source_row["payload_hex"])
        expected_tail = bytes(TAIL_CAPACITY - size) + payload
        frame = int(source_row["frame"])
        hits = []
        if parse_valid:
            hits = [
                i for i, packet in enumerate(packets)
                if len(packet) >= TAIL_CAPACITY
                and packet[-TAIL_CAPACITY:] == expected_tail
            ]
        at_original = frame in hits
        anywhere = bool(hits)
        if at_original != truth(row["payload_exact_at_original_index"]):
            transformed_failures.append(f"original-index result mismatch {key}/{transform}")
        if anywhere != truth(row["payload_exact_anywhere"]):
            transformed_failures.append(f"anywhere result mismatch {key}/{transform}")
        recomputed_counts[(version, size, transform)]["at_original"] += int(at_original)
        recomputed_counts[(version, size, transform)]["anywhere"] += int(anywhere)

    expected_group_keys = {
        (v, size, t)
        for v in VERSIONS for size in (32, 36) for t in EXPECTED_TRANSFORMS
    }
    groups_ok = (
        set(group_counts) == expected_group_keys
        and all(group_counts[k] == 100 for k in expected_group_keys)
    )
    add_check(
        checks, "B18 transformation design balance",
        groups_ok,
        f"{len(group_counts)} groups; expected 32 groups × 100 cases",
    )
    add_check(
        checks, "B18 transformed bitstreams and payload outcomes independently revalidated",
        not transformed_failures,
        f"{len(transform_rows)} rows checked; {len(transformed_failures)} failures"
        + (("; " + "; ".join(transformed_failures[:8])) if transformed_failures else ""),
    )

    summary_failures = []
    for s in summary_rows:
        key = (s["encoder"], int(s["payload_size_bytes"]), s["transformation"])
        n = group_counts[key]
        counts = recomputed_counts[key]
        checks_map = {
            "parser_valid_n": counts["parser_valid"],
            "payload_exact_at_original_index_n": counts["at_original"],
            "payload_exact_anywhere_n": counts["anywhere"],
        }
        for field, value in checks_map.items():
            if int(s[field]) != value:
                summary_failures.append(f"{key}: {field} stored={s[field]} recomputed={value}")
        if int(s["n_events"]) != n:
            summary_failures.append(f"{key}: event count mismatch")
    add_check(
        checks, "B18 transformation summary independently recomputed",
        not summary_failures,
        f"{len(summary_rows)} groups checked"
        + (("; " + "; ".join(summary_failures[:8])) if summary_failures else ""),
    )

    decoder_rows = read_csv(b18 / "b18_decoder_results.csv")
    pcm_rows = read_csv(b18 / "b18_pcm_pair_audit.csv")
    reencode_rows = read_csv(b18 / "b18_codec_reencode_results.csv")
    add_check(
        checks, "B18 decoder result row count",
        len(decoder_rows) == 360, f"rows={len(decoder_rows)}"
    )
    decoder_groups = defaultdict(list)
    for r in decoder_rows:
        decoder_groups[(r["source_encoder"], r["decoder_version"], r["variant"])].append(r)
    decoder_design_ok = (
        len(decoder_groups) == 36
        and all(len(g) == 10 for g in decoder_groups.values())
    )
    decoder_complete = sum(truth(r["decode_complete"]) for r in decoder_rows)
    add_check(
        checks, "B18 decoder sample completion",
        decoder_design_ok and decoder_complete == len(decoder_rows),
        f"{decoder_complete}/{len(decoder_rows)} complete; "
        f"{len(decoder_groups)} groups",
    )
    add_check(
        checks, "B18 PCM pair identity",
        len(pcm_rows) == 40 and all(
            truth(r["cover_decode_complete"])
            and truth(r["stego_decode_complete"])
            and truth(r["same_decoder_pcm_identical"])
            for r in pcm_rows
        ),
        f"{sum(truth(r['same_decoder_pcm_identical']) for r in pcm_rows)}/{len(pcm_rows)} identical",
    )
    reencode_ok = (
        len(reencode_rows) == 60
        and all(r["status"] == "COMPLETE" for r in reencode_rows)
        and all(truth(r["cover_stego_pcm_identical"]) for r in reencode_rows)
        and all(truth(r["reencoded_bitstreams_identical"]) for r in reencode_rows)
        and all(not truth(r["payload_exact_in_reencoded_stego"]) for r in reencode_rows)
        and all(truth(r["reencoded_stego_decode_complete"]) for r in reencode_rows)
    )
    add_check(
        checks, "B18 codec re-encoding outcomes",
        reencode_ok,
        f"{len(reencode_rows)} trials; "
        f"PCM-identical={sum(truth(r['cover_stego_pcm_identical']) for r in reencode_rows)}; "
        f"bitstream-identical={sum(truth(r['reencoded_bitstreams_identical']) for r in reencode_rows)}; "
        f"payload recovered={sum(truth(r['payload_exact_in_reencoded_stego']) for r in reencode_rows)}",
    )
    return transform_rows, decoder_rows


def test_malformed_length_decoders(b18: Path, decoder_rows, transform_rows, out: Path):
    """Test malformed_target_length on the same 10 × 2 encoder sample,
    with both decoder binaries. This was not included in the original B18
    decoder-variant matrix.
    """
    sample = defaultdict(set)
    for row in decoder_rows:
        if row["variant"] == "cover" and int(row["payload_size_bytes"]) == 36:
            sample[row["source_encoder"]].add(row["recording"])

    transform_index = {
        (r["encoder"], r["recording"], int(r["payload_size_bytes"]), r["transformation"]): r
        for r in transform_rows
    }
    temp_root = out / "tmp_malformed_decoder"
    temp_root.mkdir(parents=True, exist_ok=True)
    results = []

    for source_encoder in VERSIONS:
        recordings = sorted(sample[source_encoder])
        if len(recordings) != 10:
            raise ValueError(
                f"Expected 10 B18 decoder-sample recordings for {source_encoder}; "
                f"found {len(recordings)}"
            )
        for recording in recordings:
            trow = transform_index.get(
                (source_encoder, recording, 36, "malformed_target_length")
            )
            if trow is None:
                raise ValueError(f"Missing malformed transform row: {source_encoder}/{recording}")
            bitstream = safe_child(b18, trow["transformed_bitstream"])
            expected_frames = int(trow["packet_count_original"])
            for decoder_version in VERSIONS:
                decoder = DECODERS[decoder_version]
                with tempfile.TemporaryDirectory(prefix="b19_badlen_", dir=temp_root) as td:
                    pcm = Path(td) / "decoded.pcm"
                    try:
                        proc = subprocess.run(
                            [str(decoder), str(bitstream), str(pcm)],
                            capture_output=True, text=True, timeout=180,
                            cwd=td,
                        )
                        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
                        match = re.search(r"Decoded\s+(\d+)\s+frames", log)
                        decoded_frames = int(match.group(1)) if match else -1
                        pcm_exists = pcm.is_file()
                        pcm_bytes = pcm.stat().st_size if pcm_exists else 0
                        pcm_hash = sha256_file(pcm) if pcm_exists else ""
                        complete = (
                            proc.returncode == 0 and pcm_exists
                            and decoded_frames == expected_frames
                            and "opus_decode failed" not in log
                            and "Invalid packet length" not in log
                        )
                        results.append({
                            "source_encoder": source_encoder,
                            "recording": recording,
                            "payload_size_bytes": 36,
                            "decoder_version": decoder_version,
                            "transformation": "malformed_target_length",
                            "expected_frames_from_original": expected_frames,
                            "returncode": proc.returncode,
                            "decoded_frames": decoded_frames,
                            "pcm_exists": pcm_exists,
                            "pcm_bytes": pcm_bytes,
                            "pcm_sha256": pcm_hash,
                            "decode_complete_by_original_frame_count": complete,
                            "error_excerpt": " | ".join(
                                line.strip() for line in log.splitlines()
                                if any(x in line.lower() for x in ("error", "failed", "invalid"))
                            )[:500],
                            "log_excerpt": " | ".join(log.splitlines())[-1200:],
                        })
                    except subprocess.TimeoutExpired:
                        results.append({
                            "source_encoder": source_encoder,
                            "recording": recording,
                            "payload_size_bytes": 36,
                            "decoder_version": decoder_version,
                            "transformation": "malformed_target_length",
                            "expected_frames_from_original": expected_frames,
                            "returncode": -999,
                            "decoded_frames": -1,
                            "pcm_exists": False,
                            "pcm_bytes": 0,
                            "pcm_sha256": "",
                            "decode_complete_by_original_frame_count": False,
                            "error_excerpt": "decoder timeout",
                            "log_excerpt": "decoder timeout",
                        })
    shutil.rmtree(temp_root, ignore_errors=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b12-run", type=Path, default=B12_DEFAULT)
    parser.add_argument("--b17-run", type=Path, default=B17_DEFAULT)
    parser.add_argument("--b17-supp-run", type=Path, default=B17_SUPP_DEFAULT)
    parser.add_argument("--b18-run", type=Path, default=B18_DEFAULT)
    args = parser.parse_args()

    b12 = args.b12_run.expanduser().resolve()
    b17 = args.b17_run.expanduser().resolve()
    b17_supp = args.b17_supp_run.expanduser().resolve()
    b18 = args.b18_run.expanduser().resolve()

    for path in (b12, b17, b17_supp, b18):
        if not path.is_dir():
            raise FileNotFoundError(path)
    for decoder in DECODERS.values():
        if not decoder.is_file() or not decoder.stat().st_mode & 0o111:
            raise FileNotFoundError(f"Missing/non-executable decoder: {decoder}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = ROOT / "experiments/B19_reproducibility/results" / f"run_{stamp}"
    out.mkdir(parents=True, exist_ok=False)

    print("========== B19 INDEPENDENT EVIDENCE AUDIT ==========")
    print("Project:", ROOT)
    print("B12:", b12)
    print("B17:", b17)
    print("B17 supplementary:", b17_supp)
    print("B18:", b18)
    print("Output:", out)

    checks = []
    b17_recomputed, b17_predictions = audit_b17(b17, checks)
    b17_summary, b17_pairs, b17_genre = audit_b17_supplementary(
        b17_supp, b17_predictions, checks
    )
    b18_transform_rows, b18_decoder_rows = audit_b18(b12, b18, checks)

    print("\n========== MALFORMED-LENGTH DECODER FOLLOW-UP ==========")
    malformed_rows = test_malformed_length_decoders(
        b18, b18_decoder_rows, b18_transform_rows, out
    )
    malformed_complete = sum(
        truth(r["decode_complete_by_original_frame_count"])
        for r in malformed_rows
    )
    print(
        "Malformed-length decoder tests:",
        malformed_complete, "/", len(malformed_rows),
        "completed by original frame-count criterion"
    )

    write_csv(out / "b19_validation_results.csv", checks)
    write_csv(out / "b19_b17_recomputed_metrics.csv", b17_recomputed)
    write_csv(out / "b19_b17_supplementary_summary.csv", b17_summary)
    write_csv(out / "b19_b17_paired_score_audit.csv", b17_pairs)
    write_csv(out / "b19_b17_genre_metrics.csv", b17_genre)
    write_csv(out / "b19_malformed_length_decoder_results.csv", malformed_rows)

    failures = [r for r in checks if r["status"] != "PASS"]
    report = [
        "========== B19 INDEPENDENT REPRODUCIBILITY AND EVIDENCE AUDIT ==========",
        f"Project: {ROOT}",
        f"B12 input: {b12}",
        f"B17 input: {b17}",
        f"B17 supplementary input: {b17_supp}",
        f"B18 input: {b18}",
        f"Output: {out}",
        "",
        "========== INDEPENDENT VALIDATION ==========",
        f"Checks passed: {len(checks) - len(failures)}/{len(checks)}",
        f"Checks failed: {len(failures)}",
    ]
    for row in checks:
        report.append(f"{row['status']} | {row['check']} | {row['detail']}")
    report += [
        "",
        "========== MALFORMED TARGET-LENGTH DECODER FOLLOW-UP ==========",
        f"Tests: {len(malformed_rows)} (20 recordings × 2 decoder versions)",
        f"Completed by original frame-count criterion: {malformed_complete}/{len(malformed_rows)}",
        "This case was absent from the original B18 decoder-variant matrix.",
        "",
        "========== MANUSCRIPT INTERPRETATION NOTES ==========",
        "- B18 decoder completion means the custom decoder produced the expected frame count and output file; it does not by itself establish perceptual quality.",
        "- B18 PCM identity is bit-exact for the tested 20-recording sample and two decoder versions.",
        "- B18 re-encoding results are exploratory: 20 recordings, 10 per source encoder, at three bitrates.",
        "- The B18 transformation named target_marker_bitflip changes the byte immediately preceding the 36-byte tail. Confirm that byte's semantic role in the codec source before calling it a marker in the manuscript.",
        "- The B18 malformed_target_length transformation was parser-tested on all 400 event-size rows; B19 adds decoder tests on the 20-recording 36-byte decoder sample.",
        "- Packet deletion/reordering experiments operate on the custom packet-sequence files, not a full RTP/network simulation.",
        "- Positive music controls in B17 are limited to 10 hip-hop recordings; matched-pair direction does not establish general music-domain detection.",
        "- No universal cross-domain detection, network robustness, or arbitrary-transcoding claim is established.",
        "",
        "========== FINAL STATUS ==========",
        "PASS" if not failures else "REVIEW REQUIRED",
    ]
    (out / "b19_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    config = {
        "experiment": "B19 independent reproducibility and evidence-integrity audit",
        "b12_run": str(b12),
        "b17_run": str(b17),
        "b17_supplementary_run": str(b17_supp),
        "b18_run": str(b18),
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failures),
        "checks_failed": len(failures),
        "malformed_length_decoder_tests": len(malformed_rows),
        "malformed_length_decoder_completed": malformed_complete,
        "models_retrained": False,
        "thresholds_retuned": False,
        "source_artifacts_modified": False,
    }
    (out / "b19_run_config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    checksum_path = out / "b19_checksums.sha256"
    lines = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p != checksum_path):
        lines.append(f"{sha256_file(path)}  {path.relative_to(out)}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n========== B19 FINAL SUMMARY ==========")
    print(f"Checks passed: {len(checks) - len(failures)}/{len(checks)}")
    print(f"Checks failed: {len(failures)}")
    for row in failures:
        print("FAIL:", row["check"], "|", row["detail"])
    print(
        "Malformed-length decoder completion:",
        f"{malformed_complete}/{len(malformed_rows)}"
    )
    print("\nB19 AUDIT:", "PASS" if not failures else "REVIEW REQUIRED")
    print("Report:", out / "b19_report.txt")
    print("Validation:", out / "b19_validation_results.csv")
    print("Malformed-length decoder results:", out / "b19_malformed_length_decoder_results.csv")
    print("Checksums:", checksum_path)


if __name__ == "__main__":
    main()
