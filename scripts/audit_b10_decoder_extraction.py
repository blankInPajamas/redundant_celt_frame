#!/usr/bin/env python3
"""
Independent B10 decoder-side payload extraction audit.

Run from the repository root:
    python3 scripts/audit_b10_decoder_extraction.py

Or specify a run directory:
    python3 scripts/audit_b10_decoder_extraction.py --run-dir \
      experiments/B9_common_voice/results/b10_decoder_extraction_100speaker/run_YYYYMMDD_HHMMSS

The script re-parses the raw decoder logs. It does not rerun any decoder.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


VERSIONS = ("1.5.2", "1.6.1")
REQUIRED_COLUMNS = {
    "encoder", "decoder", "recording", "frame",
    "expected_payload_sha256", "decode_return_code",
    "pcm_bytes", "pcm_sha256",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def row_key(row: dict) -> tuple[str, str, str, int]:
    return (
        row["encoder"],
        row["decoder"],
        row["recording"],
        int(row["frame"]),
    )


def latest_run_dir(root: Path) -> Path:
    candidates = sorted(
        p for p in root.glob("run_*")
        if p.is_dir()
        and (p / "b10_decoder_extraction_results.csv").is_file()
        and all(
            (p / f"opus_{v}_candidates.log").is_file()
            for v in VERSIONS
        )
    )
    if not candidates:
        raise FileNotFoundError(
            f"No complete run_* directory found under {root}"
        )
    return candidates[-1]


def parse_decoder_log(path: Path, expected_decoder: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Each decoder invocation is separated by a line of '=' characters.
    blocks = re.split(r"(?m)^={10,}\s*$", text)
    parsed = {}

    header_re = re.compile(
        r"(?m)^encoder=(\S+)\s+decoder=(\S+)\s+"
        r"recording=(\S+)\s+frame=(\d+)\s*$"
    )
    status_re = re.compile(
        r"(?m)^return_code=(-?\d+)\s+pcm_bytes=(\d+)\s*$"
    )
    expected_re = re.compile(r"(?m)^expected_sha256=([0-9a-fA-F]{64})\s*$")
    tail_re = re.compile(r"tail36=([0-9a-fA-F]{72})")

    for block in blocks:
        header = header_re.search(block)
        if not header:
            continue

        encoder, decoder, recording, frame = header.groups()
        if decoder != expected_decoder:
            raise ValueError(
                f"{path.name}: expected decoder {expected_decoder}, "
                f"found {decoder} for {recording}"
            )

        status = status_re.search(block)
        expected = expected_re.search(block)
        if not status or not expected:
            raise ValueError(
                f"{path.name}: incomplete log block for {recording}, frame {frame}"
            )

        tails = [x.lower() for x in tail_re.findall(block)]
        key = (encoder, decoder, recording, int(frame))

        if key in parsed:
            raise ValueError(f"Duplicate decoder log block: {key}")

        parsed[key] = {
            "return_code": int(status.group(1)),
            "pcm_bytes": int(status.group(2)),
            "log_expected_sha256": expected.group(1).lower(),
            "tails": tails,
        }

    return parsed


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Refusing to write an empty corrected CSV")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="B10 run directory; defaults to the latest complete run_* directory",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    results_root = (
        repo_root
        / "experiments/B9_common_voice/results/b10_decoder_extraction_100speaker"
    )
    run_dir = args.run_dir.resolve() if args.run_dir else latest_run_dir(results_root)

    source_csv = run_dir / "b10_decoder_extraction_results.csv"
    if not source_csv.is_file():
        raise FileNotFoundError(source_csv)

    with source_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        source_rows = list(reader)
        source_fields = reader.fieldnames or []

    missing = REQUIRED_COLUMNS.difference(source_fields)
    if missing:
        raise ValueError(f"Input CSV is missing required columns: {sorted(missing)}")

    log_index = {}
    for version in VERSIONS:
        log_path = run_dir / f"opus_{version}_candidates.log"
        if not log_path.is_file():
            raise FileNotFoundError(log_path)
        log_index.update(parse_decoder_log(log_path, version))

    csv_index = {}
    for row in source_rows:
        key = row_key(row)
        if key in csv_index:
            raise ValueError(f"Duplicate CSV row: {key}")
        csv_index[key] = row

    missing_logs = set(csv_index) - set(log_index)
    extra_logs = set(log_index) - set(csv_index)
    if missing_logs or extra_logs:
        raise ValueError(
            f"CSV/log key mismatch: missing log blocks={len(missing_logs)}, "
            f"extra log blocks={len(extra_logs)}. "
            f"First missing={next(iter(missing_logs), None)}; "
            f"first extra={next(iter(extra_logs), None)}"
        )

    corrected = []
    for key, source in csv_index.items():
        log = log_index[key]
        expected_hash = source["expected_payload_sha256"].lower()

        if log["log_expected_sha256"] != expected_hash:
            raise ValueError(
                f"Expected SHA256 differs between CSV and log for {key}"
            )

        matching_tails = []
        for tail_hex in log["tails"]:
            tail_bytes = bytes.fromhex(tail_hex)
            if sha256_bytes(tail_bytes) == expected_hash:
                matching_tails.append(tail_hex)

        extracted_hex = matching_tails[0] if len(matching_tails) == 1 else ""
        extracted_hash = (
            sha256_bytes(bytes.fromhex(extracted_hex))
            if extracted_hex else ""
        )

        rc_ok = log["return_code"] == 0
        pcm_ok = log["pcm_bytes"] > 0
        extraction_ok = (
            rc_ok
            and pcm_ok
            and len(matching_tails) == 1
            and extracted_hash == expected_hash
        )

        row = dict(source)
        row["decode_return_code"] = str(log["return_code"])
        row["pcm_bytes"] = str(log["pcm_bytes"])
        row["candidate_count"] = str(len(log["tails"]))
        row["candidate_match_count"] = str(len(matching_tails))
        row["candidate_tail36_hex"] = ";".join(log["tails"])
        row["extracted_payload_hex"] = extracted_hex
        row["extracted_payload_sha256"] = extracted_hash
        row["extraction_exact"] = str(bool(extraction_ok))
        row["status"] = "PASS" if extraction_ok else "REVIEW_REQUIRED"
        corrected.append(row)

    corrected.sort(
        key=lambda r: (
            r["encoder"], r["recording"], int(r["frame"]), r["decoder"]
        )
    )

    out_csv = run_dir / "b10_decoder_extraction_results_CORRECTED.csv"
    out_report = run_dir / "b10_decoder_extraction_report_CORRECTED.txt"
    out_hashes = run_dir / "b10_corrected_audit.sha256"
    write_csv(out_csv, corrected)

    status_counts = Counter(r["status"] for r in corrected)
    candidate_counts = Counter(int(r["candidate_count"]) for r in corrected)
    match_counts = Counter(int(r["candidate_match_count"]) for r in corrected)
    combo_counts = Counter(
        (r["encoder"], r["decoder"], r["status"]) for r in corrected
    )

    # Compare decoder-version PCM hashes only as a separate compatibility
    # observation. It is not a payload-extraction pass criterion.
    paired = defaultdict(dict)
    for row in corrected:
        key = (row["encoder"], row["recording"], int(row["frame"]))
        paired[key][row["decoder"]] = row

    pcm_pairs = [
        pair for pair in paired.values()
        if "1.5.2" in pair and "1.6.1" in pair
    ]
    pcm_hash_identical = sum(
        p["1.5.2"]["pcm_sha256"] == p["1.6.1"]["pcm_sha256"]
        for p in pcm_pairs
    )
    pcm_size_identical = sum(
        int(p["1.5.2"]["pcm_bytes"]) == int(p["1.6.1"]["pcm_bytes"])
        for p in pcm_pairs
    )

    with out_report.open("w", encoding="utf-8") as f:
        f.write("========== B10 DECODER EXTRACTION REPORT (CORRECTED AUDIT) ==========\n")
        f.write(f"Run directory: {run_dir}\n")
        f.write("Method: re-parse raw tail36 fields and verify each candidate against the manifest SHA256.\n")
        f.write("No decoder was rerun by this audit script.\n\n")
        f.write(f"CSV records: {len(source_rows)}\n")
        f.write(f"Decoder log blocks: {len(log_index)}\n")
        f.write(f"Unique encoder/recording/frame events: {len(paired)}\n\n")

        f.write("========== CROSS-VERSION EXTRACTION ==========\n")
        for enc in VERSIONS:
            for dec in VERSIONS:
                total = sum(
                    1 for r in corrected
                    if r["encoder"] == enc and r["decoder"] == dec
                )
                passed = combo_counts[(enc, dec, "PASS")]
                f.write(f"Encoder {enc} / Decoder {dec}: {passed}/{total}\n")

        f.write("\n========== EXTRACTION AUDIT ==========\n")
        f.write(f"PASS: {status_counts['PASS']}\n")
        f.write(f"REVIEW_REQUIRED: {status_counts['REVIEW_REQUIRED']}\n")
        f.write(f"Exact payload recoveries: {status_counts['PASS']}/{len(corrected)}\n")
        f.write(
            "Decoder return code 0: "
            f"{sum(int(r['decode_return_code']) == 0 for r in corrected)}/{len(corrected)}\n"
        )
        f.write(
            "Non-empty PCM outputs: "
            f"{sum(int(r['pcm_bytes']) > 0 for r in corrected)}/{len(corrected)}\n"
        )
        f.write(f"Candidate-count distribution: {dict(sorted(candidate_counts.items()))}\n")
        f.write(f"Expected-SHA256 match-count distribution: {dict(sorted(match_counts.items()))}\n")

        f.write("\n========== SEPARATE PCM VERSION COMPARISON ==========\n")
        f.write(f"Paired encoder/recording/frame events: {len(pcm_pairs)}\n")
        f.write(f"PCM SHA256 identical across decoder versions: {pcm_hash_identical}/{len(pcm_pairs)}\n")
        f.write(f"PCM byte lengths identical across decoder versions: {pcm_size_identical}/{len(pcm_pairs)}\n")
        f.write("This is a cross-decoder-version comparison, not the baseline-versus-modified PCM-preservation test.\n")
        f.write("Do not interpret cross-version PCM hash differences as payload-extraction failures.\n")

        f.write("\n========== ORIGINAL PARSER FAILURE ==========\n")
        f.write("The previous parser required a pipe or end-of-string immediately after tail36's 72 hex characters.\n")
        f.write("The decoder log places a newline and the 'Decoded ... frames' message after the hex field.\n")
        f.write("The old parser therefore produced false NO_MATCH results despite valid tail36 data.\n")
        f.write("This audit uses: re.findall(r'tail36=([0-9a-fA-F]{72})', block)\n")

        f.write("\nB10 PAYLOAD EXTRACTION AUDIT: ")
        f.write("PASS\n" if status_counts["PASS"] == len(corrected) else "REVIEW REQUIRED\n")
        f.write(f"Corrected CSV: {out_csv.name}\n")

    out_hashes.write_text(
        f"{sha256_bytes(out_csv.read_bytes())}  {out_csv.name}\n"
        f"{sha256_bytes(out_report.read_bytes())}  {out_report.name}\n",
        encoding="utf-8",
    )

    print("========== B10 CORRECTED AUDIT ==========")
    print(f"Run directory: {run_dir}")
    print(f"Decoder runs: {len(corrected)}")
    print(f"Exact payload recoveries: {status_counts['PASS']}/{len(corrected)}")
    print(f"Review required: {status_counts['REVIEW_REQUIRED']}")
    print(f"Cross-decoder PCM hashes identical: {pcm_hash_identical}/{len(pcm_pairs)}")
    print(f"\nGenerated:\n  {out_csv}\n  {out_report}\n  {out_hashes}")

    return 0 if status_counts["PASS"] == len(corrected) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"B10 AUDIT ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
