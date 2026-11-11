import csv
import sys
from pathlib import Path
from collections import Counter

base = Path(sys.argv[1])

selected_pcm = set(
    (base / "pilot/pilot100_pcm_files.txt")
    .read_text().splitlines()
)

# Convert PCM filenames back to MP3 filenames.
selected_mp3 = {
    Path(name).stem + ".mp3"
    for name in selected_pcm
}

manifest = base / "pilot/pilot_manifest.tsv"

speaker_counts = Counter()
matched = 0

with open(manifest, encoding="utf-8") as f:

    for row in csv.DictReader(f, delimiter="\t"):

        if row["path"] in selected_mp3:

            speaker_counts[row["client_id"]] += 1
            matched += 1

print("========== B9 PILOT SPEAKER AUDIT ==========")

print("Selected recordings:", len(selected_pcm))
print("Matched manifest recordings:", matched)
print("Unique speakers:", len(speaker_counts))

print(
    "Speakers with multiple recordings:",
    sum(n > 1 for n in speaker_counts.values())
)

print(
    "Maximum recordings per speaker:",
    max(speaker_counts.values()) if speaker_counts else 0
)

assert len(selected_pcm) == 100
assert matched == 100
assert len(speaker_counts) > 0

print("\nB9 PILOT SPEAKER AUDIT: PASS")
