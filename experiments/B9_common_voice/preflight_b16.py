import csv
import json
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

B12 = ROOT / (
    "experiments/B9_common_voice/results/"
    "b12_payload_reliability/run_20261104_020705"
)

B13_PARENT = ROOT / (
    "experiments/B9_common_voice/results/b13_steganalysis"
)

B14 = ROOT / (
    "experiments/B9_common_voice/results/"
    "b14_feature_attribution/run_20261104_110548"
)

OUT = (
    ROOT / "experiments/B9_common_voice/results/"
    "b16_cross_version_transfer"
)

OUT.mkdir(parents=True, exist_ok=True)

PREFLIGHT = OUT / (
    "preflight_" + datetime.now().strftime("%Y%m%d_%H%M%S")
)

PREFLIGHT.mkdir()

def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames, rows

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def show_file(path, report, inventory):

    if not path.exists():
        report.append(f"MISSING: {path}")
        return

    size = path.stat().st_size

    if path.suffix == ".csv":
        columns, rows = read_csv(path)

        sample = rows[0] if rows else {}

        report.append(f"\nFILE: {path}")
        report.append(f"Rows: {len(rows)}")
        report.append(f"Columns: {columns}")
        report.append(f"Sample: {sample}")

        inventory.append({
            "file": str(path),
            "exists": True,
            "rows": len(rows),
            "size_bytes": size,
            "columns": json.dumps(columns),
            "sha256": sha256(path)
        })

    else:
        report.append(f"\nFILE: {path}")
        report.append(f"Size: {size}")

        if path.suffix == ".json":
            report.append(
                json.dumps(
                    json.loads(path.read_text()),
                    indent=2
                )
            )

        inventory.append({
            "file": str(path),
            "exists": True,
            "rows": "",
            "size_bytes": size,
            "columns": "",
            "sha256": sha256(path)
        })

def main():

    report = []
    inventory = []

    b13_candidates = sorted(
        B13_PARENT.glob("run_*"),
        key=lambda p: p.stat().st_mtime
    )

    if not b13_candidates:
        raise RuntimeError("No B13 run directory found")

    B13 = b13_candidates[-1]

    report.append("========== B16 INPUT PREFLIGHT ==========")
    report.append(f"Project: {ROOT}")
    report.append(f"B12: {B12}")
    report.append(f"B13: {B13}")
    report.append(f"B14: {B14}")

    if not B12.exists() or not B14.exists():
        raise RuntimeError("B12 or B14 directory missing")

    files = [
        B12 / "b12_payload_manifest.csv",
        B13 / "b13_feature_summary.csv",
        B13 / "b13_oof_predictions.csv",
        B13 / "b13_ml_metrics.csv",
        B14 / "b14_paired_feature_effects.csv",
        B14 / "b14_oof_predictions.csv",
        B14 / "b14_feature_group_metrics.csv",
        B14 / "b14_permutation_importance_summary.csv",
        B14 / "b14_permutation_importance_by_fold.csv",
        B14 / "b14_run_config.json",
        B14 / "b14_report.txt"
    ]

    for path in files:
        show_file(path, report, inventory)

    # Speaker and event overlap audit

    manifest = read_csv(
        B12 / "b12_payload_manifest.csv"
    )[1]

    events = defaultdict(dict)
    speakers = defaultdict(set)

    for r in manifest:

        version = r["encoder"]
        recording = r["recording"]
        speaker = r["speaker_sha256"]
        frame = r["frame"]

        speakers[version].add(speaker)

        events[version][(recording, frame)] = speaker

    shared_speakers = (
        speakers["1.5.2"] & speakers["1.6.1"]
    )

    shared_recordings = (
        {r for r, f in events["1.5.2"]}
        &
        {r for r, f in events["1.6.1"]}
    )

    report.append("\n========== SPEAKER OVERLAP ==========")

    report.append(
        f"1.5.2 events: {len(events['1.5.2'])}"
    )

    report.append(
        f"1.6.1 events: {len(events['1.6.1'])}"
    )

    report.append(
        f"1.5.2 speaker groups: {len(speakers['1.5.2'])}"
    )

    report.append(
        f"1.6.1 speaker groups: {len(speakers['1.6.1'])}"
    )

    report.append(
        f"Shared speakers: {len(shared_speakers)}"
    )

    report.append(
        f"Shared recording IDs: {len(shared_recordings)}"
    )

    for version in ["1.5.2", "1.6.1"]:

        retained = sum(
            speaker not in shared_speakers
            for speaker in events[version].values()
        )

        excluded = len(events[version]) - retained

        report.append(
            f"{version}: retained={retained}; "
            f"excluded={excluded}"
        )

    overlap_rows = []

    for speaker in sorted(shared_speakers):

        overlap_rows.append({
            "speaker_sha256": speaker,
            "present_1_5_2": speaker in speakers["1.5.2"],
            "present_1_6_1": speaker in speakers["1.6.1"]
        })

    with (PREFLIGHT / "b16_shared_speakers.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "speaker_sha256",
                "present_1_5_2",
                "present_1_6_1"
            ]
        )

        writer.writeheader()
        writer.writerows(overlap_rows)

    # Find B14 scripts

    report.append("\n========== B14 SOURCE SCRIPTS ==========")

    scripts = sorted(
        ROOT.glob("experiments/B9_common_voice/**/*b14*.py")
    )

    for script in scripts:

        report.append(str(script))
        report.append(f"SHA256: {sha256(script)}")

    if not scripts:
        report.append("No B14 Python script found")

    # B13 source script

    b13_script = (
        ROOT / "experiments/B9_common_voice/"
        "run_b13_steganalysis.py"
    )

    if b13_script.exists():

        report.append("\n========== B13 SOURCE SCRIPT ==========")
        report.append(str(b13_script))
        report.append(f"SHA256: {sha256(b13_script)}")

    # Write inventory

    with (PREFLIGHT / "b16_input_inventory.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file", "exists", "rows",
                "size_bytes", "columns", "sha256"
            ]
        )

        writer.writeheader()
        writer.writerows(inventory)

    report.append("\n========== PREFLIGHT COMPLETE ==========")
    report.append(f"Output: {PREFLIGHT}")
    report.append("Source data modified: NO")

    report_text = "\n".join(report) + "\n"

    (PREFLIGHT / "b16_preflight_report.txt").write_text(
        report_text,
        encoding="utf-8"
    )

    with (PREFLIGHT / "b16_preflight_checksums.sha256").open(
        "w"
    ) as f:

        for p in sorted(PREFLIGHT.iterdir()):

            if p.is_file() and p.name != "b16_preflight_checksums.sha256":

                f.write(
                    f"{sha256(p)}  {p.name}\n"
                )

    print(report_text)


if __name__ == "__main__":
    main()
