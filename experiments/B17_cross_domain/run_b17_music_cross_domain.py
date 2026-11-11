#!/usr/bin/env python3
"""B17: Common Voice -> GTZAN natural-music cross-domain steganalysis.

This reproduces the B17 design from the second research conversation.
It reads the frozen B7/B9/B12/B14/B15/B16 evidence and writes new B17
outputs only. It does not modify prior experimental data.
"""

import csv
import hashlib
import importlib.util
import json
import sys
import joblib
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    roc_auc_score,
    roc_curve,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path.home() / "research/redundant_celt_frame_steganography"
B9 = ROOT / "experiments/B9_common_voice"
B12 = B9 / "results/b12_payload_reliability/run_20261104_020705"
B14_SCRIPT = B9 / "run_b14_feature_attribution.py"
B14 = B9 / "results/b14_feature_attribution/run_20261104_110548"
B16_SHARED = (
    B9 / "results/b16_cross_version_transfer"
    / "preflight_20261105_161055/b16_shared_speakers.csv"
)
B7 = ROOT / "logs/phase_b/B7_official_20261103_020241"
B15 = (
    ROOT / "experiments/B7_music/results"
    / "b15_natural_cover_audit/run_20261104_132107"
)
B17_PREFLIGHT = (
    ROOT / "experiments/B17_cross_domain"
    / "preflight_20261105_202713"
)

B12_MANIFEST = B12 / "b12_payload_manifest.csv"
B14_CONFIG = B14 / "b14_run_config.json"
B15_RECORDINGS = B15 / "b15_recording_results.csv"
B15_POSITIVES = B15 / "b15_positive_control_audit.csv"
B15_HASHES = B15 / "b15_input_bitstream_hashes.csv"

EXPECTED_B12_SHA = (
    "e993cd21001ff1d16467f8bab65ef5fb"
    "4dbaa2138a3b8aeb95cc0084b9e8c9b8"
)
EXPECTED_B14_SHA = (
    "4205c3d6864dea29653ec304bd838768"
    "0e01a82ae67917a0c0640a9765e756db"
)
EXPECTED_B14_CONFIG_SHA = (
    "64a2b78c27f985124d5aa9e65f4c860"
    "bcf897cf87f091aefdb0ae9f086fc6af0"
)

VERSIONS = ("1.5.2", "1.6.1")
TRAIN_SIZES = (32, 36)
PRIMARY_FEATURE_GROUP = "global_without_packet_geometry"
FEATURE_GROUPS = (
    "global_without_packet_geometry",
    "global_all",
    "stream_histogram",
    "stream_scalar",
    "packet_geometry",
)
MODELS = ("logistic_regression", "random_forest")
CAPACITY = 36
THRESHOLD = 0.5
SEED = 42
BOOTSTRAP_REPETITIONS = 1000

OUT_PARENT = (
    ROOT / "experiments/B17_cross_domain/results"
    / "b17_music_cross_domain"
)
OUT_PARENT.mkdir(parents=True, exist_ok=True)
OUT = OUT_PARENT / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
OUT.mkdir(parents=True)
MODEL_DIR = OUT / "models"
MODEL_DIR.mkdir()
REPORT = OUT / "b17_report.txt"


# ============================================================
# GENERAL UTILITIES
# ============================================================

