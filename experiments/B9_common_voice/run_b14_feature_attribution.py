#!/usr/bin/env python3
"""B14: Feature attribution and ablation for Opus redundancy steganalysis.

READ-ONLY:
- Does not modify B9 source bitstreams.
- Does not modify B12 modified bitstreams.
- Uses B12 repetition 1 for primary ML.
- Uses speaker-grouped cross-validation.
- Separates global, histogram, structural and target-aware features.
"""

import argparse
import csv
import hashlib
import json
import struct

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


VERSIONS = ("1.5.2", "1.6.1")
SIZES = (4, 8, 16, 24, 32, 36)

CAPACITY = 36
PRIMARY_REPETITION = 1

ALL_GROUPS = (
    "global_all",
    "stream_scalar",
    "stream_histogram",
    "packet_geometry",
    "global_without_histogram",
    "global_without_stream_scalars",
    "global_without_packet_geometry",
    "target_packet",
    "target_tail36",
    "target_prefix_control",
    "global_plus_tail36",
)

# Encoder-specific evaluation is restricted to these key groups.
ENCODER_GROUPS = (
    "global_all",
    "stream_scalar",
    "stream_histogram",
    "global_without_histogram",
    "target_prefix_control",
)

FOCUS_FEATURES = (
    "g_stream_entropy",
    "g_stream_zero_fraction",
    "g_stream_nonzero_count",
    "g_stream_unique_count",
    "g_stream_mean",
    "g_stream_std",
    "g_stream_transition_rate",
    "g_stream_longest_zero_run",
    "g_stream_trailing_zero_bytes",
    "g_packet_count",
    "g_packet_length_mean",
    "g_packet_length_std",
    "g_packet_length_min",
    "g_packet_length_max",
    "t_packet_entropy",
    "t_packet_zero_fraction",
    "t_tail36_entropy",
    "t_tail36_zero_fraction",
    "t_tail36_nonzero_count",
    "t_tail36_trailing_zero_bytes",
    "t_prefix36_entropy",
    "t_prefix36_zero_fraction",
    "t_prefix36_nonzero_count",
)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_packets(raw, label):
    packets = []
    offset = 0

    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError(f"{label}: incomplete packet header")

        n = struct.unpack_from("<I", raw, offset)[0]
        offset += 4

        if n <= 0 or offset + n > len(raw):
            raise ValueError(f"{label}: invalid packet length {n}")

        packets.append(raw[offset:offset+n])
        offset += n

    if not packets:
        raise ValueError(f"{label}: no packets")

    return packets


def add_region_features(out, prefix, raw):
    a = np.frombuffer(raw, dtype=np.uint8)

    if not a.size:
        raise ValueError(f"Empty feature region: {prefix}")

    counts = np.bincount(a, minlength=256).astype(float)
    hist = counts / a.size

    z = (a == 0)
    p = hist[hist > 0]

    longest = 0
    run = 0

    for value in z:
        run = run + 1 if value else 0
        longest = max(longest, run)

    trailing = 0
    for value in z[::-1]:
        if not value:
            break
        trailing += 1

    out[f"{prefix}_nbytes"] = float(a.size)
    out[f"{prefix}_zero_fraction"] = float(np.mean(z))
    out[f"{prefix}_nonzero_count"] = float(np.count_nonzero(a))
    out[f"{prefix}_unique_count"] = float(np.unique(a).size)
    out[f"{prefix}_mean"] = float(np.mean(a))
    out[f"{prefix}_std"] = float(np.std(a))

    out[f"{prefix}_entropy"] = float(
        -(p * np.log2(p)).sum()
    )

    out[f"{prefix}_transition_rate"] = (
        float(np.mean(a[1:] != a[:-1]))
        if a.size > 1 else 0.0
    )

    out[f"{prefix}_longest_zero_run"] = float(longest)
    out[f"{prefix}_trailing_zero_bytes"] = float(trailing)

    for i, value in enumerate(hist):
        out[f"{prefix}_hist_{i:03d}"] = float(value)


