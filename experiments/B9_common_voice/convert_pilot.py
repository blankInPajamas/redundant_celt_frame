import csv
import hashlib
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

BASE = Path(__file__).parent
AUDIO = BASE / "pilot/audio/clips"
PCM = BASE / "pilot/pcm"

MANIFEST = BASE / "pilot/pilot_manifest.tsv"
RESULTS = BASE / "results/b9_pcm_conversion.csv"
FAILURES = BASE / "results/b9_conversion_failures.txt"

SAMPLE_RATE = 48000
FRAME_SIZE = 960
WORKERS = 4

PCM.mkdir(parents=True, exist_ok=True)
RESULTS.parent.mkdir(parents=True, exist_ok=True)

def sha256(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


with open(MANIFEST, encoding="utf-8") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))


def convert(row):
    source_name = row["path"]

    if Path(source_name).name != source_name:
        return {"status": "INVALID_PATH", "source": source_name}

    source = AUDIO / source_name
    output = PCM / (Path(source_name).stem + ".pcm")
    temp = output.with_suffix(".pcm.tmp")

    try:
        if not source.is_file():
            raise FileNotFoundError(source)

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-xerror",
            "-y",
            "-i", str(source),
            "-map", "0:a:0",
            "-vn", "-sn", "-dn",
            "-ac", "1",
            "-ar", str(SAMPLE_RATE),
            "-c:a", "pcm_s16le",
            "-f", "s16le",
            str(temp)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr[-1000:])

        size = temp.stat().st_size

        if size == 0 or size % 2:
            raise ValueError("Invalid PCM size")

        samples = size // 2
        complete_frames = samples // FRAME_SIZE
        remainder = samples % FRAME_SIZE

        temp.replace(output)

        return {
            "status": "PASS",
            "source": source_name,
            "client_id": row["client_id"],
            "pcm_file": output.name,
            "pcm_bytes": size,
            "pcm_samples": samples,
            "complete_frames": complete_frames,
            "remainder_samples": remainder,
            "discarded_ms": remainder / SAMPLE_RATE * 1000,
            "duration_seconds": samples / SAMPLE_RATE,
            "encoded_duration_seconds":
                complete_frames * FRAME_SIZE / SAMPLE_RATE,
            "sha256": sha256(output),
            "error": ""
        }

    except Exception as e:
        temp.unlink(missing_ok=True)

        return {
            "status": "FAIL",
            "source": source_name,
            "error": str(e)
        }


results = []

print("========== B9 PCM CONVERSION ==========")
print("Recordings:", len(rows))
print("Workers:", WORKERS)

with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    for i, result in enumerate(pool.map(convert, rows), 1):
        results.append(result)

        if i % 100 == 0:
            print(f"Processed {i}/{len(rows)}")

fields = [
    "status",
    "source",
    "client_id",
    "pcm_file",
    "pcm_bytes",
    "pcm_samples",
    "complete_frames",
    "remainder_samples",
    "discarded_ms",
    "duration_seconds",
    "encoded_duration_seconds",
    "sha256",
    "error"
]

with open(RESULTS, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()

    for result in results:
        writer.writerow({
            field: result.get(field, "")
            for field in fields
        })

passed = [r for r in results if r["status"] == "PASS"]
failed = [r for r in results if r["status"] != "PASS"]

with open(FAILURES, "w", encoding="utf-8") as f:
    for r in failed:
        f.write(str(r) + "\n")

total_samples = sum(r["pcm_samples"] for r in passed)
total_frames = sum(r["complete_frames"] for r in passed)
total_remainder = sum(r["remainder_samples"] for r in passed)

print("\n========== CONVERSION SUMMARY ==========")
print("Expected:", len(rows))
print("Successful:", len(passed))
print("Failed:", len(failed))
print("Total PCM bytes:", sum(r["pcm_bytes"] for r in passed))
print("Total decoded hours:", total_samples / SAMPLE_RATE / 3600)
print("Complete Opus frames:", total_frames)
print("Incomplete trailing samples:", total_remainder)
print("Potentially discarded milliseconds:",
      total_remainder / SAMPLE_RATE * 1000)

print("\nResults:", RESULTS)
print("Failures:", FAILURES)

if len(passed) != len(rows) or failed:
    raise SystemExit("B9 PCM CONVERSION: FAIL")

print("\nB9 PCM CONVERSION: PASS")
