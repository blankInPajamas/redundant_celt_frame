import csv
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent / "metadata"

splits = ["train", "dev", "test"]
speaker_sets = {}
all_paths = set()

total_rows = 0
missing_speakers = 0
duplicate_paths = 0
gender_counts = Counter()
accent_counts = Counter()

print("========== B9 METADATA VALIDATION ==========")

for split in splits:
    path = BASE / f"{split}.tsv"
    speakers = set()
    rows = 0

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")

        if not {"client_id", "path"}.issubset(reader.fieldnames):
            raise ValueError(f"Missing required columns in {split}.tsv")

        print(f"\n{split.upper()} columns:", reader.fieldnames)

        for row in reader:
            rows += 1

            client = row.get("client_id", "").strip()
            clip = row.get("path", "").strip()

            if client:
                speakers.add(client)
            else:
                missing_speakers += 1

            if clip in all_paths:
                duplicate_paths += 1
            all_paths.add(clip)

            gender_counts[row.get("gender", "")] += 1
            accent_counts[row.get("accents", "")] += 1

    speaker_sets[split] = speakers
    total_rows += rows

    print("Rows:", rows)
    print("Unique speakers:", len(speakers))

print("\n========== SPLIT INDEPENDENCE ==========")

for i, a in enumerate(splits):
    for b in splits[i+1:]:
        overlap = speaker_sets[a] & speaker_sets[b]
        print(f"{a} vs {b}: {len(overlap)} overlapping speakers")

print("\n========== DATASET SUMMARY ==========")
print("Total clips:", total_rows)
print("Total unique speakers:",
      len(set.union(*speaker_sets.values())))
print("Missing speaker IDs:", missing_speakers)
print("Duplicate clip paths:", duplicate_paths)

print("\nGender distribution:", gender_counts)
print("Accent distribution:", accent_counts)

print("\n========== VALIDATION ==========")

assert missing_speakers == 0, "Missing speaker IDs"
assert duplicate_paths == 0, "Duplicate clip paths"

for i, a in enumerate(splits):
    for b in splits[i+1:]:
        assert not (speaker_sets[a] & speaker_sets[b]), \
            f"Speaker leakage: {a} and {b}"

print("B9 METADATA VALIDATION: PASS")
