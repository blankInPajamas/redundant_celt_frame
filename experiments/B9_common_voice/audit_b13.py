#!/usr/bin/env python3

import csv
import hashlib
import sys
from pathlib import Path
from collections import defaultdict
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score,
    precision_score, recall_score, f1_score,
    roc_auc_score
)

OUT = Path(sys.argv[1]).resolve()

def read_csv(name):
    with (OUT / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def check(condition, message, errors):
    if not condition:
        errors.append(message)

def verify_checksums():
    errors = []
    manifest = OUT / "b13_checksums.sha256"

    for line in manifest.read_text().splitlines():
        expected, filename = line.split("  ", 1)
        path = OUT / filename
        if not path.is_file():
            errors.append(f"MISSING: {filename}")
            continue

        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"HASH MISMATCH: {filename}")

    return errors

def calculate_metrics(rows):
    y = [int(r["y_true"]) for r in rows]
    pred = [int(r["y_pred"]) for r in rows]
    score = [float(r["y_score"]) for r in rows]

    tn = sum(a == 0 and b == 0 for a, b in zip(y, pred))
    fp = sum(a == 0 and b == 1 for a, b in zip(y, pred))
    fn = sum(a == 1 and b == 0 for a, b in zip(y, pred))
    tp = sum(a == 1 and b == 1 for a, b in zip(y, pred))

    return {
        "accuracy": accuracy_score(y, pred),
        "balanced_accuracy": balanced_accuracy_score(y, pred),
        "precision": precision_score(y, pred, zero_division=0),
        "tpr": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "roc_auc": roc_auc_score(y, score),
        "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        "fpr": fp / (fp + tn) if fp + tn else 0,
    }