def extract_features(raw, packets, frame):
    if frame < 0 or frame >= len(packets):
        raise ValueError("Target frame outside packet count")

    target = packets[frame]

    if len(target) <= CAPACITY:
        raise ValueError("Target packet has no nonempty prefix")

    out = {}

    # Entire serialized stream, including packet-length headers.
    add_region_features(out, "g_stream", raw)

    # Complete target packet.
    add_region_features(out, "t_packet", target)

    # Candidate embedding region.
    add_region_features(out, "t_tail36", target[-CAPACITY:])

    # Negative control: unchanged bytes preceding the tail.
    add_region_features(out, "t_prefix36", target[:-CAPACITY])

    lengths = np.asarray(
        [len(p) for p in packets], dtype=float
    )

    out["g_packet_count"] = float(len(packets))
    out["g_packet_length_mean"] = float(np.mean(lengths))
    out["g_packet_length_std"] = float(np.std(lengths))
    out["g_packet_length_min"] = float(np.min(lengths))
    out["g_packet_length_max"] = float(np.max(lengths))

    return out


def read_manifest(path):
    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError("Empty B12 manifest")

    required = {
        "encoder",
        "recording",
        "speaker_sha256",
        "frame",
        "payload_size_bytes",
        "repetition",
        "payload_hex",
        "payload_sha256",
        "source_bitstream_sha256",
        "modified_bitstream_sha256",
        "modified_bitstream",
    }

    missing = required - set(rows[0])

    if missing:
        raise ValueError(
            "Missing manifest columns: " +
            ", ".join(sorted(missing))
        )

    return rows


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")

    with path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


def build_records(root, b9, b12_run, manifest):
    source_cache = {}
    records = []
    seen = set()

    for i, row in enumerate(manifest, 1):

        enc = row["encoder"].strip()
        rec = row["recording"].strip()
        speaker = row["speaker_sha256"].strip()

        frame = int(row["frame"])
        size = int(row["payload_size_bytes"])
        rep = int(row["repetition"])

        if enc not in VERSIONS:
            raise ValueError(f"Unknown encoder: {enc}")

        if size not in SIZES or rep not in (1, 2, 3):
            raise ValueError("Unexpected size or repetition")

        event = (enc, rec, frame)
        identity = event + (size, rep)

        if identity in seen:
            raise ValueError(f"Duplicate event row: {identity}")

        seen.add(identity)

        source_path = (
            b9 / "results" / "b9_full_encoding" /
            enc / "bitstreams" / f"{rec}.bin"
        )

        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        if event not in source_cache:

            cover_raw = source_path.read_bytes()

            if sha_bytes(cover_raw) != row[
                "source_bitstream_sha256"
            ]:
                raise ValueError(
                    f"Cover SHA256 mismatch: {source_path}"
                )

            cover_packets = read_packets(
                cover_raw, str(source_path)
            )

            if frame >= len(cover_packets):
                raise ValueError("Cover target frame missing")

            cover_target = cover_packets[frame]

            if cover_target[-CAPACITY:] != bytes(CAPACITY):
                raise ValueError(
                    f"Cover tail is not 36 zero bytes: {rec}"
                )

            source_cache[event] = {
                "packets": cover_packets,
                "features": extract_features(
                    cover_raw, cover_packets, frame
                ),
                "packet_lengths": [
                    len(p) for p in cover_packets
                ],
                "speaker": speaker,
            }

        cover = source_cache[event]

        if cover["speaker"] != speaker:
            raise ValueError("Speaker identity mismatch")

        rel = Path(row["modified_bitstream"])
        stego_path = (b12_run / rel).resolve()

        if not stego_path.is_relative_to(b12_run.resolve()):
            raise ValueError("Modified path escapes B12 directory")

        if not stego_path.is_file():
            raise FileNotFoundError(stego_path)

        stego_raw = stego_path.read_bytes()

        if sha_bytes(stego_raw) != row[
            "modified_bitstream_sha256"
        ]:
            raise ValueError(
                f"Stego SHA256 mismatch: {stego_path}"
            )

        stego_packets = read_packets(
            stego_raw, str(stego_path)
        )

        if len(stego_packets) != len(cover["packets"]):
            raise ValueError("Packet count changed")

        if [len(p) for p in stego_packets] != cover[
            "packet_lengths"
        ]:
            raise ValueError("Packet lengths changed")

        payload = bytes.fromhex(row["payload_hex"])

        if len(payload) != size:
            raise ValueError("Payload length mismatch")

        if sha_bytes(payload) != row["payload_sha256"]:
            raise ValueError("Payload SHA256 mismatch")

        expected_tail = bytes(CAPACITY-size) + payload

        if stego_packets[frame][-CAPACITY:] != expected_tail:
            raise ValueError("Stego tail does not match payload")

        if (
            stego_packets[frame][:-CAPACITY]
            != cover["packets"][frame][:-CAPACITY]
        ):
            raise ValueError("Target prefix was modified")

        records.append({
            "encoder": enc,
            "recording": rec,
            "speaker": speaker,
            "frame": frame,
            "size": size,
            "rep": rep,
            "cover_features": cover["features"],
            "stego_features": extract_features(
                stego_raw, stego_packets, frame
            ),
        })

        if i % 300 == 0:
            print(f"Validated {i}/{len(manifest)} rows")

    if len(records) != 3600:
        raise ValueError(
            f"Expected 3600 records, got {len(records)}"
        )

    events = {
        (r["encoder"], r["recording"], r["frame"])
        for r in records
    }

    speakers = {
        r["speaker"] for r in records
    }

    if len(events) != 200:
        raise ValueError("Expected 200 unique events")

    if len(speakers) != 196:
        raise ValueError(
            f"Expected 196 speaker groups, found {len(speakers)}"
        )

    for size in SIZES:
        for rep in (1, 2, 3):
            subset = [
                r for r in records
                if r["size"] == size and r["rep"] == rep
            ]
            if len(subset) != 200:
                raise ValueError(
                    f"Invalid count for {size}B rep{rep}"
                )

    return records


