#!/usr/bin/env python3
"""B16: independent cross-version transfer evaluation for Opus redundancy steganalysis.

READ-ONLY:
- Reads B9 cover bitstreams and the validated B12 manifest/modified bitstreams.
- Reuses B14's exact packet parser, feature extraction, feature groups and models.
- Uses repetition 1 only, matching B14's primary ML analysis.
- Excludes any speaker OR recording ID appearing in both encoder versions.
- Trains on one encoder version and evaluates on the other, in both directions.
- Uses a fixed 0.5 decision threshold; no tuning on the test version.
- Bootstraps test metrics by speaker cluster, preserving cover/stego pairs.
"""

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import run_b14_feature_attribution as b14


ROOT = Path.home() / "research/redundant_celt_frame_steganography"
B9 = ROOT / "experiments/B9_common_voice"
DEFAULT_B12 = (
    ROOT / "experiments/B9_common_voice/results/"
    "b12_payload_reliability/run_20261104_020705"
)
DEFAULT_OUT = (
    ROOT / "experiments/B9_common_voice/results/"
    "b16_cross_version_transfer"
)

VERSIONS = ("1.5.2", "1.6.1")
SIZES = (4, 8, 16, 24, 32, 36)
MODELS = ("logistic_regression", "random_forest")
PRIMARY_REPETITION = 1
THRESHOLD = 0.5
NEGATIVE_CONTROL_GROUPS = ("packet_geometry", "target_prefix_control")


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    if fieldnames is None:
        if not rows:
            raise ValueError(f"Cannot infer CSV columns for empty output: {path}")
        fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def unique_event_inventory(manifest):
    """Return event metadata and cross-version speaker/recording overlap."""
    event_speaker = {}
    speakers = defaultdict(set)
    recordings = defaultdict(set)

    for row in manifest:
        enc = row["encoder"].strip()
        rec = row["recording"].strip()
        speaker = row["speaker_sha256"].strip()
        frame = int(row["frame"])
        event = (enc, rec, frame)

        if enc not in VERSIONS:
            raise ValueError(f"Unexpected encoder in manifest: {enc}")

        old = event_speaker.get(event)
        if old is not None and old != speaker:
            raise ValueError(f"Conflicting speaker identity for event {event}")

        event_speaker[event] = speaker
        speakers[enc].add(speaker)
        recordings[enc].add(rec)

    shared_speakers = speakers[VERSIONS[0]] & speakers[VERSIONS[1]]
    shared_recordings = recordings[VERSIONS[0]] & recordings[VERSIONS[1]]

    return event_speaker, speakers, recordings, shared_speakers, shared_recordings


def make_transfer_dataset(records, size, version, columns,
                          excluded_speakers, excluded_recordings):
    selected = [
        r for r in records
        if r["encoder"] == version
        and r["size"] == size
        and r["rep"] == PRIMARY_REPETITION
        and r["speaker"] not in excluded_speakers
        and r["recording"] not in excluded_recordings
    ]

    X, y, groups, meta = [], [], [], []

    seen_events = set()
    for r in selected:
        event_id = (r["encoder"], r["recording"], r["frame"])
        if event_id in seen_events:
            raise ValueError(f"Duplicate primary-repetition event: {event_id}")
        seen_events.add(event_id)

        for label, feature_key in (
            (0, "cover_features"),
            (1, "stego_features"),
        ):
            X.append([r[feature_key][col] for col in columns])
            y.append(label)
            groups.append(r["speaker"])
            meta.append({
                "encoder": r["encoder"],
                "recording": r["recording"],
                "frame": r["frame"],
                "speaker_sha256": r["speaker"],
                "class": "stego" if label else "cover",
                "event_id": "|".join(map(str, event_id)),
            })

    if not selected:
        raise ValueError(f"No eligible events for {version}, {size} bytes")

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)

    if X.ndim != 2 or X.shape[1] != len(columns):
        raise RuntimeError("Unexpected feature matrix dimensions")
    if set(np.unique(y)) != {0, 1}:
        raise RuntimeError("Dataset does not contain both classes")
    if len(X) != 2 * len(selected):
        raise RuntimeError("Cover/stego pairing count is incorrect")

    return X, y, groups, meta, len(selected)


