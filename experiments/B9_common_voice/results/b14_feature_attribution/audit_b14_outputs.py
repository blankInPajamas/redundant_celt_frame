import csv
import sys
from pathlib import Path
from collections import defaultdict

from sklearn.metrics import (
    roc_auc_score,
    balanced_accuracy_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)

run = Path(sys.argv[1])

with (run / "b14_oof_predictions.csv").open(
    newline="", encoding="utf-8"
) as f:
    rows = list(csv.DictReader(f))

assert len(rows) == 76800, len(rows)

groups = defaultdict(list)

for r in rows:
    key = (
        r["scope"],
        r["payload_size_bytes"],
        r["feature_group"],
        r["model"],
    )
    groups[key].append(r)

metrics = []

for key, data in sorted(groups.items()):

    y = [int(r["y_true"]) for r in data]
    score = [float(r["y_score"]) for r in data]

    # Resolve exact 0.5 ties as negative.
    pred = [int(s > 0.5) for s in score]

    tn, fp, fn, tp = confusion_matrix(
        y, pred, labels=[0, 1]
    ).ravel()

    metrics.append({
        "scope": key[0],
        "payload_size_bytes": key[1],
        "feature_group": key[2],
        "model": key[3],
        "n_samples": len(data),
        "roc_auc": roc_auc_score(y, score),
        "accuracy": accuracy_score(y, pred),
        "balanced_accuracy": balanced_accuracy_score(y, pred),
        "precision": precision_score(
            y, pred, zero_division=0
        ),
        "tpr": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "fpr": fp / (fp + tn) if fp + tn else 0,
        "n_tied_scores": sum(abs(s - 0.5) < 1e-12 for s in score),
        "threshold": 0.5,
        "tie_policy": "negative",
    })

assert len(metrics) == 252, len(metrics)

def write_csv(path, data):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)

write_csv(
    run / "b14_corrected_metrics.csv",
    metrics
)

# Compare cover/stego OOF scores for the two negative controls.
pairs = defaultdict(dict)

for r in rows:
    if r["feature_group"] not in (
        "packet_geometry",
        "target_prefix_control",
    ):
        continue

    key = (
        r["scope"],
        r["payload_size_bytes"],
        r["feature_group"],
        r["model"],
        r["encoder"],
        r["recording"],
        r["speaker_sha256"],
    )

    pairs[key][int(r["y_true"])] = float(r["y_score"])

control_groups = defaultdict(list)

for key, values in pairs.items():
    group_key = key[:4]

    if 0 in values and 1 in values:
        control_groups[group_key].append(
            abs(values[0] - values[1])
        )

control_report = []

for key, differences in sorted(control_groups.items()):
    control_report.append({
        "scope": key[0],
        "payload_size_bytes": key[1],
        "feature_group": key[2],
        "model": key[3],
        "n_pairs": len(differences),
        "exact_equal_score_pairs": sum(
            d == 0 for d in differences
        ),
        "max_absolute_score_difference": max(differences),
        "all_pairs_equal": all(d == 0 for d in differences),
    })

write_csv(
    run / "b14_negative_control_pair_audit.csv",
    control_report
)

print("B14 corrected metrics:", len(metrics))
print("B14 control audit groups:", len(control_report))
print("B14 prediction rows:", len(rows))

for r in control_report:
    print(r)

print("\nB14 reporting audit complete.")