def define_feature_groups(keys):

    stream_scalar = [
        k for k in keys
        if k.startswith("g_stream_")
        and "_hist_" not in k
    ]

    stream_histogram = [
        k for k in keys
        if k.startswith("g_stream_hist_")
    ]

    packet_geometry = [
        k for k in keys
        if k.startswith("g_packet_")
    ]

    global_all = [
        k for k in keys if k.startswith("g_")
    ]

    target_packet = [
        k for k in keys if k.startswith("t_packet_")
    ]

    target_tail = [
        k for k in keys if k.startswith("t_tail36_")
    ]

    target_prefix = [
        k for k in keys if k.startswith("t_prefix36_")
    ]

    groups = {
        "global_all": global_all,
        "stream_scalar": stream_scalar,
        "stream_histogram": stream_histogram,
        "packet_geometry": packet_geometry,

        "global_without_histogram":
            stream_scalar + packet_geometry,

        "global_without_stream_scalars":
            stream_histogram + packet_geometry,

        "global_without_packet_geometry":
            stream_scalar + stream_histogram,

        "target_packet": target_packet,
        "target_tail36": target_tail,
        "target_prefix_control": target_prefix,

        "global_plus_tail36":
            global_all + target_tail,
    }

    for name, cols in groups.items():
        if not cols:
            raise ValueError(f"Empty feature group: {name}")

        if len(cols) != len(set(cols)):
            raise ValueError(f"Duplicate features in {name}")

    return groups


def make_model(name, seed):

    if name == "logistic_regression":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=5000,
                class_weight="balanced",
                solver="liblinear",
                random_state=seed,
            ),
        )

    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=200,
            max_features="sqrt",
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=-1,
        )

    raise ValueError(name)


def make_dataset(records, size, scope, cols):

    selected = [
        r for r in records
        if r["size"] == size
        and r["rep"] == PRIMARY_REPETITION
        and (
            scope == "pooled"
            or r["encoder"] == scope
        )
    ]

    X, y, groups, meta = [], [], [], []

    for r in selected:

        for label, key in (
            (0, "cover_features"),
            (1, "stego_features"),
        ):

            X.append([
                r[key][col] for col in cols
            ])

            y.append(label)
            groups.append(r["speaker"])

            meta.append((
                r["encoder"],
                r["recording"],
                r["speaker"],
                label,
            ))

    return (
        np.asarray(X, dtype=float),
        np.asarray(y, dtype=int),
        np.asarray(groups),
        meta,
        len(selected),
    )


def calculate_metrics(y, pred, score):

    tn, fp, fn, tp = confusion_matrix(
        y, pred, labels=[0, 1]
    ).ravel()

    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(
            balanced_accuracy_score(y, pred)
        ),
        "precision": float(
            precision_score(y, pred, zero_division=0)
        ),
        "tpr": float(
            recall_score(y, pred, zero_division=0)
        ),
        "f1": float(
            f1_score(y, pred, zero_division=0)
        ),
        "roc_auc": float(roc_auc_score(y, score)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "fpr": float(fp/(fp+tn)) if fp+tn else 0.0,
    }