def main():
    errors = []

    print("========== B13 INDEPENDENT AUDIT ==========")
    print("Run:", OUT)

    check(OUT.is_dir(), "Output directory missing", errors)

    if errors:
        raise SystemExit("\n".join(errors))

    checksum_errors = verify_checksums()
    errors.extend(checksum_errors)

    metrics = read_csv("b13_ml_metrics.csv")
    predictions = read_csv("b13_oof_predictions.csv")
    features = read_csv("b13_feature_summary.csv")
    tails = read_csv("b13_tail_rule_metrics.csv")

    print("\n========== OUTPUT COUNTS ==========")
    print("ML metric rows:", len(metrics))
    print("OOF prediction rows:", len(predictions))
    print("Feature summary rows:", len(features))
    print("Tail-rule rows:", len(tails))

    check(len(metrics) == 108, "Expected 108 ML metric rows", errors)
    check(len(predictions) == 28800,
          "Expected 28,800 OOF prediction rows", errors)
    check(len(features) == 7200,
          "Expected 7,200 feature summary rows", errors)
    check(len(tails) == 54,
          "Expected 54 tail-rule rows", errors)

    print("\n========== TARGET-TAIL CONSTRUCTION ==========")

    cover = [r for r in features if r["class"] == "cover"]
    stego = [r for r in features if r["class"] == "stego"]

    cover_zero = sum(
        float(r["tail36_nonzero_count"]) == 0.0 for r in cover
    )
    stego_nonzero = sum(
        float(r["tail36_nonzero_count"]) > 0.0 for r in stego
    )

    print("Cover rows:", len(cover))
    print("Cover rows with zero nonzero bytes:", cover_zero)
    print("Stego rows:", len(stego))
    print("Stego rows with at least one nonzero byte:", stego_nonzero)

    check(len(cover) == 3600, "Unexpected cover row count", errors)
    check(len(stego) == 3600, "Unexpected stego row count", errors)

    print("\n========== GROUPED-CV LEAKAGE AUDIT ==========")

    groups = defaultdict(set)
    event_pairs = defaultdict(list)

    for r in predictions:
        key = (
            r["scope"], r["payload_size_bytes"],
            r["feature_set"], r["model"]
        )
        groups[key + (r["speaker_sha256"],)].add(r["fold"])

        event_key = key + (r["encoder"], r["recording"])
        event_pairs[event_key].append(r)

    leakage = 0
    for key, folds in groups.items():
        if len(folds) != 1:
            leakage += 1
            errors.append(f"Speaker crosses CV folds: {key}")

    bad_pairs = 0
    for key, rows in event_pairs.items():
        labels = sorted(r["class"] for r in rows)
        fold_values = {r["fold"] for r in rows}

        if len(rows) != 2 or labels != ["cover", "stego"]:
            bad_pairs += 1
            errors.append(f"Invalid cover/stego pair: {key}")

        if len(fold_values) != 1:
            bad_pairs += 1
            errors.append(f"Cover/stego pair split across folds: {key}")

    print("Speaker-fold leakage cases:", leakage)
    print("Invalid or split event pairs:", bad_pairs)
    print("Unique event-pair groups:", len(event_pairs))

    print("\n========== METRIC RECOMPUTATION ==========")

    pred_groups = defaultdict(list)

    for r in predictions:
        key = (
            r["scope"], r["payload_size_bytes"],
            r["feature_set"], r["model"]
        )
        pred_groups[key].append(r)

    metric_lookup = {
        (
            r["scope"], r["payload_size_bytes"],
            r["feature_set"], r["model"]
        ): r for r in metrics
    }

    mismatch = 0

    for key, rows in pred_groups.items():
        if key not in metric_lookup:
            errors.append(f"Missing metric row: {key}")
            mismatch += 1
            continue

        recomputed = calculate_metrics(rows)
        saved = metric_lookup[key]

        for name, value in recomputed.items():
            if abs(float(saved[name]) - float(value)) > 1e-6:
                mismatch += 1
                errors.append(
                    f"Metric mismatch: {key} / {name}"
                )

    print("Prediction groups:", len(pred_groups))
    print("Metric mismatches:", mismatch)

    print("\n========== POOLED MODEL COMPARISON ==========")

    comparison = []

    for r in metrics:
        if r["scope"] != "pooled":
            continue

        row = {
            "payload_size_bytes": r["payload_size_bytes"],
            "feature_set": r["feature_set"],
            "model": r["model"],
            "roc_auc": r["roc_auc"],
            "accuracy": r["accuracy"],
            "balanced_accuracy": r["balanced_accuracy"],
            "tpr": r["tpr"],
            "fpr": r["fpr"],
            "f1": r["f1"],
        }
        comparison.append(row)

    comparison.sort(
        key=lambda r: (
            int(r["payload_size_bytes"]),
            r["feature_set"],
            r["model"]
        )
    )

    with (OUT / "b13_independent_model_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(comparison)

    for r in comparison:
        print(
            f"{r['payload_size_bytes']:>2}B | "
            f"{r['feature_set']:<8} | "
            f"{r['model']:<22} | "
            f"AUC={float(r['roc_auc']):.4f} | "
            f"BA={float(r['balanced_accuracy']):.4f} | "
            f"FPR={float(r['fpr']):.4f}"
        )

    print("\n========== GLOBAL-ONLY RESULTS ==========")

    global_rows = [
        r for r in comparison if r["feature_set"] == "global"
    ]

    for r in global_rows:
        print(
            f"{r['payload_size_bytes']:>2}B | "
            f"{r['model']:<22} | "
            f"AUC={float(r['roc_auc']):.4f} | "
            f"Accuracy={float(r['accuracy']):.4f} | "
            f"FPR={float(r['fpr']):.4f}"
        )

    print("\n========== TAIL RULE ==========")

    for r in tails:
        if r["scope"] == "pooled":
            print(
                f"{r['payload_size_bytes']}B | "
                f"rep={r['repetition']} | "
                f"accuracy={float(r['accuracy']):.4f} | "
                f"TPR={float(r['tpr']):.4f} | "
                f"FPR={float(r['fpr']):.4f}"
            )

    status = "PASS" if not errors else "FAIL"

    report = [
        "========== B13 INDEPENDENT AUDIT REPORT ==========",
        f"Run: {OUT}",
        f"Checksum errors: {len(checksum_errors)}",
        f"ML metric rows: {len(metrics)}",
        f"OOF prediction rows: {len(predictions)}",
        f"Feature summary rows: {len(features)}",
        f"Tail-rule rows: {len(tails)}",
        f"Cover zero-tail rows: {cover_zero}/{len(cover)}",
        f"Stego nonzero-tail rows: {stego_nonzero}/{len(stego)}",
        f"Speaker leakage cases: {leakage}",
        f"Invalid event pairs: {bad_pairs}",
        f"Metric mismatches: {mismatch}",
        f"Errors: {len(errors)}",
        "",
        "INTERPRETATION:",
        "- Target-tail classification is an informed, target-aware test.",
        "- Global-only classification is the more relevant non-localized baseline.",
        "- Perfect detection must not be interpreted as universal detectability.",
        "- This audit does not establish resistance to other detection methods.",
        "",
        f"AUDIT STATUS: {status}",
    ]

    if errors:
        report += ["", "ERROR DETAILS:"] + errors

    text = "\n".join(report) + "\n"

    (OUT / "b13_independent_audit_report.txt").write_text(
        text, encoding="utf-8"
    )

    print("\n" + text)

    if errors:
        raise SystemExit(1)

    print("B13 INDEPENDENT AUDIT: PASS")


if __name__ == "__main__":
    main()
