#!/usr/bin/env python3
"""B13: paired steganalysis of the B12 Opus bitstreams.

ML uses repetition 1 as the primary trial. Repetitions 2 and 3 are used
for descriptive and simple-tail-rule reproducibility checks only.
"""
import argparse
import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score, roc_curve,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSIONS = ("1.5.2", "1.6.1")
SIZES = (4, 8, 16, 24, 32, 36)
CAPACITY = 36
ML_REPETITION = 1


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_packets(raw, label):
    packets, offset = [], 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError(f"{label}: incomplete packet header")
        n = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if n <= 0 or offset + n > len(raw):
            raise ValueError(f"{label}: invalid packet length {n}")
        packets.append(raw[offset:offset + n])
        offset += n
    if not packets:
        raise ValueError(f"{label}: no packets")
    return packets


def add_region_features(out, prefix, raw):
    a = np.frombuffer(raw, dtype=np.uint8)
    if not a.size:
        raise ValueError(f"Empty region: {prefix}")
    counts = np.bincount(a, minlength=256).astype(float)
    hist = counts / a.size
    p = hist[hist > 0]
    z = (a == 0)
    longest = run = 0
    for v in z:
        run = run + 1 if v else 0
        longest = max(longest, run)
    trailing = 0
    for v in z[::-1]:
        if not v:
            break
        trailing += 1

    out[f"{prefix}_nbytes"] = float(a.size)
    out[f"{prefix}_zero_fraction"] = float(np.mean(z))
    out[f"{prefix}_nonzero_count"] = float(np.count_nonzero(a))
    out[f"{prefix}_unique_count"] = float(np.unique(a).size)
    out[f"{prefix}_mean"] = float(np.mean(a))
    out[f"{prefix}_std"] = float(np.std(a))
    out[f"{prefix}_entropy"] = float(-(p * np.log2(p)).sum())
    out[f"{prefix}_transition_rate"] = (
        float(np.mean(a[1:] != a[:-1])) if a.size > 1 else 0.0
    )
    out[f"{prefix}_longest_zero_run"] = float(longest)
    out[f"{prefix}_trailing_zero_bytes"] = float(trailing)
    for i, value in enumerate(hist):
        out[f"{prefix}_hist_{i:03d}"] = float(value)


def extract_features(raw, packets, frame):
    if frame < 0 or frame >= len(packets):
        raise ValueError(f"Target frame {frame} outside packet count")
    target = packets[frame]
    if len(target) < CAPACITY:
        raise ValueError("Target packet shorter than 36 bytes")
    out = {}
    add_region_features(out, "g_stream", raw)
    add_region_features(out, "t_packet", target)
    add_region_features(out, "t_tail36", target[-CAPACITY:])
    lengths = np.asarray([len(p) for p in packets], dtype=float)
    out["g_packet_count"] = float(len(packets))
    out["g_packet_length_mean"] = float(np.mean(lengths))
    out["g_packet_length_std"] = float(np.std(lengths))
    out["g_packet_length_min"] = float(np.min(lengths))
    out["g_packet_length_max"] = float(np.max(lengths))
    return out