def evaluate_group(
    records, size, scope, group_name, cols,
    model_name, seed, folds
):

    X, y, groups, meta, n_events = make_dataset(
        records, size, scope, cols
    )

    if len(np.unique(groups)) < folds:
        raise ValueError("Insufficient speaker groups")

    cv = StratifiedGroupKFold(
        n_splits=folds,
        shuffle=True,
        random_state=seed,
    )

    scores = np.full(len(y), np.nan)
    preds = np.full(len(y), -1, dtype=int)
    fold_ids = np.full(len(y), -1, dtype=int)

    for fold, (tr, te) in enumerate(
        cv.split(X, y, groups), 1
    ):

        if set(groups[tr]) & set(groups[te]):
            raise RuntimeError("Speaker leakage")

        if len(np.unique(y[tr])) != 2:
            raise RuntimeError("Training fold missing a class")

        if len(np.unique(y[te])) != 2:
            raise RuntimeError("Test fold missing a class")

        model = make_model(model_name, seed)
        model = clone(model)

        model.fit(X[tr], y[tr])

        scores[te] = model.predict_proba(X[te])[:, 1]
        preds[te] = (scores[te] >= 0.5).astype(int)
        fold_ids[te] = fold

    if np.isnan(scores).any() or np.any(preds < 0):
        raise RuntimeError("Missing OOF predictions")

    result = calculate_metrics(y, preds, scores)

    result.update({
        "scope": scope,
        "payload_size_bytes": size,
        "feature_group": group_name,
        "model": model_name,
        "n_features": len(cols),
        "n_samples": len(y),
        "n_events": n_events,
        "n_speaker_groups": len(np.unique(groups)),
        "cv_folds": folds,
        "split_unit": "speaker_sha256",
        "decision_threshold": 0.5,
    })

    pred_rows = []

    for i, (enc, rec, speaker, label) in enumerate(meta):

        pred_rows.append({
            "scope": scope,
            "payload_size_bytes": size,
            "feature_group": group_name,
            "model": model_name,
            "encoder": enc,
            "recording": rec,
            "speaker_sha256": speaker,
            "class": "stego" if label else "cover",
            "y_true": int(y[i]),
            "y_score": float(scores[i]),
            "y_pred": int(preds[i]),
            "fold": int(fold_ids[i]),
        })

    return result, pred_rows


def calculate_feature_effects(records, keys):

    output = []

    for size in SIZES:

        selected = [
            r for r in records
            if r["size"] == size
            and r["rep"] == PRIMARY_REPETITION
        ]

        for key in keys:

            delta = np.asarray([
                r["stego_features"][key]
                - r["cover_features"][key]
                for r in selected
            ], dtype=float)

            family = (
                "stream_histogram"
                if "_hist_" in key and key.startswith("g_stream")
                else key.split("_")[0]
            )

            output.append({
                "payload_size_bytes": size,
                "feature": key,
                "feature_family": family,
                "n_events": len(delta),
                "mean_delta_stego_minus_cover":
                    float(np.mean(delta)),
                "mean_absolute_delta":
                    float(np.mean(np.abs(delta))),
                "median_absolute_delta":
                    float(np.median(np.abs(delta))),
                "std_delta":
                    float(np.std(delta, ddof=1)),
                "n_changed":
                    int(np.count_nonzero(np.abs(delta) > 1e-12)),
                "percent_changed":
                    float(
                        100*np.mean(np.abs(delta) > 1e-12)
                    ),
            })

    return output


def cluster_bootstrap_effects(
    records, seed, repetitions
):

    output = []
    rng = np.random.default_rng(seed)

    for size in SIZES:

        selected = [
            r for r in records
            if r["size"] == size
            and r["rep"] == PRIMARY_REPETITION
        ]

        by_speaker = defaultdict(list)

        for r in selected:
            by_speaker[r["speaker"]].append(r)

        speakers = sorted(by_speaker)

        for feature in FOCUS_FEATURES:

            clusters = {}

            for speaker in speakers:
                clusters[speaker] = np.asarray([
                    r["stego_features"][feature]
                    - r["cover_features"][feature]
                    for r in by_speaker[speaker]
                ], dtype=float)

            all_delta = np.concatenate(
                list(clusters.values())
            )

            observed = float(np.mean(all_delta))

            boot = np.empty(repetitions)

            for b in range(repetitions):

                chosen = rng.choice(
                    speakers,
                    size=len(speakers),
                    replace=True,
                )

                sample = np.concatenate([
                    clusters[s] for s in chosen
                ])

                boot[b] = np.mean(sample)

            low, high = np.quantile(
                boot, [0.025, 0.975]
            )

            output.append({
                "payload_size_bytes": size,
                "feature": feature,
                "n_events": len(selected),
                "n_speaker_groups": len(speakers),
                "mean_delta": observed,
                "ci95_lower": float(low),
                "ci95_upper": float(high),
                "bootstrap_repetitions": repetitions,
                "cluster_unit": "speaker_sha256",
            })

    return output


