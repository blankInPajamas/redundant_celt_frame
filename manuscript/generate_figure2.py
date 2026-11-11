from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

# --------------------------------------------------
# PATHS
# --------------------------------------------------

BASE = Path(".")
OUT = BASE / "manuscript" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

CANDIDATES = (
    BASE / "experiments/B9_common_voice/results/"
    "b9_full_encoding/payload_preflight/"
    "b9_payload_event_candidates.csv"
)

CAPACITY = (
    BASE / "experiments/B9_common_voice/results/"
    "b11_payload_reliability/pilot_20261104_013941/"
    "b11_independent_capacity_audit.csv"
)

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def as_bool(series):
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin(["1", "true", "yes", "y"])
    )

# --------------------------------------------------
# LOAD B9 CANDIDATES
# --------------------------------------------------

df = pd.read_csv(CANDIDATES)

df["trailing_zero_bytes"] = pd.to_numeric(
    df["trailing_zero_bytes"], errors="coerce"
)

for col in [
    "final_record_found",
    "moved",
    "relocation_consistent"
]:
    df[col] = as_bool(df[col])

df["tail_ge_36"] = (
    pd.to_numeric(df["tail_ge_36"], errors="coerce")
    .fillna(0).astype(int)
)

df["tail_ge_36_calculated"] = (
    df["trailing_zero_bytes"] >= 36
).astype(int)

mismatches = (
    df["tail_ge_36"] != df["tail_ge_36_calculated"]
).sum()

print("\n========== FIGURE 2 DATA AUDIT ==========")
print("Candidate records:", len(df))
print("Tail flag mismatches:", mismatches)

if mismatches:
    raise ValueError(
        "tail_ge_36 does not match trailing_zero_bytes"
    )

# Only use candidates with verified relocation records.
valid = df[
    df["final_record_found"]
    & df["moved"]
    & df["relocation_consistent"]
].copy()

print("Validated candidate records:", len(valid))

# --------------------------------------------------
# VERSION SUMMARY
# --------------------------------------------------

summary = []

for version in ["1.5.2", "1.6.1"]:

    all_rows = df[df["version"].astype(str) == version]
    g = valid[valid["version"].astype(str) == version]

    n = len(g)
    capacity = int((g["trailing_zero_bytes"] >= 36).sum())

    percentage = (
        100 * capacity / n if n else 0
    )

    exact36 = int(
        (g["trailing_zero_bytes"] == 36).sum()
    )

    summary.append({
        "version": version,
        "all_candidates": len(all_rows),
        "validated_candidates": n,
        "tail_at_least_36": capacity,
        "exactly_36": exact36,
        "percentage_at_least_36": percentage
    })

    print(f"\nOpus {version}")
    print("All candidates:", len(all_rows))
    print("Validated candidates:", n)
    print("At least 36 zero bytes:", capacity)
    print("Exactly 36 zero bytes:", exact36)
    print("Occurrence:", f"{percentage:.2f}%")

    print("\nZero-tail distribution:")
    print(
        g["trailing_zero_bytes"]
        .value_counts()
        .sort_index()
        .to_string()
    )

summary_df = pd.DataFrame(summary)

summary_df.to_csv(
    OUT / "fig2_source_summary.csv",
    index=False
)

# --------------------------------------------------
# B11 CAPACITY AUDIT
# --------------------------------------------------

capacity_df = pd.read_csv(CAPACITY)

print("\n========== B11 CAPACITY AUDIT ==========")

for version, g in capacity_df.groupby("encoder"):

    print("\nEncoder:", version)
    print("Records:", len(g))

    print("Actual zero-tail distribution:")
    print(
        g["actual_zero_tail_bytes"]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print(
        "37-byte attempts:",
        (g["attempted_payload_bytes"] == 37).sum()
    )

    print(
        "Physical capacity verified:",
        as_bool(g["physical_capacity_verified"]).sum(),
        "/", len(g)
    )

    print(
        "Configured guard rejected:",
        as_bool(g["configured_guard_rejected"]).sum(),
        "/", len(g)
    )

# --------------------------------------------------
# GENERATE FIGURE 2
# --------------------------------------------------

fig, axes = plt.subplots(
    1, 2,
    figsize=(7.2, 3.2)
)

versions = ["1.5.2", "1.6.1"]

# Panel A: relocation success
ax = axes[0]

success = [5050, 4929]
total = [5050, 4929]

rates = [
    100 * s / t
    for s, t in zip(success, total)
]

bars = ax.bar(versions, rates)

for bar, s, t in zip(bars, success, total):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() - 5,
        f"{s:,}/{t:,}",
        ha="center",
        va="top",
        fontsize=8
    )

ax.set_ylim(0, 110)
ax.set_ylabel("Successful relocation (%)")
ax.set_title("(a) Relocation validation")
ax.grid(axis="y", alpha=0.25)

# Panel B: 36-byte zero-tail availability
ax = axes[1]

percentages = [
    x["percentage_at_least_36"]
    for x in summary
]

bars = ax.bar(versions, percentages)

for bar, item in zip(bars, summary):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 1,
        (
            f'{item["tail_at_least_36"]:,}/'
            f'{item["validated_candidates"]:,}'
            f'\n({item["percentage_at_least_36"]:.1f}%)'
        ),
        ha="center",
        va="bottom",
        fontsize=7
    )

ax.set_ylim(
    0,
    max(100, max(percentages, default=0) + 15)
)

ax.set_ylabel("Candidates with ≥36 zero bytes (%)")
ax.set_title("(b) Zero-tail availability")
ax.grid(axis="y", alpha=0.25)

fig.tight_layout()

fig.savefig(
    OUT / "fig2_redundancy_characterization.png",
    dpi=300,
    bbox_inches="tight"
)

fig.savefig(
    OUT / "fig2_redundancy_characterization.pdf",
    bbox_inches="tight"
)

plt.close(fig)

print("\nFIGURE 2 GENERATED SUCCESSFULLY")
print("Output:", OUT)