def cluster_bootstrap_ci(y, pred, score, groups, repetitions, seed):
    """Percentile CIs from speaker-cluster resampling of paired cover/stego rows."""
    metric_names = (
        "accuracy", "balanced_accuracy", "tpr", "fpr", "f1", "roc_auc"
    )
    if repetitions <= 0:
        return {}

    unique_groups = np.unique(groups)
    indices_by_group = {
        group: np.flatnonzero(groups == group)
        for group in unique_groups
    }
    rng = np.random.default_rng(seed)
    values = {name: [] for name in metric_names}

    for _ in range(repetitions):
        sampled_groups = rng.choice(
            unique_groups, size=len(unique_groups), replace=True
        )
        idx = np.concatenate([
            indices_by_group[group] for group in sampled_groups
        ])
        metrics = b14.calculate_metrics(y[idx], pred[idx], score[idx])
        for name in metric_names:
            values[name].append(metrics[name])

    result = {}
    for name, samples in values.items():
        low, high = np.percentile(samples, [2.5, 97.5])
        result[f"{name}_ci95_low"] = float(low)
        result[f"{name}_ci95_high"] = float(high)
    return result


def audit_negative_controls(records, excluded_speakers, excluded_recordings,
                            feature_groups):
    rows = []
    for version in VERSIONS:
        for size in SIZES:
            selected = [
                r for r in records
                if r["encoder"] == version
                and r["size"] == size
                and r["rep"] == PRIMARY_REPETITION
                and r["speaker"] not in excluded_speakers
                and r["recording"] not in excluded_recordings
            ]
            for group_name in NEGATIVE_CONTROL_GROUPS:
                cols = feature_groups[group_name]
                identical = 0
                for r in selected:
                    cover = [r["cover_features"][c] for c in cols]
                    stego = [r["stego_features"][c] for c in cols]
                    if cover == stego:
                        identical += 1
                rows.append({
                    "encoder": version,
                    "payload_size_bytes": size,
                    "feature_group": group_name,
                    "n_events": len(selected),
                    "identical_cover_stego_feature_pairs": identical,
                    "changed_pairs": len(selected) - identical,
                    "all_pairs_identical": identical == len(selected),
                })
    return rows