def read_manifest(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"Empty manifest: {path}")
    required = {
        "encoder", "recording", "speaker_sha256", "frame",
        "payload_size_bytes", "repetition", "payload_hex",
        "payload_sha256", "source_bitstream_sha256",
        "modified_bitstream_sha256", "modified_bitstream",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError("B12 manifest missing columns: " + ", ".join(sorted(missing)))
    return rows


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build_records(root, b9, b12_run, manifest):
    source_cache, records, seen = {}, [], set()
    for i, row in enumerate(manifest, 1):
        enc = row["encoder"].strip()
        rec = row["recording"].strip()
        speaker = row["speaker_sha256"].strip()
        frame = int(row["frame"])
        size = int(row["payload_size_bytes"])
        rep = int(row["repetition"])
        if enc not in VERSIONS or size not in SIZES or rep not in (1, 2, 3):
            raise ValueError(f"Unexpected manifest values in row {i}")
        if not speaker:
            raise ValueError(f"Missing speaker hash: {enc}/{rec}")
        event = (enc, rec, frame)
        row_key = event + (size, rep)
        if row_key in seen:
            raise ValueError(f"Duplicate manifest row: {row_key}")
        seen.add(row_key)

        source_path = (
            b9 / "results" / "b9_full_encoding" / enc
            / "bitstreams" / f"{rec}.bin"
        )
        if not source_path.is_file():
            raise FileNotFoundError(f"Cover bitstream missing: {source_path}")

        if event not in source_cache:
            raw = source_path.read_bytes()
            if sha_bytes(raw) != row["source_bitstream_sha256"]:
                raise ValueError(f"Cover SHA256 mismatch: {source_path}")
            packets = read_packets(raw, str(source_path))
            if frame >= len(packets) or packets[frame][-CAPACITY:] != bytes(CAPACITY):
                raise ValueError(f"Cover target tail is not 36 zero bytes: {enc}/{rec}")
            source_cache[event] = {
                "packets": packets,
                "features": extract_features(raw, packets, frame),
                "packet_lengths": [len(p) for p in packets],
            }
        cover = source_cache[event]
        if cover.get("speaker") not in (None, speaker):
            raise ValueError(f"Speaker hash changes within event: {enc}/{rec}")
        cover["speaker"] = speaker

        rel = Path(row["modified_bitstream"])
        stego_path = (b12_run / rel).resolve()
        if not stego_path.is_relative_to(b12_run.resolve()):
            raise ValueError(f"Modified path escapes B12 run: {rel}")
        if not stego_path.is_file():
            raise FileNotFoundError(f"Stego bitstream missing: {stego_path}")
        stego_raw = stego_path.read_bytes()
        if sha_bytes(stego_raw) != row["modified_bitstream_sha256"]:
            raise ValueError(f"Stego SHA256 mismatch: {stego_path}")
        stego_packets = read_packets(stego_raw, str(stego_path))
        if len(stego_packets) != len(cover["packets"]):
            raise ValueError(f"Packet count changed: {stego_path}")
        if [len(p) for p in stego_packets] != cover["packet_lengths"]:
            raise ValueError(f"Packet lengths changed: {stego_path}")

        payload = bytes.fromhex(row["payload_hex"])
        if len(payload) != size or sha_bytes(payload) != row["payload_sha256"]:
            raise ValueError(f"Payload integrity mismatch: {stego_path}")
        expected_tail = bytes(CAPACITY - size) + payload
        if stego_packets[frame][-CAPACITY:] != expected_tail:
            raise ValueError(f"Target tail does not match payload: {stego_path}")
        if stego_packets[frame][:-CAPACITY] != cover["packets"][frame][:-CAPACITY]:
            raise ValueError(f"Target packet prefix changed: {stego_path}")

        tail = stego_packets[frame][-CAPACITY:]
        records.append({
            "encoder": enc, "recording": rec, "speaker": speaker,
            "frame": frame, "size": size, "rep": rep,
            "cover_features": cover["features"],
            "stego_features": extract_features(stego_raw, stego_packets, frame),
            "cover_tail_nonzero": 0,
            "stego_tail_nonzero": int(np.count_nonzero(tail)),
        })
        if i % 300 == 0:
            print(f"Validated {i}/{len(manifest)} manifest rows")

    if len(records) != 3600:
        raise ValueError(f"Expected 3,600 B12 rows, found {len(records)}")
    if len({(r["encoder"], r["recording"], r["frame"]) for r in records}) != 200:
        raise ValueError("Expected exactly 200 unique recording events")
    for size in SIZES:
        for rep in (1, 2, 3):
            n = sum(r["size"] == size and r["rep"] == rep for r in records)
            if n != 200:
                raise ValueError(f"Expected 200 rows for {size}B rep{rep}; found {n}")
    return records

def metric_dict(y, pred, score):
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "tpr": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, score)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
        "fpr": float(fp / (fp + tn)) if fp + tn else 0.0,
    }


