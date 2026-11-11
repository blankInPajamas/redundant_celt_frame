#!/usr/bin/env python3

import json
import hashlib
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path.home() / "research/redundant_celt_frame_steganography"

B16 = ROOT / (
    "experiments/B9_common_voice/results/"
    "b16_cross_version_transfer/run_20261105_163028"
)

OUT = ROOT / (
    "experiments/B17_cross_domain/"
    "preflight_20261105_202713"
)

def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()

def main():

    config_path = B16 / "b16_run_config.json"

    if not config_path.is_file():
        raise FileNotFoundError(config_path)

    with config_path.open() as f:
        config = json.load(f)

    b12_manifest = (
        Path(config["b12_run"]) / "b12_payload_manifest.csv"
    )

    b14_script = Path(config["b14_script"])
    b14_config = Path(config["b14_config"])

    checks = [
        ("B12 manifest", b12_manifest, "b12_manifest_sha256"),
        ("B14 source script", b14_script, "b14_script_sha256"),
        ("B14 configuration", b14_config, "b14_config_sha256"),
    ]

    lines = [
        "========== B17 CROSS-EXPERIMENT HASH AUDIT ==========",
        f"Date: {datetime.now().isoformat()}",
        f"Project: {ROOT}",
        "",
    ]

    failures = []

    for label, path, key in checks:

        print(f"\nChecking: {label}")
        print(f"Path: {path}")

        if not path.is_file():
            failures.append(f"MISSING: {label}")
            print("FAIL: File missing")
            continue

        actual = sha256(path)
        expected = config[key]

        passed = actual == expected

        status = "PASS" if passed else "FAIL"

        print(f"Expected: {expected}")
        print(f"Actual:   {actual}")
        print(f"Status:   {status}")

        lines.extend([
            label,
            f"Path: {path}",
            f"Expected: {expected}",
            f"Actual: {actual}",
            f"Status: {status}",
            "",
        ])

        if not passed:
            failures.append(label)

    print("\n========== FINAL RESULT ==========")

    if failures:
        print("B17 HASH AUDIT: FAIL")

        for item in failures:
            print("-", item)

        lines.append("B17 HASH AUDIT: FAIL")
        lines.extend(failures)

    else:
        print("B17 HASH AUDIT: PASS")
        print("All three cross-experiment hashes match.")

        lines.append("B17 HASH AUDIT: PASS")

    OUT.mkdir(parents=True, exist_ok=True)

    report = OUT / "b17_cross_experiment_hash_audit.txt"
    report.write_text("\n".join(lines) + "\n")

    print(f"\nReport saved: {report}")

    if failures:
        sys.exit(1)

if __name__ == "__main__":
    main()