def calculate_permutation_importance(
    records, groups, seed, folds, repeats
):

    output = []
    selected_groups = (
        "global_all",
        "stream_scalar",
        "stream_histogram",
    )

    for size in (4, 16, 36):

        for group_name in selected_groups:

            cols = groups[group_name]

            X, y, group_ids, meta, _ = make_dataset(
                records, size, "pooled", cols
            )

            cv = StratifiedGroupKFold(
                n_splits=folds,
                shuffle=True,
                random_state=seed,
            )

            for fold, (tr, te) in enumerate(
                cv.split(X, y, group_ids), 1
            ):

                model = make_model(
                    "logistic_regression", seed
                )

                model.fit(X[tr], y[tr])

                importance = permutation_importance(
                    model,
                    X[te],
                    y[te],
                    scoring="roc_auc",
                    n_repeats=repeats,
                    random_state=seed + fold + size,
                    n_jobs=1,
                )

                for j, feature in enumerate(cols):

                    output.append({
                        "payload_size_bytes": size,
                        "feature_group": group_name,
                        "feature": feature,
                        "fold": fold,
                        "importance_mean":
                            float(importance.importances_mean[j]),
                        "importance_std":
                            float(importance.importances_std[j]),
                    })

            print(
                f"Permutation importance complete: "
                f"{size}B / {group_name}"
            )

    return output


def summarize_importance(rows):

    grouped = defaultdict(list)

    for r in rows:
        grouped[
            (r["payload_size_bytes"],
             r["feature_group"],
             r["feature"])
        ].append(r["importance_mean"])

    output = []

    for (size, group, feature), values in grouped.items():

        values = np.asarray(values, dtype=float)

        output.append({
            "payload_size_bytes": size,
            "feature_group": group,
            "feature": feature,
            "mean_importance": float(np.mean(values)),
            "std_across_folds": float(np.std(values, ddof=1)),
            "positive_folds": int(np.sum(values > 0)),
            "n_folds": len(values),
        })

    return output


