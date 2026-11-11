#!/usr/bin/env python3

import csv
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from sklearn.metrics import (
    precision_recall_curve,
    average_precision_score,
    roc_auc_score,
)

# --------------------------------------------------
# PATHS AND CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]

RUN = (
    ROOT
    / "experiments/B17_cross_domain/results/"
      "b17_music_cross_domain/run_20261106_005837"
)

INPUT = RUN / "b17_music_predictions.csv"

FIG_DIR = ROOT / "figures"

OUTPUT_PNG = FIG_DIR / "fig7_b17_precision_recall.png"
OUTPUT_PDF = FIG_DIR / "fig7_b17_precision_recall.pdf"

OUTPUT_METRICS = RUN / "b17_precision_recall_metrics.csv"

PAYLOAD_SIZE = 36

FEATURE_GROUP = "global_without_packet_geometry"

CONDITIONS = [
    ("1.5.2", "logistic_regression",
     "Opus 1.5.2 — Logistic Regression"),

    ("1.5.2", "random_forest",
     "Opus 1.5.2 — Random Forest"),

    ("1.6.1", "logistic_regression",
     "Opus 1.6.1 — Logistic Regression"),

    ("1.6.1", "random_forest",
     "Opus 1.6.1 — Random Forest"),
]


def main():

    if not INPUT.is_file():
        raise FileNotFoundError(INPUT)

    with INPUT.open(
        newline="", encoding="utf-8-sig"
    ) as f:
        rows = list(csv.DictReader(f))

    required = {
        "training_payload_size_bytes",
        "test_encoder",
        "feature_group",
        "model",
        "recording",
        "class",
        "y_true",
        "y_score",
    }

    if not rows or not required.issubset(rows[0]):
        raise ValueError("Prediction CSV has an unexpected schema")

    # Primary B17 condition only.
    selected = [
        r for r in rows
        if int(r["training_payload_size_bytes"]) == PAYLOAD_SIZE
        and r["feature_group"] == FEATURE_GROUP
    ]

    if not selected:
        raise ValueError("No primary B17 prediction rows found")

    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------
    # TWO-PANEL PRECISION-RECALL FIGURE
    # --------------------------------------------------

    fig, axes = plt.subplots(
        1, 2,
        figsize=(7.0, 3.6),
        sharex=True
    )

    metrics = []

    for encoder, model, label in CONDITIONS:

        group = [
            r for r in selected
            if r["test_encoder"] == encoder
            and r["model"] == model
        ]

        counts = Counter(r["class"] for r in group)

        if len(group) != 1009:
            raise ValueError(
                f"{encoder}/{model}: expected 1009 rows, "
                f"found {len(group)}"
            )

        if counts != Counter({"cover": 999, "positive": 10}):
            raise ValueError(
                f"Unexpected class counts: {encoder}/{model}: {counts}"
            )

        cover_ids = {
            r["recording"] for r in group
            if r["class"] == "cover"
        }

        positive_ids = {
            r["recording"] for r in group
            if r["class"] == "positive"
        }

        if not positive_ids.issubset(cover_ids):
            raise ValueError("Positive recordings lack matched clean covers")

        if len({r["recording"] for r in group}) != 999:
            raise ValueError("Unexpected unique recording count")

        if len({
            (r["recording"], r["class"]) for r in group
        }) != len(group):
            raise ValueError("Duplicate recording/class prediction")

        y_true = np.asarray(
            [int(r["y_true"]) for r in group],
            dtype=int
        )

        scores = np.asarray(
            [float(r["y_score"]) for r in group],
            dtype=float
        )

        # Validate class labels against the recorded class.
        for r in group:
            expected = 1 if r["class"] == "positive" else 0
            if int(r["y_true"]) != expected:
                raise ValueError("Class-label mismatch")

        if not np.all(np.isfinite(scores)):
            raise ValueError("Non-finite prediction score")

        precision, recall, _ = precision_recall_curve(
            y_true, scores
        )

        ap = average_precision_score(y_true, scores)

        auc = roc_auc_score(y_true, scores)

        prevalence = float(np.mean(y_true))

        # Full-range PR curve.
        axes[0].step(
            recall,
            precision,
            where="post",
            linewidth=1.5,
            label=f"{label} (AP={ap:.4f})"
        )

        # Magnified view near the positive prevalence.
        axes[1].step(
            recall,
            precision,
            where="post",
            linewidth=1.5,
            label=f"{label} (AP={ap:.4f})"
        )

        metrics.append({
            "encoder": encoder,
            "classifier": model,
            "training_payload_size_bytes": PAYLOAD_SIZE,
            "feature_group": FEATURE_GROUP,
            "n_total": len(group),
            "n_clean": len(cover_ids),
            "n_positive": len(positive_ids),
            "n_unique_recordings": len(
                {r["recording"] for r in group}
            ),
            "positive_prevalence": prevalence,
            "average_precision": ap,
            "random_baseline_ap": prevalence,
            "roc_auc": auc,
        })

        print(
            f"{encoder} | {model} | "
            f"AP={ap:.6f} | AUC={auc:.6f}"
        )

    # Positive prevalence baseline.
    baseline = 10 / 1009

    axes[0].axhline(
        baseline,
        linestyle="--",
        linewidth=1.2,
        label=f"Prevalence baseline ({baseline:.4f})"
    )

    axes[1].axhline(
        baseline,
        linestyle="--",
        linewidth=1.2,
    )

    # Left panel: complete precision range.
    axes[0].set_xlim(0, 1)
    axes[0].set_ylim(0, 1.02)
    axes[0].set_title("(a) Full precision range")
    axes[0].set_ylabel("Precision")
    axes[0].set_xlabel("Recall")

    # Right panel: magnified precision range.
    axes[1].set_xlim(0, 1)
    axes[1].set_ylim(0, 0.02)
    axes[1].set_title("(b) Zoomed precision range")
    axes[1].set_ylabel("Precision")
    axes[1].set_xlabel("Recall")

    for ax in axes:
        ax.grid(True, alpha=0.25)

    handles, labels = axes[0].get_legend_handles_labels()

    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=2,
        fontsize=7,
        frameon=False
    )

    fig.tight_layout(
        rect=[0, 0.20, 1, 0.96]
    )

    # --------------------------------------------------
    # SAVE FIGURES
    # --------------------------------------------------

    fig.savefig(
        OUTPUT_PNG,
        dpi=300,
        bbox_inches="tight"
    )

    fig.savefig(
        OUTPUT_PDF,
        bbox_inches="tight"
    )

    plt.close(fig)

    # --------------------------------------------------
    # SAVE METRICS
    # --------------------------------------------------

    with OUTPUT_METRICS.open(
        "w", newline="", encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(metrics[0].keys())
        )

        writer.writeheader()
        writer.writerows(metrics)

    print("\n========== B17 PR GENERATION COMPLETE ==========")
    print("Input:", INPUT)
    print("PNG:", OUTPUT_PNG)
    print("PDF:", OUTPUT_PDF)
    print("Metrics:", OUTPUT_METRICS)
    print("Positive prevalence:", baseline)


if __name__ == "__main__":
    main()
