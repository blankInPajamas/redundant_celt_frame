#!/usr/bin/env python3
"""B17 supplementary audit: matched-pair and genre-stratified diagnostics.

This is a read-only audit of the frozen B17 outputs. It does not retrain
models, retune thresholds, or modify the original B17 run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import confusion_matrix, roc_auc_score

ROOT = Path.home() / "research/redundant_celt_frame_steganography"
B17 = ROOT / "experiments/B17_cross_domain"
DEFAULT_RUN = B17 / "results/b17_music_cross_domain/run_20261106_005837"
PRIMARY_SIZE = 36
PRIMARY_GROUP = "global_without_packet_geometry"
BOOTSTRAP_REPS = 5000
SEED = 20261106


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_checksums(directory: Path):
    lines = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()
                       and p.name != "b17_supplementary_checksums.sha256"):
        lines.append(f"{sha256_file(path)}  {path.relative_to(directory)}")
    target = directory / "b17_supplementary_checksums.sha256"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = successes / n
    den = 1.0 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = z * math.sqrt((p*(1-p)/n) + z*z/(4*n*n)) / den
    return center-half, center+half


def bootstrap_mean_ci(values, seed, repetitions=BOOTSTRAP_REPS):
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(repetitions, dtype=float)
    for i in range(repetitions):
        means[i] = rng.choice(values, size=len(values), replace=True).mean()
    return tuple(np.percentile(means, [2.5, 97.5]))


def bootstrap_hiphop_auc(rows, seed, repetitions=BOOTSTRAP_REPS):
    """Cluster bootstrap: sample 10 matched positive/cover pairs and 90
    clean-only hip-hop recordings. Resampling unit is recording identity.
    """
    by_recording = defaultdict(dict)
    for row in rows:
        by_recording[row["recording"]][row["class"]] = float(row["y_score"])

    positive_ids = sorted(
        rec for rec, values in by_recording.items()
        if "positive" in values
    )
    cover_ids = sorted(
        rec for rec, values in by_recording.items()
        if "cover" in values
    )
    if not positive_ids or any("cover" not in by_recording[x] for x in positive_ids):
        raise ValueError("Every positive recording must have a matched clean cover")
    clean_only = sorted(set(cover_ids) - set(positive_ids))
    if len(positive_ids) != 10 or len(clean_only) != 90:
        raise ValueError(
            f"Expected 10 matched positive pairs and 90 clean-only hip-hop "
            f"recordings; got {len(positive_ids)} and {len(clean_only)}"
        )

    y_true = []
    y_score = []
    for rec in cover_ids:
        y_true.append(0)
        y_score.append(by_recording[rec]["cover"])
    for rec in positive_ids:
        y_true.append(1)
        y_score.append(by_recording[rec]["positive"])
    point = roc_auc_score(y_true, y_score)

    rng = np.random.default_rng(seed)
    values = np.empty(repetitions, dtype=float)
    for i in range(repetitions):
        sampled_pairs = rng.choice(positive_ids, size=len(positive_ids), replace=True)
        sampled_clean = rng.choice(clean_only, size=len(clean_only), replace=True)
        ys, scores = [], []
        for rec in sampled_pairs:
            ys.extend((0, 1))
            scores.extend((
                by_recording[rec]["cover"],
                by_recording[rec]["positive"],
            ))
        for rec in sampled_clean:
            ys.append(0)
            scores.append(by_recording[rec]["cover"])
        values[i] = roc_auc_score(ys, scores)
    low, high = np.percentile(values, [2.5, 97.5])
    return point, float(low), float(high), len(cover_ids), len(positive_ids), len(clean_only)


def verify_checksums(run_dir: Path):
    manifest = run_dir / "b17_checksums.sha256"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    rows = []
    core = {
        "b17_cross_domain_metrics.csv",
        "b17_music_predictions.csv",
        "b17_report.txt",
        "b17_run_config.json",
    }
    core_failures = []
    warnings = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        expected, rel = parts
        rel = rel.lstrip("*")
        path = (run_dir / rel).resolve()
        exists = path.is_file() and path.is_relative_to(run_dir.resolve())
        actual = sha256_file(path) if exists else ""
        passed = exists and actual == expected
        rows.append({
            "file": rel,
            "exists": exists,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if passed else ("MISSING" if not exists else "MISMATCH"),
        })
        if not passed:
            message = f"{rel}: {'missing' if not exists else 'checksum mismatch'}"
            if rel in core:
                core_failures.append(message)
            else:
                warnings.append(message)
    if core_failures:
        raise ValueError("Core B17 checksum failure: " + "; ".join(core_failures))
    return rows, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--bootstrap-repetitions", type=int, default=BOOTSTRAP_REPS)
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    metrics_path = run_dir / "b17_cross_domain_metrics.csv"
    predictions_path = run_dir / "b17_music_predictions.csv"
    config_path = run_dir / "b17_run_config.json"
    report_path = run_dir / "b17_report.txt"
    for path in (metrics_path, predictions_path, config_path, report_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    print("========== B17 SUPPLEMENTARY AUDIT ==========")
    print("Frozen B17 run:", run_dir)
    checksum_rows, checksum_warnings = verify_checksums(run_dir)
    print("Core checksum verification: PASS")
    print("Checksum entries:", len(checksum_rows))
    if checksum_warnings:
        print("Non-core checksum warnings:", len(checksum_warnings))
        for item in checksum_warnings:
            print("WARNING:", item)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    metrics = read_csv(metrics_path)
    predictions = read_csv(predictions_path)
    if len(metrics) != 40:
        raise ValueError(f"Expected 40 metric rows, found {len(metrics)}")
    if len(predictions) != 40360:
        raise ValueError(f"Expected 40,360 prediction rows, found {len(predictions)}")

    # Validate the frozen test design.
    for row in predictions:
        row["training_payload_size_bytes"] = int(row["training_payload_size_bytes"])
        row["y_true"] = int(row["y_true"])
        row["y_pred"] = int(row["y_pred"])
        row["y_score"] = float(row["y_score"])
        row["threshold"] = float(row["threshold"])
        row["genre"] = row["recording"].split("__", 1)[0]

    positive_recordings = sorted({
        r["recording"] for r in predictions if r["class"] == "positive"
    })
    positive_genres = sorted({
        r["genre"] for r in predictions if r["class"] == "positive"
    })
    if len(positive_recordings) != 10:
        raise ValueError(f"Expected 10 unique positive music recordings, got {len(positive_recordings)}")
    if positive_genres != ["hiphop"]:
        raise ValueError(f"Expected positive controls only in hiphop; got {positive_genres}")

    # One row per model/test/feature/size/recording/class is expected.
    primary = [
        r for r in predictions
        if r["training_payload_size_bytes"] == PRIMARY_SIZE
        and r["feature_group"] == PRIMARY_GROUP
    ]
    pair_rows = []
    summary_rows = []
    genre_rows = []
    primary_conditions = sorted({
        (r["test_encoder"], r["model"]) for r in primary
    })

    for encoder, model in primary_conditions:
        rows = [
            r for r in primary
            if r["test_encoder"] == encoder and r["model"] == model
        ]
        by_recording = defaultdict(dict)
        for row in rows:
            if row["class"] in by_recording[row["recording"]]:
                raise ValueError("Duplicate class/recording prediction row")
            by_recording[row["recording"]][row["class"]] = row

        cover_ids = {rec for rec, d in by_recording.items() if "cover" in d}
        positive_ids = {rec for rec, d in by_recording.items() if "positive" in d}
        if len(cover_ids) != 999 or len(positive_ids) != 10:
            raise ValueError(
                f"{encoder}/{model}: expected 999 covers and 10 positives; "
                f"got {len(cover_ids)} and {len(positive_ids)}"
            )
        if not positive_ids.issubset(cover_ids):
            raise ValueError("Positive controls do not all have matched clean recordings")

        # Recompute pooled AUC and fixed-threshold confusion counts.
        y = np.asarray([r["y_true"] for r in rows], dtype=int)
        scores = np.asarray([r["y_score"] for r in rows], dtype=float)
        preds = np.asarray([r["y_pred"] for r in rows], dtype=int)
        recomputed_auc = float(roc_auc_score(y, scores))
        tn, fp, fn, tp = confusion_matrix(y, preds, labels=[0, 1]).ravel()
        stored = next(
            m for m in metrics
            if int(m["training_payload_size_bytes"]) == PRIMARY_SIZE
            and m["test_encoder"] == encoder
            and m["model"] == model
            and m["feature_group"] == PRIMARY_GROUP
        )
        auc_delta = abs(recomputed_auc - float(stored["roc_auc"]))
        if auc_delta > 1e-10:
            raise ValueError(f"AUC mismatch for {encoder}/{model}: {auc_delta}")
        if (tn, fp, fn, tp) != tuple(int(stored[k]) for k in ("tn", "fp", "fn", "tp")):
            raise ValueError(f"Confusion-matrix mismatch for {encoder}/{model}")

        deltas = []
        for rec in sorted(positive_ids):
            cover = by_recording[rec]["cover"]
            positive = by_recording[rec]["positive"]
            delta = positive["y_score"] - cover["y_score"]
            deltas.append(delta)
            pair_rows.append({
                "test_encoder": encoder,
                "model": model,
                "recording": rec,
                "genre": positive["genre"],
                "clean_score": cover["y_score"],
                "positive_score": positive["y_score"],
                "positive_minus_clean_score": delta,
                "positive_score_higher": delta > 0,
                "clean_prediction_at_0_5": cover["y_pred"],
                "positive_prediction_at_0_5": positive["y_pred"],
            })

        higher = sum(d > 0 for d in deltas)
        direction_low, direction_high = wilson_interval(higher, len(deltas))
        delta_low, delta_high = bootstrap_mean_ci(
            deltas, SEED + (0 if encoder == "1.5.2" else 100) + (0 if model == "logistic_regression" else 10),
            args.bootstrap_repetitions,
        )
        hiphop_rows = [r for r in rows if r["genre"] == "hiphop"]
        hip_auc, hip_low, hip_high, n_hip_covers, n_hip_pos, n_hip_clean_only = (
            bootstrap_hiphop_auc(
                hiphop_rows,
                SEED + (0 if encoder == "1.5.2" else 100) + (0 if model == "logistic_regression" else 10),
                args.bootstrap_repetitions,
            )
        )
        matched_y, matched_scores = [], []
        for rec in sorted(positive_ids):
            matched_y.extend((0, 1))
            matched_scores.extend((
                by_recording[rec]["cover"]["y_score"],
                by_recording[rec]["positive"]["y_score"],
            ))
        matched_auc = float(roc_auc_score(matched_y, matched_scores))

        summary_rows.append({
            "test_encoder": encoder,
            "model": model,
            "training_payload_size_bytes": PRIMARY_SIZE,
            "feature_group": PRIMARY_GROUP,
            "pooled_auc_recomputed": recomputed_auc,
            "pooled_auc_stored": float(stored["roc_auc"]),
            "pooled_tpr_at_0_5": tp / (tp + fn),
            "pooled_fpr_at_0_5": fp / (fp + tn),
            "pooled_balanced_accuracy_at_0_5": (
                (tp / (tp + fn)) + (tn / (tn + fp))
            ) / 2,
            "n_clean_all_genres": len(cover_ids),
            "n_positive": len(positive_ids),
            "positive_genres": ";".join(positive_genres),
            "n_matched_pairs": len(deltas),
            "matched_positive_higher": higher,
            "matched_direction_fraction": higher / len(deltas),
            "matched_direction_wilson95_low": direction_low,
            "matched_direction_wilson95_high": direction_high,
            "matched_only_auc": matched_auc,
            "mean_paired_score_delta": float(np.mean(deltas)),
            "mean_paired_score_delta_bootstrap95_low": delta_low,
            "mean_paired_score_delta_bootstrap95_high": delta_high,
            "hiphop_only_auc": hip_auc,
            "hiphop_auc_cluster_bootstrap95_low": hip_low,
            "hiphop_auc_cluster_bootstrap95_high": hip_high,
            "n_hiphop_clean": n_hip_covers,
            "n_hiphop_positive": n_hip_pos,
            "n_hiphop_clean_only": n_hip_clean_only,
            "bootstrap_repetitions": args.bootstrap_repetitions,
        })

        # Genre-specific score/threshold diagnostics; only hip-hop has positives.
        genres = sorted({r["genre"] for r in rows})
        for genre in genres:
            gr = [r for r in rows if r["genre"] == genre]
            gy = np.asarray([r["y_true"] for r in gr], dtype=int)
            gs = np.asarray([r["y_score"] for r in gr], dtype=float)
            gp = np.asarray([r["y_pred"] for r in gr], dtype=int)
            gtn, gfp, gfn, gtp = confusion_matrix(gy, gp, labels=[0, 1]).ravel()
            genre_auc = float(roc_auc_score(gy, gs)) if len(set(gy)) == 2 else ""
            genre_rows.append({
                "test_encoder": encoder,
                "model": model,
                "genre": genre,
                "n_recordings": len({r["recording"] for r in gr}),
                "n_clean": int((gy == 0).sum()),
                "n_positive": int((gy == 1).sum()),
                "auc": genre_auc,
                "mean_clean_score": float(np.mean(gs[gy == 0])) if np.any(gy == 0) else "",
                "mean_positive_score": float(np.mean(gs[gy == 1])) if np.any(gy == 1) else "",
                "fpr_at_0_5": gfp / (gfp + gtn) if (gfp + gtn) else "",
                "tpr_at_0_5": gtp / (gtp + gfn) if (gtp + gfn) else "",
            })

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = B17 / "results" / "b17_supplementary_audit" / f"run_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)

    write_csv(out_dir / "b17_paired_score_audit.csv", pair_rows)
    write_csv(out_dir / "b17_genre_stratified_metrics.csv", genre_rows)
    write_csv(out_dir / "b17_supplementary_summary.csv", summary_rows)
    write_csv(out_dir / "b17_checksum_audit.csv", checksum_rows)

    report = [
        "========== B17 SUPPLEMENTARY AUDIT ==========",
        f"Frozen input run: {run_dir}",
        f"Supplementary output: {out_dir}",
        "Original B17 outputs modified: NO",
        f"Prediction rows: {len(predictions)}",
        f"Metric rows: {len(metrics)}",
        f"Primary conditions audited: {len(primary_conditions)}",
        f"Positive music recordings: {len(positive_recordings)}",
        f"Positive-control genres: {', '.join(positive_genres)}",
        "Positive controls are all hip-hop recordings.",
        "",
        "========== PRIMARY CONDITION DIAGNOSTICS ==========",
    ]
    for r in summary_rows:
        report.append(
            f"{r['test_encoder']} | {r['model']} | "
            f"pooled AUC={r['pooled_auc_recomputed']:.4f} | "
            f"hip-hop-only AUC={r['hiphop_only_auc']:.4f} "
            f"[{r['hiphop_auc_cluster_bootstrap95_low']:.4f}, "
            f"{r['hiphop_auc_cluster_bootstrap95_high']:.4f}] | "
            f"matched pairs={r['matched_positive_higher']}/{r['n_matched_pairs']} | "
            f"matched-only AUC={r['matched_only_auc']:.4f} | "
            f"mean paired delta={r['mean_paired_score_delta']:.4f} "
            f"[{r['mean_paired_score_delta_bootstrap95_low']:.4f}, "
            f"{r['mean_paired_score_delta_bootstrap95_high']:.4f}] | "
            f"FPR={r['pooled_fpr_at_0_5']:.4f}"
        )
    report += [
        "",
        "========== INTERPRETATION LIMITS ==========",
        "- The positive set contains only 10 unique music recordings.",
        "- All 10 positive recordings are from the hip-hop genre.",
        "- Each positive has a matched clean version in the prediction set.",
        "- Matched-pair score direction is not the same as cross-recording generalization.",
        "- Hip-hop-only AUC includes 100 clean hip-hop and 10 positive hip-hop recordings.",
        "- Hip-hop bootstrap resamples recording identities and preserves the 10 matched pairs.",
        "- Threshold remains the original fixed 0.5; no tuning or score inversion was performed.",
        "- These supplementary analyses do not increase the number of independent positive recordings.",
        "- The results do not establish universal music-domain detectability.",
    ]
    if checksum_warnings:
        report += ["", "========== NON-CORE CHECKSUM WARNINGS =========="] + checksum_warnings
    (out_dir / "b17_supplementary_report.txt").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    config_out = {
        "experiment": "B17 supplementary audit",
        "input_run": str(run_dir),
        "primary_training_payload_size_bytes": PRIMARY_SIZE,
        "primary_feature_group": PRIMARY_GROUP,
        "bootstrap_repetitions": args.bootstrap_repetitions,
        "bootstrap_seed": SEED,
        "positive_controls": len(positive_recordings),
        "positive_genres": positive_genres,
        "threshold": 0.5,
        "models_retrained": False,
        "threshold_retuned": False,
        "source_data_modified": False,
    }
    (out_dir / "b17_supplementary_config.json").write_text(
        json.dumps(config_out, indent=2) + "\n", encoding="utf-8"
    )
    write_checksums(out_dir)

    print("\n========== B17 SUPPLEMENTARY RESULTS ==========")
    for r in summary_rows:
        print(
            f"{r['test_encoder']} | {r['model']} | "
            f"pooled AUC={r['pooled_auc_recomputed']:.4f} | "
            f"hip-hop AUC={r['hiphop_only_auc']:.4f} "
            f"[{r['hiphop_auc_cluster_bootstrap95_low']:.4f}, "
            f"{r['hiphop_auc_cluster_bootstrap95_high']:.4f}] | "
            f"matched={r['matched_positive_higher']}/10"
        )
    print("\nB17 SUPPLEMENTARY AUDIT: COMPLETE")
    print("Output:", out_dir)
    print("Report:", out_dir / "b17_supplementary_report.txt")
    print("Checksums:", out_dir / "b17_supplementary_checksums.sha256")


if __name__ == "__main__":
    main()