def evaluate_ml(records, size, scope, feature_set, cols, model_name, model, seed, folds):
    selected = [
        r for r in records
        if r["size"] == size and r["rep"] == ML_REPETITION
        and (scope == "pooled" or r["encoder"] == scope)
    ]
    X, y, groups, meta = [], [], [], []
    for r in selected:
        for label, key in ((0, "cover_features"), (1, "stego_features")):
            X.append([r[key][c] for c in cols])
            y.append(label)
            groups.append(r["speaker"])
            meta.append((r["encoder"], r["recording"], r["speaker"], label))
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    if len(np.unique(groups)) < folds:
        raise ValueError(f"Not enough speaker groups for {scope}")
    cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    scores = np.full(len(y), np.nan)
    preds = np.full(len(y), -1, dtype=int)
    fold_ids = np.full(len(y), -1, dtype=int)

    for fold, (tr, te) in enumerate(cv.split(X, y, groups), 1):
        if set(groups[tr]) & set(groups[te]):
            raise RuntimeError("Speaker leakage detected")
        if len(np.unique(y[tr])) != 2 or len(np.unique(y[te])) != 2:
            raise RuntimeError(f"Fold {fold} missing a class")
        est = clone(model)
        est.fit(X[tr], y[tr])
        scores[te] = est.predict_proba(X[te])[:, 1]
        preds[te] = (scores[te] >= 0.5).astype(int)
        fold_ids[te] = fold

    if np.isnan(scores).any() or np.any(preds < 0):
        raise RuntimeError("Missing out-of-fold predictions")

    result = metric_dict(y, preds, scores)
    result.update({
        "scope": scope, "payload_size_bytes": size,
        "repetition": ML_REPETITION, "feature_set": feature_set,
        "model": model_name, "n_samples": int(len(y)),
        "n_events": int(len(selected)),
        "n_speaker_groups": int(len(np.unique(groups))),
        "cv_folds": folds, "split_unit": "speaker_sha256",
        "decision_threshold": 0.5,
    })
    pred_rows = []
    for i, (enc, rec, speaker, label) in enumerate(meta):
        pred_rows.append({
            "scope": scope, "payload_size_bytes": size,
            "repetition": ML_REPETITION, "feature_set": feature_set,
            "model": model_name, "encoder": enc, "recording": rec,
            "speaker_sha256": speaker,
            "class": "stego" if label else "cover",
            "y_true": int(y[i]), "y_score": float(scores[i]),
            "y_pred": int(preds[i]), "fold": int(fold_ids[i]),
        })
    roc = None
    if scope == "pooled" and size == 36:
        roc = roc_curve(y, scores)[:2]
    return result, pred_rows, roc


def tail_rule_metrics(records):
    out = []
    for size in SIZES:
        for rep in (1, 2, 3):
            for scope in ("pooled", "1.5.2", "1.6.1"):
                subset = [
                    r for r in records
                    if r["size"] == size and r["rep"] == rep
                    and (scope == "pooled" or r["encoder"] == scope)
                ]
                y, pred = [], []
                for r in subset:
                    y.extend((0, 1))
                    pred.extend((0, int(r["stego_tail_nonzero"] > 0)))
                y = np.asarray(y)
                pred = np.asarray(pred)
                vals = metric_dict(y, pred, pred.astype(float))
                out.append({
                    "scope": scope, "payload_size_bytes": size,
                    "repetition": rep, "n_events": len(subset),
                    "rule": "stego_if_any_nonzero_byte_in_target_36B_tail",
                    **vals,
                })
    return out