def save_figures(out, metrics, importance):

    fig, ax = plt.subplots(figsize=(12, 7))

    selected_groups = (
        "global_all",
        "stream_scalar",
        "stream_histogram",
        "packet_geometry",
        "global_without_histogram",
        "target_tail36",
        "target_prefix_control",
    )

    for group in selected_groups:

        rows = sorted([
            r for r in metrics
            if r["scope"] == "pooled"
            and r["model"] == "logistic_regression"
            and r["feature_group"] == group
        ], key=lambda r: r["payload_size_bytes"])

        if rows:
            ax.plot(
                [r["payload_size_bytes"] for r in rows],
                [r["roc_auc"] for r in rows],
                marker="o",
                label=group,
            )

    ax.set(
        xlabel="Payload size (bytes)",
        ylabel="ROC-AUC",
        title="B14: Feature-family ablation",
        ylim=(0, 1.05),
    )

    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()

    fig.savefig(
        out / "b14_feature_ablation_auc.png",
        dpi=220,
    )
    plt.close(fig)

    rows = [
        r for r in importance
        if r["payload_size_bytes"] == 36
        and r["feature_group"] == "global_all"
    ]

    rows = sorted(
        rows,
        key=lambda r: r["mean_importance"],
        reverse=True,
    )[:20]

    if rows:

        fig, ax = plt.subplots(figsize=(10, 8))

        labels = [r["feature"] for r in rows]
        values = [r["mean_importance"] for r in rows]

        ax.barh(labels[::-1], values[::-1])

        ax.set(
            xlabel="Mean held-out permutation importance",
            title="B14: Top global features at 36 bytes",
        )

        ax.grid(True, axis="x", alpha=0.3)
        fig.tight_layout()

        fig.savefig(
            out / "b14_global_permutation_importance.png",
            dpi=220,
        )
        plt.close(fig)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--b12-run",
        required=True,
        help="Exact B12 run directory",
    )

    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--permutation-repeats", type=int, default=3)

    args = parser.parse_args()

    if args.folds < 2:
        raise ValueError("At least two folds required")

    if args.bootstrap < 100:
        raise ValueError("Use at least 100 bootstrap repetitions")

    script = Path(__file__).resolve()
    root = script.parents[2]

    b9 = root / "experiments" / "B9_common_voice"

    b12_run = Path(args.b12_run).expanduser().resolve()
    manifest_path = b12_run / "b12_payload_manifest.csv"

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    print("========== B14 INPUT VALIDATION ==========")
    print("Project root:", root)
    print("B12 run:", b12_run)

    manifest = read_manifest(manifest_path)

    print("Manifest records:", len(manifest))

    records = build_records(
        root, b9, b12_run, manifest
    )

    events = {
        (r["encoder"], r["recording"], r["frame"])
        for r in records
    }

    speakers = {
        r["speaker"] for r in records
    }

    print("Unique events:", len(events))
    print("Unique speaker groups:", len(speakers))
    print("Source hashes: PASS")
    print("Payload integrity: PASS")
    print("Packet framing: PASS")
    print("Unmodified target prefix: PASS")

    keys = sorted(records[0]["cover_features"])
    feature_groups = define_feature_groups(keys)

    base = b9 / "results" / "b14_feature_attribution"
    base.mkdir(parents=True, exist_ok=True)

    out = base / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    out.mkdir()

    metrics = []
    predictions = []

    models = (
        "logistic_regression",
        "random_forest",
    )

    print("\n========== B14 GROUPED-CV EVALUATION ==========")

    # Full feature-family ablation on pooled recordings.
    for size in SIZES:

        for group_name in ALL_GROUPS:

            for model_name in models:

                print(
                    f"{size}B | pooled | "
                    f"{group_name} | {model_name}"
                )

                m, pred = evaluate_group(
                    records,
                    size,
                    "pooled",
                    group_name,
                    feature_groups[group_name],
                    model_name,
                    args.seed,
                    args.folds,
                )

                metrics.append(m)
                predictions.extend(pred)

    # Encoder-specific sensitivity evaluation.
    for size in SIZES:

        for version in VERSIONS:

            for group_name in ENCODER_GROUPS:

                for model_name in models:

                    print(
                        f"{size}B | {version} | "
                        f"{group_name} | {model_name}"
                    )

                    m, pred = evaluate_group(
                        records,
                        size,
                        version,
                        group_name,
                        feature_groups[group_name],
                        model_name,
                        args.seed,
                        args.folds,
                    )

                    metrics.append(m)
                    predictions.extend(pred)

    write_csv(
        out / "b14_feature_group_metrics.csv",
        metrics,
    )

    write_csv(
        out / "b14_oof_predictions.csv",
        predictions,
    )

    print("\n========== PAIRED FEATURE EFFECTS ==========")

    effects = calculate_feature_effects(
        records, keys
    )

    write_csv(
        out / "b14_paired_feature_effects.csv",
        effects,
    )

    print("\n========== SPEAKER-CLUSTERED BOOTSTRAP ==========")

    bootstrap = cluster_bootstrap_effects(
        records,
        args.seed,
        args.bootstrap,
    )

    write_csv(
        out / "b14_cluster_bootstrap_effects.csv",
        bootstrap,
    )

    print("\n========== HELD-OUT PERMUTATION IMPORTANCE ==========")

    perm = calculate_permutation_importance(
        records,
        feature_groups,
        args.seed,
        args.folds,
        args.permutation_repeats,
    )

    perm_summary = summarize_importance(perm)

    write_csv(
        out / "b14_permutation_importance_by_fold.csv",
        perm,
    )

    write_csv(
        out / "b14_permutation_importance_summary.csv",
        perm_summary,
    )

    save_figures(out, metrics, perm_summary)

    # Configuration record.
    config = {
        "stage": "B14",
        "b12_run": str(b12_run),
        "manifest_sha256": sha_file(manifest_path),
        "events": len(events),
        "speaker_groups": len(speakers),
        "encoders": list(VERSIONS),
        "payload_sizes": list(SIZES),
        "primary_repetition": PRIMARY_REPETITION,
        "folds": args.folds,
        "seed": args.seed,
        "bootstrap_repetitions": args.bootstrap,
        "permutation_repeats": args.permutation_repeats,
        "cross_validation": "StratifiedGroupKFold",
        "group_unit": "speaker_sha256",
        "models": list(models),
        "feature_group_sizes": {
            k: len(v) for k, v in feature_groups.items()
        },
        "read_only": True,
    }

    (out / "b14_run_config.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )

    # Main report.
    report = [
        "========== B14 FEATURE ATTRIBUTION REPORT ==========",
        f"Output: {out}",
        f"B12 run: {b12_run}",
        f"Manifest records: {len(manifest)}",
        f"Unique events: {len(events)}",
        f"Speaker groups: {len(speakers)}",
        "Primary repetition: 1",
        f"Grouped CV folds: {args.folds}",
        "Grouping: speaker_sha256",
        "Models: Logistic Regression and Random Forest",
        "",
        "========== FEATURE GROUP SIZES ==========",
    ]

    for name, cols in feature_groups.items():
        report.append(f"{name}: {len(cols)} features")

    report += [
        "",
        "========== POOLED LOGISTIC REGRESSION ==========",
    ]

    important_groups = (
        "global_all",
        "stream_scalar",
        "stream_histogram",
        "packet_geometry",
        "global_without_histogram",
        "global_without_stream_scalars",
        "global_without_packet_geometry",
        "target_packet",
        "target_tail36",
        "target_prefix_control",
    )

    for size in SIZES:

        report.append(f"\nPAYLOAD SIZE: {size} bytes")

        for group_name in important_groups:

            row = next(
                r for r in metrics
                if r["scope"] == "pooled"
                and r["payload_size_bytes"] == size
                and r["feature_group"] == group_name
                and r["model"] == "logistic_regression"
            )

            report.append(
                f"{group_name:35s} "
                f"AUC={row['roc_auc']:.4f} "
                f"BA={row['balanced_accuracy']:.4f} "
                f"TPR={row['tpr']:.4f} "
                f"FPR={row['fpr']:.4f}"
            )

    report += [
        "",
        "========== NEGATIVE CONTROLS ==========",
        "Packet geometry should be unchanged by payload replacement.",
        "Target prefix control should be unchanged by payload replacement.",
        "A materially above-chance negative-control result requires investigation.",
        "",
        "========== TOP GLOBAL PERMUTATION FEATURES: 36B ==========",
    ]

    top = sorted(
        [
            r for r in perm_summary
            if r["payload_size_bytes"] == 36
            and r["feature_group"] == "global_all"
        ],
        key=lambda r: r["mean_importance"],
        reverse=True,
    )[:20]

    for r in top:
        report.append(
            f"{r['feature']:35s} "
            f"importance={r['mean_importance']:.6f} "
            f"positive_folds={r['positive_folds']}/{r['n_folds']}"
        )

    report += [
        "",
        "========== INTERPRETATION LIMITS ==========",
        "- Global stream features are computed over the entire serialized bitstream.",
        "- They do not require knowing the target packet, but include the modified bytes.",
        "- Target-tail features are informed because the embedding location is known.",
        "- The target-prefix control is unchanged by construction.",
        "- Packet geometry is a structural negative control.",
        "- Cover events were preselected for 36 trailing zero bytes.",
        "- Results do not establish universal detectability or undetectability.",
        "- Permutation importance can be distributed across correlated features.",
        "- The sample contains 200 events and 196 speaker groups.",
        "- B14 does not modify source or stego bitstreams.",
        "",
        "B14 FEATURE ATTRIBUTION: COMPLETE",
    ]

    report_path = out / "b14_report.txt"

    report_path.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    checksum = out / "b14_checksums.sha256"

    with checksum.open("w", encoding="utf-8") as f:

        for file in sorted(
            x for x in out.rglob("*")
            if x.is_file() and x != checksum
        ):

            f.write(
                f"{sha_file(file)}  "
                f"{file.relative_to(out).as_posix()}\n"
            )

    print("\n".join(report))

    print("\n========== B14 OUTPUT FILES ==========")

    for file in sorted(out.iterdir()):
        if file.is_file():
            print(file.name, file.stat().st_size, "bytes")

    print("\nB14 checksums:", checksum)
    print("B14 output:", out)


if __name__ == "__main__":
    main()