def log(message):
    print(message, flush=True)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_hash(path, expected, label):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(
            f"{label} SHA256 mismatch\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )
    log(f"PASS: {label} SHA256")


def truth(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def normalize_class(value):
    value = str(value).strip().lower()
    if "cover" in value and "stego" not in value:
        return "cover"
    return "positive"


def resolve_music_file(value):
    p = Path(value).expanduser()
    candidates = (
        [p] if p.is_absolute()
        else [ROOT / p, B7 / p, B15 / p]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(value)


def check_inside(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        raise ValueError(f"Path escapes expected directory: {path}")


# ============================================================
# LOAD EXACT B14 IMPLEMENTATION
# ============================================================

def load_b14():
    check_hash(B14_SCRIPT, EXPECTED_B14_SHA, "B14 source script")
    spec = importlib.util.spec_from_file_location(
        "b14_feature_attribution", B14_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load B14 script: {B14_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.CAPACITY != CAPACITY:
        raise ValueError("B14 capacity mismatch")
    return module


# ============================================================
# GLOBAL FEATURE EXTRACTION
# ============================================================

def extract_global_features(b14, raw, packets):
    out = {}

    # Exactly the B14 global serialized-stream features.
    # This includes packet-length headers.
    b14.add_region_features(out, "g_stream", raw)

    lengths = np.asarray([len(p) for p in packets], dtype=float)
    if len(lengths) == 0:
        raise ValueError("No packets found during feature extraction")

    out["g_packet_count"] = float(len(packets))
    out["g_packet_length_mean"] = float(np.mean(lengths))
    out["g_packet_length_std"] = float(np.std(lengths))
    out["g_packet_length_min"] = float(np.min(lengths))
    out["g_packet_length_max"] = float(np.max(lengths))
    return out


# ============================================================
# COMMON VOICE TRAINING DATA
# ============================================================

def build_training_data(b14, manifest, shared_speakers, size):
    selected = [
        r for r in manifest
        if int(r["payload_size_bytes"]) == size
        and int(r["repetition"]) == 1
    ]

    if len(selected) != 200:
        raise ValueError(
            f"Expected 200 events for {size}B; found {len(selected)}"
        )

    selected = [
        r for r in selected
        if r["speaker_sha256"] not in shared_speakers
    ]

    if len(selected) != 192:
        raise ValueError(
            f"Expected 192 retained events for {size}B; found {len(selected)}"
        )

    samples = []
    manifest_rows = []
    events = set()

    log(f"\nBuilding Common Voice {size}B training data")

    for i, row in enumerate(selected, 1):
        enc = row["encoder"]
        recording = row["recording"]
        speaker = row["speaker_sha256"]
        frame = int(row["frame"])
        event = (enc, recording, frame)

        if event in events:
            raise ValueError(f"Duplicate training event: {event}")
        events.add(event)

        source = (
            B9 / "results/b9_full_encoding"
            / enc / "bitstreams" / f"{recording}.bin"
        )
        if not source.is_file():
            raise FileNotFoundError(source)
        check_inside(source, ROOT)

        if sha256(source) != row["source_bitstream_sha256"]:
            raise ValueError(f"Source hash mismatch: {recording}")

        modified = (B12 / row["modified_bitstream"]).resolve()
        check_inside(modified, B12)
        if not modified.is_file():
            raise FileNotFoundError(modified)

        if sha256(modified) != row["modified_bitstream_sha256"]:
            raise ValueError(f"Modified hash mismatch: {recording}")

        payload = bytes.fromhex(row["payload_hex"])
        if len(payload) != size:
            raise ValueError("Training payload length mismatch")
        if hashlib.sha256(payload).hexdigest() != row["payload_sha256"]:
            raise ValueError("Training payload SHA256 mismatch")

        cover_raw = source.read_bytes()
        stego_raw = modified.read_bytes()
        cover_packets = b14.read_packets(cover_raw, str(source))
        stego_packets = b14.read_packets(stego_raw, str(modified))

        if len(cover_packets) != len(stego_packets):
            raise ValueError("Packet count changed")
        if [len(p) for p in cover_packets] != [len(p) for p in stego_packets]:
            raise ValueError("Packet lengths changed")
        if frame >= len(cover_packets):
            raise ValueError("Training frame missing")
        if cover_packets[frame][-CAPACITY:] != bytes(CAPACITY):
            raise ValueError("Original reserved tail is not zero")

        expected_tail = bytes(CAPACITY - size) + payload
        if stego_packets[frame][-CAPACITY:] != expected_tail:
            raise ValueError("Training payload verification failed")
        if cover_packets[frame][:-CAPACITY] != stego_packets[frame][:-CAPACITY]:
            raise ValueError("Target prefix changed")

        for index, (a, b) in enumerate(zip(cover_packets, stego_packets)):
            if index != frame and a != b:
                raise ValueError(f"Unexpected modified packet: {recording}")

        cover_features = extract_global_features(b14, cover_raw, cover_packets)
        stego_features = extract_global_features(b14, stego_raw, stego_packets)
        if set(cover_features) != set(stego_features):
            raise ValueError("Feature schema mismatch")

        samples.append({
            "y": 0,
            "encoder": enc,
            "recording": recording,
            "speaker": speaker,
            "features": cover_features,
        })
        samples.append({
            "y": 1,
            "encoder": enc,
            "recording": recording,
            "speaker": speaker,
            "features": stego_features,
        })

        for label, digest in (
            ("cover", row["source_bitstream_sha256"]),
            ("stego", row["modified_bitstream_sha256"]),
        ):
            manifest_rows.append({
                "training_payload_size_bytes": size,
                "encoder": enc,
                "recording": recording,
                "speaker_sha256": speaker,
                "frame": frame,
                "class": label,
                "bitstream_sha256": digest,
            })

        if i % 40 == 0:
            log(f"Validated {i}/192 events")

    speakers = {r["speaker"] for r in samples}
    if len(speakers) != 192:
        raise ValueError("Training speaker count mismatch")

    version_counts = Counter(r["encoder"] for r in selected)
    if version_counts != {"1.5.2": 96, "1.6.1": 96}:
        raise ValueError(f"Unexpected training version counts: {version_counts}")

    if len(samples) != 384:
        raise ValueError("Expected 384 training samples")

    log(f"Training events: {len(events)}")
    log(f"Training samples: {len(samples)}")
    log(f"Unique speakers: {len(speakers)}")
    return samples, manifest_rows


# ============================================================
# GTZAN MUSIC TEST DATA
# ============================================================

def build_music_test_data(b14):
    recordings = read_csv(B15_RECORDINGS)
    positives = read_csv(B15_POSITIVES)
    hashes = read_csv(B15_HASHES)

    if len(recordings) != 2018:
        raise ValueError("B15 recording count mismatch")
    if len(positives) != 20:
        raise ValueError("B15 positive-control count mismatch")
    if len(hashes) != 2018:
        raise ValueError("B15 input hash count mismatch")

    positive_map = {
        (r["version"], r["recording"]): r for r in positives
    }
    required_flags = (
        "detected_anywhere",
        "payload_recovered",
        "pcm_identical",
        "packet_lengths_preserved",
        "independent_payload_correct",
        "other_packets_unchanged",
        "target_prefix_unchanged",
    )

    for row in positives:
        for flag in required_flags:
            if not truth(row[flag]):
                raise ValueError(
                    f"Positive-control failure: {row['recording']} {flag}"
                )

    hash_map = {}
    for row in hashes:
        key = (
            row["version"],
            normalize_class(row["class"]),
            row["recording"],
        )
        if key in hash_map:
            raise ValueError(f"Duplicate music hash: {key}")
        hash_map[key] = row["sha256"]

    if len(hash_map) != 2018:
        raise ValueError("Music hash inventory mismatch")

    test_samples = []
    seen = set()
    log("\nBuilding GTZAN music test features")

    for i, row in enumerate(recordings, 1):
        version = row["version"]
        recording = row["recording"]
        cls = normalize_class(row["class"])
        key = (version, cls, recording)

        if key in seen:
            raise ValueError(f"Duplicate music test sample: {key}")
        seen.add(key)

        path = resolve_music_file(row["file"])
        expected = hash_map.get(key)
        if expected is None:
            raise ValueError(f"Missing music hash: {key}")

        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Music hash mismatch: {key}")

        raw = path.read_bytes()
        packets = b14.read_packets(raw, str(path))

        if cls == "positive":
            audit = positive_map.get((version, recording))
            if audit is None:
                raise ValueError(f"Positive control missing from B15 audit: {key}")
            frame = int(audit["expected_frame_from_manifest"])
            if frame < 0 or frame >= len(packets):
                raise ValueError(f"Positive target frame missing: {key}")
            if len(packets[frame]) <= CAPACITY:
                raise ValueError(f"Positive target packet too short: {key}")

        features = extract_global_features(b14, raw, packets)
        test_samples.append({
            "y": 1 if cls == "positive" else 0,
            "version": version,
            "recording": recording,
            "class": cls,
            "sha256": actual,
            "features": features,
        })

        if i % 250 == 0:
            log(f"Processed {i}/2018 music files")

    by_version = {
        version: [r for r in test_samples if r["version"] == version]
        for version in VERSIONS
    }

    for version, rows in by_version.items():
        counts = Counter(r["class"] for r in rows)
        if counts != {"cover": 999, "positive": 10}:
            raise ValueError(f"Unexpected {version} class distribution: {counts}")

        pairs = defaultdict(set)
        for r in rows:
            pairs[r["recording"]].add(r["class"])
        matched = sum(
            {"cover", "positive"}.issubset(classes)
            for classes in pairs.values()
        )

        if matched != 10:
            raise ValueError(
                f"{version}: expected 10 matched controls, got {matched}"
            )
        if len(pairs) != 999:
            raise ValueError(f"{version}: unexpected unique recording count")

        log(
            f"{version}: {len(rows)} samples; 999 covers; "
            f"10 positives; {matched} matched pairs"
        )

    return by_version


# ============================================================
# CONFIDENCE INTERVALS
# ============================================================

def wilson_interval(successes, total, z=1.959963984540054):
    if total == 0:
        return (float("nan"), float("nan"))
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = (
        z * np.sqrt(
            p * (1 - p) / total
            + z * z / (4 * total * total)
        ) / denominator
    )
    return (
        max(0.0, center - margin),
        min(1.0, center + margin),
    )


def paired_cluster_auc_ci(rows, scores, seed, repetitions=1000):
    y = np.asarray([r["y"] for r in rows], dtype=int)
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row["recording"]].append(i)

    paired = []
    clean_only = []
    for recording, indices in groups.items():
        labels = sorted(y[indices].tolist())
        if labels == [0, 1]:
            paired.append(recording)
        elif labels == [0]:
            clean_only.append(recording)
        else:
            raise ValueError(f"Unexpected recording group: {recording}")

    if len(paired) != 10 or len(clean_only) != 989:
        raise ValueError(
            "Unexpected paired bootstrap group structure: "
            f"paired={len(paired)}, clean_only={len(clean_only)}"
        )

    rng = np.random.default_rng(seed)
    values = []
    for _ in range(repetitions):
        sampled = list(rng.choice(paired, size=len(paired), replace=True))
        sampled += list(
            rng.choice(clean_only, size=len(clean_only), replace=True)
        )
        indices = []
        for recording in sampled:
            indices.extend(groups[recording])
        values.append(roc_auc_score(y[indices], scores[indices]))

    return tuple(np.percentile(values, [2.5, 97.5]))


# ============================================================
# EVALUATION
# ============================================================

def evaluate_model(
    model,
    train_samples,
    test_rows,
    feature_columns,
    model_name,
    feature_group,
    train_size,
    test_version,
    bootstrap_seed,
):
    X_test = np.asarray(
        [[row["features"][col] for col in feature_columns] for row in test_rows],
        dtype=float,
    )
    y_test = np.asarray([r["y"] for r in test_rows], dtype=int)
    scores = model.predict_proba(X_test)[:, 1]
    predictions = (scores >= THRESHOLD).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_test, predictions, labels=[0, 1]
    ).ravel()
    auc = roc_auc_score(y_test, scores)
    auc_low, auc_high = paired_cluster_auc_ci(
        test_rows, scores, bootstrap_seed, BOOTSTRAP_REPETITIONS
    )

    tpr = tp / (tp + fn)
    fpr = fp / (fp + tn)
    tpr_low, tpr_high = wilson_interval(tp, tp + fn)
    fpr_low, fpr_high = wilson_interval(fp, fp + tn)

    score_lookup = {
        (r["recording"], r["class"]): scores[i]
        for i, r in enumerate(test_rows)
    }
    positive_recordings = [
        r["recording"] for r in test_rows if r["class"] == "positive"
    ]
    paired_deltas = [
        score_lookup[(recording, "positive")]
        - score_lookup[(recording, "cover")]
        for recording in positive_recordings
    ]

    summary = {
        "training_payload_size_bytes": train_size,
        "test_encoder": test_version,
        "feature_group": feature_group,
        "model": model_name,
        "n_features": len(feature_columns),
        "n_train_events": 192,
        "n_train_samples": len(train_samples),
        "n_test_samples": len(test_rows),
        "n_test_covers": int((y_test == 0).sum()),
        "n_test_positives": int((y_test == 1).sum()),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "tpr": float(tpr),
        "tpr_ci_low": float(tpr_low),
        "tpr_ci_high": float(tpr_high),
        "specificity": float(1 - fpr),
        "fpr": float(fpr),
        "fpr_ci_low": float(fpr_low),
        "fpr_ci_high": float(fpr_high),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(auc),
        "roc_auc_ci_low": float(auc_low),
        "roc_auc_ci_high": float(auc_high),
        "average_precision": float(average_precision_score(y_test, scores)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "decision_threshold": THRESHOLD,
        "paired_positive_higher_fraction": float(
            np.mean(np.asarray(paired_deltas) > 0)
        ),
        "paired_mean_score_delta": float(np.mean(paired_deltas)),
        "paired_median_score_delta": float(np.median(paired_deltas)),
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
    }

    prediction_rows = []
    for i, row in enumerate(test_rows):
        prediction_rows.append({
            "training_payload_size_bytes": train_size,
            "test_encoder": test_version,
            "feature_group": feature_group,
            "model": model_name,
            "recording": row["recording"],
            "class": row["class"],
            "y_true": int(y_test[i]),
            "y_score": float(scores[i]),
            "y_pred": int(predictions[i]),
            "sha256": row["sha256"],
            "threshold": THRESHOLD,
        })

    return summary, prediction_rows, scores


# ============================================================
# MAIN
# ============================================================

def main():
    report = []

    def note(message):
        report.append(str(message))
        log(message)

    note("========== B17 MUSIC CROSS-DOMAIN EXPERIMENT ==========")
    note(f"Project: {ROOT}")
    note(f"Output: {OUT}")

    # Input integrity
    note("\n========== INPUT INTEGRITY ==========")
    check_hash(B12_MANIFEST, EXPECTED_B12_SHA, "B12 payload manifest")
    check_hash(B14_CONFIG, EXPECTED_B14_CONFIG_SHA, "B14 configuration")

    preflight_report = B17_PREFLIGHT / "b17_music_input_audit.txt"
    if not preflight_report.is_file():
        raise FileNotFoundError(preflight_report)
    if "B17 MUSIC INPUT AUDIT: PASS" not in preflight_report.read_text(
        encoding="utf-8"
    ):
        raise ValueError("B17 preflight did not pass")

    b14 = load_b14()
    b14_config = json.loads(B14_CONFIG.read_text(encoding="utf-8"))
    if b14_config["manifest_sha256"] != EXPECTED_B12_SHA:
        raise ValueError("B14/B12 manifest mismatch")
    note("B17 preflight: PASS")

    # Shared speaker exclusion
    shared_rows = read_csv(B16_SHARED)
    shared_speakers = {r["speaker_sha256"] for r in shared_rows}
    if len(shared_speakers) != 4:
        raise ValueError(f"Expected 4 shared speakers, found {len(shared_speakers)}")
    note(f"Shared speaker groups excluded: {len(shared_speakers)}")

    # Feature group verification.
    # B14's define_feature_groups() validates the FULL B14 schema, including
    # target-packet/tail/prefix groups. B17 intentionally trains and tests
    # using global features only, so a global-only probe would make those
    # unused B14 groups appear empty and trigger a false failure.
    #
    # Use B14's own complete extractor on a synthetic packet solely to
    # discover/validate the canonical feature-group schema. These synthetic
    # values are NOT added to the training or music datasets.
    probe_packet = b"test-feature-packet" + bytes(CAPACITY + 1)
    feature_probe = b14.extract_features(
        b"test-feature-stream", [probe_packet], 0
    )
    groups = b14.define_feature_groups(sorted(feature_probe.keys()))
    for name in FEATURE_GROUPS:
        if name not in groups:
            raise ValueError(f"Missing B14 feature group: {name}")
        expected = b14_config["feature_group_sizes"][name]
        if len(groups[name]) != expected:
            raise ValueError(f"Feature count mismatch: {name}")
        note(f"Feature group {name}: {len(groups[name])}")

    # Common Voice training
    manifest = read_csv(B12_MANIFEST)
    if len(manifest) != 3600:
        raise ValueError("B12 manifest row count mismatch")

    all_training = {}
    training_manifest = []
    for size in TRAIN_SIZES:
        samples, manifest_rows = build_training_data(
            b14, manifest, shared_speakers, size
        )
        all_training[size] = samples
        training_manifest.extend(manifest_rows)

    write_csv(OUT / "b17_training_manifest.csv", training_manifest)

    # Natural music testing
    music = build_music_test_data(b14)

    # Fit and evaluate models
    note("\n========== MODEL TRAINING AND TESTING ==========")
    metrics = []
    predictions = []
    primary_curves = []
    evaluation_number = 0

    for train_size in TRAIN_SIZES:
        train_samples = all_training[train_size]
        y_train = np.asarray([r["y"] for r in train_samples], dtype=int)
        if Counter(y_train) != {0: 192, 1: 192}:
            raise ValueError("Training class balance mismatch")

        for group_name in FEATURE_GROUPS:
            columns = groups[group_name]
            X_train = np.asarray(
                [[r["features"][col] for col in columns] for r in train_samples],
                dtype=float,
            )
            if not np.isfinite(X_train).all():
                raise ValueError("Non-finite training features")

            for model_name in MODELS:
                note(f"\nTraining {model_name} | {train_size}B | {group_name}")
                model = b14.make_model(model_name, SEED)
                model.fit(X_train, y_train)

                model_path = MODEL_DIR / (
                    f"{model_name}_{group_name}_{train_size}B.joblib"
                )
                joblib.dump(model, model_path)

                for version in VERSIONS:
                    evaluation_number += 1
                    test_rows = music[version]
                    result, prediction_rows, scores = evaluate_model(
                        model,
                        train_samples,
                        test_rows,
                        columns,
                        model_name,
                        group_name,
                        train_size,
                        version,
                        SEED + evaluation_number,
                    )
                    metrics.append(result)
                    predictions.extend(prediction_rows)
                    note(
                        f"{version}: AUC={result['roc_auc']:.4f} "
                        f"[{result['roc_auc_ci_low']:.4f}, "
                        f"{result['roc_auc_ci_high']:.4f}] "
                        f"TPR={result['tpr']:.3f} FPR={result['fpr']:.4f}"
                    )

                    if train_size == 36 and group_name == PRIMARY_FEATURE_GROUP:
                        y_test = np.asarray([r["y"] for r in test_rows])
                        curve_fpr, curve_tpr, _ = roc_curve(y_test, scores)
                        primary_curves.append({
                            "version": version,
                            "model": model_name,
                            "fpr": curve_fpr,
                            "tpr": curve_tpr,
                            "auc": result["roc_auc"],
                        })

    # Save results
    write_csv(OUT / "b17_cross_domain_metrics.csv", metrics)
    write_csv(OUT / "b17_music_predictions.csv", predictions)

    # Primary ROC plot
    plt.figure(figsize=(9, 7))
    for curve in primary_curves:
        plt.plot(
            curve["fpr"],
            curve["tpr"],
            label=(
                f"{curve['version']} {curve['model']} "
                f"AUC={curve['auc']:.3f}"
            ),
        )
    plt.plot([0, 1], [0, 1], linestyle="--", label="Random baseline")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("B17: Common Voice to GTZAN Cross-Domain Detection")
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(OUT / "b17_primary_roc.png", dpi=300)
    plt.close()

    # Configuration
    config = {
        "experiment": "B17",
        "design": "Common Voice to GTZAN cross-domain transfer",
        "training_domain": "Common Voice",
        "testing_domain": "GTZAN natural music",
        "training_payload_sizes": list(TRAIN_SIZES),
        "primary_training_size": 36,
        "music_payload_size_bytes": 35,
        "training_events_per_size": 192,
        "training_samples_per_size": 384,
        "excluded_shared_speaker_groups": 4,
        "test_samples_per_encoder": 1009,
        "test_covers_per_encoder": 999,
        "test_positives_per_encoder": 10,
        "models": list(MODELS),
        "feature_groups": list(FEATURE_GROUPS),
        "primary_feature_group": PRIMARY_FEATURE_GROUP,
        "target_location_features_used": False,
        "music_threshold_tuning": False,
        "decision_threshold": THRESHOLD,
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "bootstrap_unit": "recording_id_with_matched_pairs",
        "seed": SEED,
        "read_only_source_data": True,
        "b14_source_sha256": sha256(B14_SCRIPT),
        "b12_manifest_sha256": sha256(B12_MANIFEST),
        "b14_config_sha256": sha256(B14_CONFIG),
    }
    (OUT / "b17_run_config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    # Final report
    note("\n========== PRIMARY RESULTS: 36B TRAINING ==========")
    primary_results = [
        r for r in metrics
        if r["training_payload_size_bytes"] == 36
        and r["feature_group"] == PRIMARY_FEATURE_GROUP
    ]
    for r in primary_results:
        note(
            f"{r['test_encoder']} | {r['model']} | "
            f"AUC={r['roc_auc']:.4f} | "
            f"95% CI=[{r['roc_auc_ci_low']:.4f}, "
            f"{r['roc_auc_ci_high']:.4f}] | "
            f"TPR={r['tpr']:.3f} | FPR={r['fpr']:.4f} | "
            f"Balanced accuracy={r['balanced_accuracy']:.4f}"
        )

    note("\n========== INTERPRETATION LIMITS ==========")
    note("- Music was never used to train or tune the models.")
    note("- Target-tail and target-packet features were excluded.")
    note("- The decision threshold remained fixed at 0.5.")
    note("- The primary model was trained at 36B.")
    note("- A 32B training condition provides size sensitivity.")
    note("- Music positive controls contain 35B payloads.")
    note("- Only 10 positive music recordings exist per encoder.")
    note("- AUC confidence intervals use recording-level resampling.")
    note("- Results do not establish universal cross-domain detection.")
    note("\nB17 MUSIC CROSS-DOMAIN EXPERIMENT: COMPLETE")

    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    # Checksums
    checksum_file = OUT / "b17_checksums.sha256"
    checksum_lines = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path == checksum_file:
            continue
        digest = sha256(path)
        checksum_lines.append(f"{digest}  {path.relative_to(OUT)}")
    checksum_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    log("\n========== B17 FINAL OUTPUT ==========")
    log(f"Results: {OUT}")
    log(f"Metrics: {OUT / 'b17_cross_domain_metrics.csv'}")
    log(f"Predictions: {OUT / 'b17_music_predictions.csv'}")
    log(f"ROC plot: {OUT / 'b17_primary_roc.png'}")
    log(f"Report: {REPORT}")
    log(f"Checksums: {checksum_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"\nB17 FAILED: {exc}")
        raise
