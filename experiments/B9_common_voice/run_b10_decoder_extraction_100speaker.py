#!/usr/bin/env python3
import csv, hashlib, re, subprocess, tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/ishu/research/redundant_celt_frame_steganography")
B9 = ROOT / "experiments/B9_common_voice"
ROUND = B9 / "results/b9_full_encoding/payload_roundtrip_100speaker"
MANIFEST = ROUND / "b9_payload_manifest.csv"
BITSTREAMS = ROUND / "modified_bitstreams"

DECODERS = {
    "1.5.2": ROOT / "scripts/decode_raw_1.5.2",
    "1.6.1": ROOT / "scripts/decode_raw_1.6.1",
}

OUT_BASE = B9 / "results/b10_decoder_extraction_100speaker"

# Extract the 36-byte candidate from B10 decoder instrumentation.
TAIL36 = re.compile(
    r"(?:^|\|)tail36=([0-9a-fA-F]{72})(?:\||$)"
)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def validate():
    with MANIFEST.open(newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) != 200:
        raise SystemExit(f"Expected 200 manifest rows, found {len(rows)}")

    counts = Counter(r["encoder"] for r in rows)

    if counts != Counter({"1.5.2": 100, "1.6.1": 100}):
        raise SystemExit(f"Unexpected encoder distribution: {dict(counts)}")

    seen = set()

    for r in rows:
        key = (r["encoder"], r["recording"], r["frame"])

        if key in seen:
            raise SystemExit(f"Duplicate manifest event: {key}")

        seen.add(key)

        payload = bytes.fromhex(r["payload_hex"])

        if len(payload) != 36 or sha(payload) != r["payload_sha256"].lower():
            raise SystemExit(f"Payload length/hash failure: {key}")

        path = BITSTREAMS / r["encoder"] / f'{r["recording"]}.bin'

        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"Missing/empty bitstream: {path}")

    # Reconcile directories against manifest.
    for version in ("1.5.2", "1.6.1"):
        expected = {
            r["recording"] for r in rows
            if r["encoder"] == version
        }

        actual = {
            p.stem for p in (BITSTREAMS / version).glob("*.bin")
        }

        if expected != actual or len(actual) != 100:
            raise SystemExit(
                f"Inventory mismatch {version}: "
                f"expected={len(expected)}, actual={len(actual)}, "
                f"missing={sorted(expected-actual)[:5]}, "
                f"extra={sorted(actual-expected)[:5]}"
            )

    # Check decoder executables and B10 instrumentation.
    for version, exe in DECODERS.items():
        if not exe.is_file() or not (exe.stat().st_mode & 0o111):
            raise SystemExit(f"Decoder missing/not executable: {exe}")

        if b"B10|mode=" not in exe.read_bytes():
            raise SystemExit(f"B10 instrumentation absent: {exe}")

    return rows