def make_heatmap(metrics_rows, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    feature_order = list(b14.ALL_GROUPS)
    fig, axes = plt.subplots(2, 2, figsize=(18, 12), constrained_layout=True)

    panels = [
        ("logistic_regression", "1.5.2", "1.6.1"),
        ("logistic_regression", "1.6.1", "1.5.2"),
        ("random_forest", "1.5.2", "1.6.1"),
        ("random_forest", "1.6.1", "1.5.2"),
    ]

    for ax, (model, train_version, test_version) in zip(axes.flat, panels):
        matrix = np.full((len(feature_order), len(SIZES)), np.nan)
        for row in metrics_rows:
            if (
                row["model"] == model
                and row["train_encoder"] == train_version
                and row["test_encoder"] == test_version
            ):
                i = feature_order.index(row["feature_group"])
                j = SIZES.index(int(row["payload_size_bytes"]))
                matrix[i, j] = float(row["roc_auc"])

        image = ax.imshow(matrix, vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(SIZES)), [str(x) for x in SIZES])
        ax.set_yticks(range(len(feature_order)), feature_order)
        ax.set_xlabel("Payload size (bytes)")
        ax.set_title(f"{model}: train {train_version} → test {test_version}")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                if np.isfinite(matrix[i, j]):
                    ax.text(j, i, f"{matrix[i, j]:.2f}",
                            ha="center", va="center", fontsize=7)

    fig.colorbar(image, ax=axes.ravel().tolist(), label="ROC-AUC")
    fig.suptitle("B16 Cross-version transfer ROC-AUC", fontsize=14)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="B16 independent cross-version transfer experiment"
    )
    parser.add_argument("--b12-run", type=Path, default=DEFAULT_B12)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.bootstrap_repetitions < 0:
        raise ValueError("Bootstrap repetitions cannot be negative")

    b12_run = args.b12_run.expanduser().resolve()
    out_root = args.out_root.expanduser().resolve()
    manifest_path = b12_run / "b12_payload_manifest.csv"
    b14_config_path = (
        B9 / "results/b14_feature_attribution/"
        "run_20261104_110548/b14_run_config.json"
    )
    b14_script_path = B9 / "run_b14_feature_attribution.py"

    for required in (manifest_path, b14_config_path, b14_script_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    b14_config = json.loads(b14_config_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(manifest_path)
    expected_manifest_hash = b14_config.get("manifest_sha256")
    if manifest_hash != expected_manifest_hash:
        raise RuntimeError(
            "B12 manifest SHA256 differs from the manifest used by B14"
        )

    print("========== B16 INPUT VALIDATION ==========")
    print("Project:", ROOT)
    print("B12 run:", b12_run)
    print("B12 manifest SHA256:", manifest_hash)
    print("B14 script SHA256:", sha256_file(b14_script_path))
    print("B14 config SHA256:", sha256_file(b14_config_path))

    manifest = b14.read_manifest(manifest_path)
    event_speaker, speakers, recordings, shared_speakers, shared_recordings = (
        unique_event_inventory(manifest)
    )

    for version in VERSIONS:
        event_count = sum(1 for e in event_speaker if e[0] == version)
        print(
            f"{version}: events={event_count}; "
            f"speakers={len(speakers[version])}; "
            f"recordings={len(recordings[version])}"
        )

    print("Shared speakers:", len(shared_speakers))
    print("Shared recording IDs:", len(shared_recordings))

    # Exclude the union to guarantee neither speaker nor recording leakage.
    excluded_speakers = set(shared_speakers)
    excluded_recordings = set(shared_recordings)

    retained_speakers = {}
    retained_recordings = {}
    retained_events = {}

    exclusion_rows = []
    for (version, recording, frame), speaker in sorted(event_speaker.items()):
        reasons = []
        if speaker in excluded_speakers:
            reasons.append("shared_speaker")
        if recording in excluded_recordings:
            reasons.append("shared_recording")
        excluded = bool(reasons)

        exclusion_rows.append({
            "encoder": version,
            "recording": recording,
            "frame": frame,
            "speaker_sha256": speaker,
            "excluded": excluded,
            "exclusion_reason": ";".join(reasons),
        })

        if not excluded:
            retained_events.setdefault(version, []).append(
                (recording, frame, speaker)
            )

    for version in VERSIONS:
        retained_speakers[version] = {
            speaker for _, _, speaker in retained_events.get(version, [])
        }
        retained_recordings[version] = {
            recording for recording, _, _ in retained_events.get(version, [])
        }
        print(
            f"{version}: retained_events={len(retained_events.get(version, []))}; "
            f"retained_speakers={len(retained_speakers[version])}; "
            f"retained_recordings={len(retained_recordings[version])}"
        )

    if retained_speakers[VERSIONS[0]] & retained_speakers[VERSIONS[1]]:
        raise RuntimeError("Speaker leakage remains after exclusions")
    if retained_recordings[VERSIONS[0]] & retained_recordings[VERSIONS[1]]:
        raise RuntimeError("Recording leakage remains after exclusions")

    if not all(retained_events.get(v) for v in VERSIONS):
        raise RuntimeError("No eligible independent events remain")

    print("\n========== BUILDING VALIDATED FEATURE RECORDS ==========")
    records = b14.build_records(ROOT, B9, b12_run, manifest)
    print("Validated B12 manifest records:", len(records))

    feature_keys = sorted(records[0]["cover_features"].keys())
    feature_groups = b14.define_feature_groups(feature_keys)

    expected_sizes = b14_config.get("feature_group_sizes", {})
    for name, cols in feature_groups.items():
        if name in expected_sizes and len(cols) != expected_sizes[name]:
            raise RuntimeError(
                f"Feature group size mismatch for {name}: "
                f"{len(cols)} != {expected_sizes[name]}"
            )

    print("Feature groups:", {
        name: len(cols) for name, cols in feature_groups.items()
    })

    # Audit the two negative controls before fitting any models.
    negative_rows = audit_negative_controls(
        records, excluded_speakers, excluded_recordings, feature_groups
    )
    failed_controls = [
        r for r in negative_rows if not r["all_pairs_identical"]
    ]
    if failed_controls:
        raise RuntimeError(
            "Negative-control features changed between cover/stego pairs: "
            + repr(failed_controls[:3])
        )

    out_root.mkdir(parents=True, exist_ok=True)
    run_dir = out_root / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=False)

    write_csv(run_dir / "b16_event_exclusion_audit.csv", exclusion_rows)
    write_csv(run_dir / "b16_negative_control_audit.csv", negative_rows)

    config = {
        "stage": "B16",
        "b16_script_sha256": sha256_file(Path(__file__).resolve()),
        "b12_run": str(b12_run),
        "b12_manifest_sha256": manifest_hash,
        "b14_config": str(b14_config_path),
        "b14_config_sha256": sha256_file(b14_config_path),
        "b14_script": str(b14_script_path),
        "b14_script_sha256": sha256_file(b14_script_path),
        "encoders": list(VERSIONS),
        "payload_sizes_bytes": list(SIZES),
        "primary_repetition": PRIMARY_REPETITION,
        "models": list(MODELS),
        "feature_groups": {k: len(v) for k, v in feature_groups.items()},
        "shared_speakers_excluded": len(shared_speakers),
        "shared_recordings_excluded": len(shared_recordings),
        "exclusion_policy": "exclude union of shared speaker IDs and recording IDs",
        "retained_events": {
            v: len(retained_events.get(v, [])) for v in VERSIONS
        },
        "decision_threshold": THRESHOLD,
        "bootstrap_repetitions": args.bootstrap_repetitions,
        "bootstrap_unit": "speaker_sha256",
        "seed": args.seed,
        "training_testing": "train on one encoder; test on the other; both directions",
        "read_only": True,
    }
    (run_dir / "b16_run_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    metric_rows = []
    prediction_rows = []
    combination = 0
    total_combinations = len(SIZES) * len(feature_groups) * len(MODELS) * 2

    print("\n========== B16 CROSS-VERSION MODEL EVALUATION ==========")
    for size in SIZES:
        for feature_name, columns in feature_groups.items():
            for model_name in MODELS:
                for train_version, test_version in (
                    (VERSIONS[0], VERSIONS[1]),
                    (VERSIONS[1], VERSIONS[0]),
                ):
                    combination += 1

                    X_train, y_train, g_train, _, n_train_events = (
                        make_transfer_dataset(
                            records, size, train_version, columns,
                            excluded_speakers, excluded_recordings
                        )
                    )
                    X_test, y_test, g_test, meta_test, n_test_events = (
                        make_transfer_dataset(
                            records, size, test_version, columns,
                            excluded_speakers, excluded_recordings
                        )
                    )

                    if set(np.unique(y_train)) != {0, 1}:
                        raise RuntimeError("Training set missing a class")
                    if set(np.unique(y_test)) != {0, 1}:
                        raise RuntimeError("Test set missing a class")
                    if set(g_train) & set(g_test):
                        raise RuntimeError("Cross-version speaker leakage")

                    model = b14.make_model(model_name, args.seed)
                    model.fit(X_train, y_train)

                    scores = model.predict_proba(X_test)[:, 1]
                    predictions = (scores >= THRESHOLD).astype(int)
                    metrics = b14.calculate_metrics(
                        y_test, predictions, scores
                    )

                    ci = cluster_bootstrap_ci(
                        y_test, predictions, scores, g_test,
                        args.bootstrap_repetitions,
                        args.seed + combination,
                    )

                    metric_row = {
                        **metrics,
                        **ci,
                        "train_encoder": train_version,
                        "test_encoder": test_version,
                        "direction": f"{train_version}_to_{test_version}",
                        "payload_size_bytes": size,
                        "repetition": PRIMARY_REPETITION,
                        "feature_group": feature_name,
                        "model": model_name,
                        "n_features": len(columns),
                        "n_train_events": n_train_events,
                        "n_test_events": n_test_events,
                        "n_train_samples": len(y_train),
                        "n_test_samples": len(y_test),
                        "n_train_speakers": len(np.unique(g_train)),
                        "n_test_speakers": len(np.unique(g_test)),
                        "split_unit": "independent_encoder_holdout; speaker/recording-disjoint",
                        "decision_threshold": THRESHOLD,
                        "bootstrap_repetitions": args.bootstrap_repetitions,
                    }
                    metric_rows.append(metric_row)

                    for i, meta in enumerate(meta_test):
                        prediction_rows.append({
                            "train_encoder": train_version,
                            "test_encoder": test_version,
                            "direction": f"{train_version}_to_{test_version}",
                            "payload_size_bytes": size,
                            "repetition": PRIMARY_REPETITION,
                            "feature_group": feature_name,
                            "model": model_name,
                            **meta,
                            "y_true": int(y_test[i]),
                            "y_score": float(scores[i]),
                            "y_pred": int(predictions[i]),
                            "decision_threshold": THRESHOLD,
                        })

                    print(
                        f"[{combination}/{total_combinations}] "
                        f"{size}B | {feature_name} | {model_name} | "
                        f"{train_version}->{test_version} | "
                        f"AUC={metrics['roc_auc']:.4f} | "
                        f"BA={metrics['balanced_accuracy']:.4f}"
                    )

    metrics_path = run_dir / "b16_transfer_metrics.csv"
    predictions_path = run_dir / "b16_transfer_predictions.csv"
    write_csv(metrics_path, metric_rows)
    write_csv(predictions_path, prediction_rows)

    make_heatmap(
        metric_rows, run_dir / "b16_transfer_auc_heatmap.png"
    )

    report_lines = [
        "========== B16 CROSS-VERSION TRANSFER REPORT ==========",
        f"Run: {run_dir}",
        f"B12 manifest SHA256: {manifest_hash}",
        f"B14 source SHA256: {sha256_file(b14_script_path)}",
        "",
        "DESIGN",
        "- Train on one encoder version and test on the other.",
        "- Both transfer directions are evaluated.",
        "- Primary repetition only; no repeated-payload pseudoreplication.",
        "- Shared speaker IDs and shared recording IDs are excluded from both sides.",
        "- Threshold fixed at 0.5; no test-set threshold tuning.",
        "- Confidence intervals use speaker-cluster bootstrap of paired cover/stego rows.",
        "",
        "SAMPLE COUNTS",
    ]

    for version in VERSIONS:
        report_lines.append(
            f"{version}: original_events="
            f"{sum(1 for e in event_speaker if e[0] == version)}; "
            f"retained_events={len(retained_events.get(version, []))}; "
            f"retained_speakers={len(retained_speakers[version])}; "
            f"retained_recordings={len(retained_recordings[version])}"
        )

    report_lines.extend([
        f"Shared speakers excluded: {len(shared_speakers)}",
        f"Shared recording IDs excluded: {len(shared_recordings)}",
        "",
        "NEGATIVE CONTROLS",
    ])
    for row in negative_rows:
        report_lines.append(
            f"{row['encoder']} | {row['payload_size_bytes']}B | "
            f"{row['feature_group']}: "
            f"{row['identical_cover_stego_feature_pairs']}/"
            f"{row['n_events']} identical pairs"
        )

    report_lines.extend([
        "",
        "RESULTS OVERVIEW",
        f"Metric rows: {len(metric_rows)}",
        f"Prediction rows: {len(prediction_rows)}",
        "",
        "Top ROC-AUC rows (descriptive; not a post-hoc selection rule):",
    ])

    for row in sorted(
        metric_rows, key=lambda x: x["roc_auc"], reverse=True
    )[:15]:
        report_lines.append(
            f"{row['direction']} | {row['payload_size_bytes']}B | "
            f"{row['feature_group']} | {row['model']} | "
            f"AUC={row['roc_auc']:.4f} "
            f"[{row.get('roc_auc_ci95_low', float('nan')):.4f}, "
            f"{row.get('roc_auc_ci95_high', float('nan')):.4f}] | "
            f"BA={row['balanced_accuracy']:.4f}"
        )

    report_lines.extend([
        "",
        "INTERPRETATION LIMITS",
        "- Cross-version transfer is evaluated only for these two encoder versions.",
        "- Target-packet and target-tail feature groups assume the modified frame is known.",
        "- Global stream features summarize the complete serialized bitstream; they are not a blind arbitrary-location detector.",
        "- Negative-control feature groups should remain identical within each cover/stego pair.",
        "- Findings do not establish detectability of arbitrary steganographic methods.",
        "- Source bitstreams and B12 inputs were read-only.",
        "",
        "B16 STATUS: COMPLETE",
    ])

    report_path = run_dir / "b16_report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    # Preserve the exact executed script with the run.
    shutil.copy2(Path(__file__).resolve(), run_dir / "b16_run.py")

    checksum_path = run_dir / "b16_checksums.sha256"
    checksum_lines = []
    for path in sorted(run_dir.iterdir()):
        if path.is_file() and path.name != checksum_path.name:
            checksum_lines.append(
                f"{sha256_file(path)}  {path.name}"
            )
    checksum_path.write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )

    print("\n========== B16 FINAL SUMMARY ==========")
    print("Run directory:", run_dir)
    print("Metric rows:", len(metric_rows))
    print("Prediction rows:", len(prediction_rows))
    print("Negative-control audit rows:", len(negative_rows))
    print("Source data modified: NO")
    print("B16 CROSS-VERSION TRANSFER: COMPLETE")
    print("\n========== CHECKSUM VERIFICATION ==========")
    for line in checksum_lines:
        expected, name = line.split("  ", 1)
        actual = sha256_file(run_dir / name)
        print(f"{name}: {'OK' if actual == expected else 'FAIL'}")
        if actual != expected:
            raise RuntimeError(f"Checksum verification failed: {name}")


if __name__ == "__main__":
    main()