def save_figures(out_dir, metrics, tail_rows, roc_data):
    fig, ax = plt.subplots(figsize=(10, 6))
    for feat in ("global", "target", "combined"):
        for model in ("logistic_regression", "random_forest"):
            rows = sorted(
                [r for r in metrics if r["scope"] == "pooled"
                 and r["feature_set"] == feat and r["model"] == model],
                key=lambda x: x["payload_size_bytes"],
            )
            if rows:
                ax.plot(
                    [r["payload_size_bytes"] for r in rows],
                    [r["roc_auc"] for r in rows],
                    marker="o", label=f"{feat} / {model.replace('_', ' ')}",
                )
    ax.set(xlabel="Payload size (bytes)", ylabel="ROC-AUC",
           title="B13 grouped-CV steganalysis by payload size", ylim=(0, 1.05))
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "b13_auc_by_payload_size.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for rep in (1, 2, 3):
        rows = sorted(
            [r for r in tail_rows if r["scope"] == "pooled" and r["repetition"] == rep],
            key=lambda x: x["payload_size_bytes"],
        )
        ax.plot([r["payload_size_bytes"] for r in rows],
                [r["accuracy"] for r in rows], marker="o", label=f"Rep {rep}")
    ax.set(xlabel="Payload size (bytes)", ylabel="Accuracy",
           title="B13 simple target-tail detector", ylim=(0, 1.05))
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "b13_tail_rule_accuracy.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 6))
    for label, (fpr, tpr) in roc_data.items():
        ax.plot(fpr, tpr, label=label.replace("_", " "))
    ax.plot([0, 1], [0, 1], linestyle="--", label="Chance")
    ax.set(xlabel="False-positive rate", ylabel="True-positive rate",
           title="B13 ROC curves: pooled 36-byte payload")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "b13_roc_36B.png", dpi=220)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--b12-run", required=True, help="Exact B12 run directory")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    script_path = Path(__file__).resolve()
    root = script_path.parents[2]
    b9 = root / "experiments" / "B9_common_voice"
    b12_run = Path(args.b12_run).expanduser().resolve()
    manifest_path = b12_run / "b12_payload_manifest.csv"
    if not b12_run.is_dir() or not manifest_path.is_file():
        raise FileNotFoundError(f"B12 run or manifest not found: {b12_run}")
    if args.folds < 2:
        raise ValueError("--folds must be at least 2")

    print("========== B13 INPUT VALIDATION ==========")
    print("Project root:", root)
    print("B12 run:", b12_run)
    manifest = read_manifest(manifest_path)
    print("Manifest rows:", len(manifest))
    records = build_records(root, b9, b12_run, manifest)
    n_events = len({(r["encoder"], r["recording"], r["frame"]) for r in records})
    n_speakers = len({r["speaker"] for r in records})
    print("Unique events:", n_events)
    print("Unique speaker groups across both versions:", n_speakers)
    print("Cover/stego hashes, packet framing and payload-tail checks: PASS")

    base = b9 / "results" / "b13_steganalysis"
    base.mkdir(parents=True, exist_ok=True)
    out = base / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    out.mkdir()

    keys = sorted(records[0]["cover_features"])
    global_cols = [k for k in keys if k.startswith("g_")]
    target_cols = [k for k in keys if k.startswith(("t_packet_", "t_tail36_"))]
    feature_sets = {
        "global": global_cols,
        "target": target_cols,
        "combined": global_cols + target_cols,
    }

    # Compact descriptive table: all cover/stego pairs and all three repetitions.
    desc = []
    for r in records:
        for label, key in ((0, "cover_features"), (1, "stego_features")):
            f = r[key]
            desc.append({
                "encoder": r["encoder"], "recording": r["recording"],
                "speaker_sha256": r["speaker"], "frame": r["frame"],
                "payload_size_bytes": r["size"], "repetition": r["rep"],
                "class": "stego" if label else "cover",
                "stream_entropy": f["g_stream_entropy"],
                "stream_zero_fraction": f["g_stream_zero_fraction"],
                "target_packet_entropy": f["t_packet_entropy"],
                "tail36_entropy": f["t_tail36_entropy"],
                "tail36_zero_fraction": f["t_tail36_zero_fraction"],
                "tail36_nonzero_count": f["t_tail36_nonzero_count"],
                "tail36_trailing_zero_bytes": f["t_tail36_trailing_zero_bytes"],
            })
    write_csv(out / "b13_feature_summary.csv", desc)

    tails = tail_rule_metrics(records)
    write_csv(out / "b13_tail_rule_metrics.csv", tails)

    models = {
        "logistic_regression": make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=5000, class_weight="balanced",
                solver="liblinear", random_state=args.seed,
            ),
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=250, max_features="sqrt", min_samples_leaf=2,
            class_weight="balanced_subsample", random_state=args.seed,
            n_jobs=-1,
        ),
    }

    metrics, predictions, rocs = [], [], {}
    print("========== B13 GROUPED ML EVALUATION ==========")
    for size in SIZES:
        for scope in ("pooled", "1.5.2", "1.6.1"):
            for feat_name, cols in feature_sets.items():
                for model_name, model in models.items():
                    print(f"{size}B | {scope} | {feat_name} | {model_name}")
                    m, pred, roc = evaluate_ml(
                        records, size, scope, feat_name, cols,
                        model_name, model, args.seed, args.folds,
                    )
                    metrics.append(m)
                    predictions.extend(pred)
                    if roc is not None:
                        rocs[f"{feat_name}_{model_name}"] = roc

    write_csv(out / "b13_ml_metrics.csv", metrics)
    write_csv(out / "b13_oof_predictions.csv", predictions)
    save_figures(out, metrics, tails, rocs)

    config = {
        "stage": "B13",
        "b12_run": str(b12_run),
        "events": n_events,
        "speaker_groups": n_speakers,
        "encoders": list(VERSIONS),
        "payload_sizes_bytes": list(SIZES),
        "manifest_repetitions": [1, 2, 3],
        "ml_primary_repetition": ML_REPETITION,
        "feature_sets": {k: len(v) for k, v in feature_sets.items()},
        "models": list(models),
        "cross_validation": "StratifiedGroupKFold",
        "folds": args.folds,
        "group_key": "speaker_sha256",
        "seed": args.seed,
        "threshold": 0.5,
    }
    (out / "b13_run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    pooled = [r for r in metrics if r["scope"] == "pooled"]
    best = max(pooled, key=lambda x: x["roc_auc"])
    tail_rep1 = sorted(
        [r for r in tails if r["scope"] == "pooled" and r["repetition"] == 1],
        key=lambda x: x["payload_size_bytes"],
    )
    report = [
        "========== B13 STEGANALYSIS REPORT ==========",
        f"B12 run: {b12_run}",
        f"Manifest rows validated: {len(manifest)}",
        f"Unique events: {n_events}",
        f"Unique speaker groups: {n_speakers}",
        "Encoders: Opus 1.5.2 and 1.6.1",
        "Payload sizes: 4, 8, 16, 24, 32, 36 bytes",
        "ML primary repetition: 1",
        f"Cross-validation: {args.folds}-fold StratifiedGroupKFold",
        "Grouping: speaker_sha256",
        "Feature groups: global, target-region, combined",
        "Models: Logistic Regression and Random Forest",
        "",
        "========== BEST POOLED ML RESULT ==========",
        f"Payload size: {best['payload_size_bytes']} bytes",
        f"Feature set: {best['feature_set']}",
        f"Model: {best['model']}",
        f"ROC-AUC: {best['roc_auc']:.4f}",
        f"Accuracy: {best['accuracy']:.4f}",
        f"Balanced accuracy: {best['balanced_accuracy']:.4f}",
        f"TPR: {best['tpr']:.4f}",
        f"FPR: {best['fpr']:.4f}",
        "",
        "========== SIMPLE TAIL RULE: POOLED, REP 1 ==========",
    ]
    for r in tail_rep1:
        report.append(
            f"{r['payload_size_bytes']}B: accuracy={r['accuracy']:.4f}, "
            f"TPR={r['tpr']:.4f}, FPR={r['fpr']:.4f}"
        )
    report += [
        "",
        "========== INTERPRETATION LIMITS ==========",
        "- Cover events were preselected to have exactly 36 zero bytes at the target tail.",
        "- The tail rule is an informed detector because the target region is known.",
        "- Global-only features provide a less localized comparison.",
        "- ML uses repetition 1; repetitions 2 and 3 are not independent recordings.",
        "- Speaker-grouped CV prevents the same speaker entering both train and test folds.",
        "- These results do not establish detectability or undetectability for all Opus traffic.",
        "- B13 is read-only; original B12 source bitstreams are not modified.",
        "",
        f"Output directory: {out}",
    ]
    (out / "b13_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    checksum = out / "b13_checksums.sha256"
    with checksum.open("w", encoding="utf-8") as f:
        for file in sorted(x for x in out.rglob("*") if x.is_file() and x != checksum):
            f.write(f"{sha_file(file)}  {file.relative_to(out).as_posix()}\n")

    print("\n".join(report))
    print("Checksums:", checksum)
    print("B13 output:", out)


if __name__ == "__main__":
    main()