def main():
    rows = validate()

    OUT_BASE.mkdir(parents=True, exist_ok=True)

    run_dir = OUT_BASE / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir()

    logs = {
        v: run_dir / f"opus_{v}_candidates.log"
        for v in DECODERS
    }

    results = []
    status_counts = Counter()
    combo_counts = Counter()

    print("B10 PREFLIGHT: PASS")
    print("Manifest events: 200")
    print("Decoder runs: 400")
    print("Starting cross-version extraction...")

    with tempfile.TemporaryDirectory(
        prefix="pcm_tmp_", dir=run_dir
    ) as td:

        tmp = Path(td)

        for row in rows:
            enc = row["encoder"]
            rec = row["recording"]

            expected_hex = row["payload_hex"].lower()
            expected_sha = row["payload_sha256"].lower()

            src = BITSTREAMS / enc / f"{rec}.bin"

            for dec, exe in DECODERS.items():
                combo_counts[(enc, dec)] += 1

                pcm = tmp / f"{enc}_{rec}_by_{dec}.pcm"

                # Existing decode_raw invocation:
                # decode_raw input.bin output.pcm
                proc = subprocess.run(
                    [str(exe), str(src), str(pcm)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    check=False
                )

                output = proc.stdout + "\n" + proc.stderr

                candidates = [
                    m.group(1).lower()
                    for m in TAIL36.finditer(output)
                ]

                matches = [
                    x for x in candidates
                    if x == expected_hex
                ]

                pcm_size = 0
                pcm_sha = ""

                if pcm.is_file():
                    data = pcm.read_bytes()
                    pcm_size = len(data)
                    pcm_sha = sha(data)
                    pcm.unlink()

                recovered_hex = (
                    matches[0] if len(matches) == 1 else ""
                )

                recovered_sha = (
                    sha(bytes.fromhex(recovered_hex))
                    if recovered_hex else ""
                )

                decode_ok = (
                    proc.returncode == 0 and pcm_size > 0
                )

                exact = bool(
                    decode_ok
                    and len(matches) == 1
                    and recovered_sha == expected_sha
                )

                if not decode_ok:
                    status = "DECODE_FAIL"
                elif len(matches) == 0:
                    status = "NO_MATCH"
                elif len(matches) > 1:
                    status = "MULTIPLE_MATCHES"
                elif not exact:
                    status = "HASH_MISMATCH"
                else:
                    status = "PASS"

                status_counts[status] += 1

                # Preserve complete decoder-side evidence.
                with logs[dec].open("a", encoding="utf-8") as f:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write(
                        f"encoder={enc} decoder={dec} "
                        f"recording={rec} frame={row['frame']}\n"
                    )
                    f.write(
                        f"return_code={proc.returncode} "
                        f"pcm_bytes={pcm_size}\n"
                    )
                    f.write(
                        f"candidate_count={len(candidates)} "
                        f"match_count={len(matches)} "
                        f"status={status}\n"
                    )
                    f.write(f"expected_sha256={expected_sha}\n")

                    if proc.stdout:
                        f.write("--- STDOUT ---\n" + proc.stdout + "\n")

                    if proc.stderr:
                        f.write("--- STDERR ---\n" + proc.stderr + "\n")

                results.append({
                    "encoder": enc,
                    "decoder": dec,
                    "recording": rec,
                    "speaker": row["speaker"],
                    "frame": row["frame"],
                    "expected_payload_sha256": expected_sha,
                    "decode_return_code": proc.returncode,
                    "pcm_bytes": pcm_size,
                    "pcm_sha256": pcm_sha,
                    "candidate_count": len(candidates),
                    "candidate_match_count": len(matches),
                    "candidate_tail36_hex": ";".join(candidates),
                    "extracted_payload_hex": recovered_hex,
                    "extracted_payload_sha256": recovered_sha,
                    "extraction_exact": exact,
                    "status": status,
                })

                print(
                    f"{len(results):03d}/400 "
                    f"enc={enc} dec={dec} {rec}: {status}"
                )

    csv_path = run_dir / "b10_decoder_extraction_results.csv"

    fields = list(results[0].keys())

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    report_path = run_dir / "b10_decoder_extraction_report.txt"

    with report_path.open("w", encoding="utf-8") as f:
        f.write("========== B10 DECODER EXTRACTION REPORT ==========\n")
        f.write(f"Manifest events: {len(rows)}\n")
        f.write(f"Decoder runs: {len(results)}\n\n")

        for enc in ("1.5.2", "1.6.1"):
            for dec in ("1.5.2", "1.6.1"):
                f.write(
                    f"Encoder {enc} / Decoder {dec}: "
                    f"{combo_counts[(enc, dec)]}\n"
                )

        f.write("\n")

        for status in (
            "PASS", "NO_MATCH", "MULTIPLE_MATCHES",
            "DECODE_FAIL", "HASH_MISMATCH"
        ):
            f.write(f"{status}: {status_counts[status]}\n")

        f.write(
            f"\nExtraction exact: "
            f"{status_counts['PASS']} / {len(results)}\n"
        )

        f.write(f"CSV: {csv_path}\n")
        f.write(f"1.5.2 log: {logs['1.5.2']}\n")
        f.write(f"1.6.1 log: {logs['1.6.1']}\n")

        f.write(
            "\nB10 DECODER EXTRACTION: "
            + (
                "PASS\n"
                if len(results) == 400
                and status_counts["PASS"] == 400
                else "REVIEW REQUIRED\n"
            )
        )

    print("\n========== B10 COMPLETE ==========")
    print(f"PASS: {status_counts['PASS']} / {len(results)}")
    print("CSV:", csv_path)
    print("Report:", report_path)
    print("Logs:", logs["1.5.2"], "and", logs["1.6.1"])

    if len(results) != 400 or status_counts["PASS"] != 400:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
