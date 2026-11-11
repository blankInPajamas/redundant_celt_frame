import csv
import random
from pathlib import Path

BASE = Path(__file__).parent
TRAIN = BASE / "metadata/train.tsv"

OUTPUT = BASE / "pilot/pilot_manifest.tsv"
MEMBERS = BASE / "pilot/audio_members.txt"

SAMPLE_SIZE = 5000
SEED = 20261103

with open(TRAIN, encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))

assert len(rows) == 280865

rng = random.Random(SEED)
selected = rng.sample(rows, SAMPLE_SIZE)

selected.sort(key=lambda r: r["path"])

fields = [
    "client_id",
    "path",
    "sentence_id",
    "gender",
    "accents",
    "locale"
]

seen = set()

for row in selected:
    assert row["gender"] == "male_masculine"
    assert row["accents"] == "United States English"
    assert row["locale"] == "en"
    assert row["path"].endswith(".mp3")
    assert row["client_id"]
    assert row["path"] not in seen

    seen.add(row["path"])

with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=fields,
        delimiter="\t"
    )

    writer.writeheader()

    # Write only the requested six columns.
    writer.writerows(
        {field: row[field] for field in fields}
        for row in selected
    )

with open(MEMBERS, "w", encoding="utf-8") as f:
    for row in selected:
        f.write("clips/" + row["path"] + "\n")

speakers = {r["client_id"] for r in selected}

print("========== B9 PILOT SELECTION ==========")
print("Seed:", SEED)
print("Selected clips:", len(selected))
print("Unique speakers:", len(speakers))
print("Training population:", len(rows))
print("Sampling fraction:", f"{SAMPLE_SIZE/len(rows)*100:.2f}%")
print("Manifest:", OUTPUT)
print("Archive member list:", MEMBERS)

assert len(selected) == SAMPLE_SIZE

print("B9 PILOT SELECTION: PASS")
