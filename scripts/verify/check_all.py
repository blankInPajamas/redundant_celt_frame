#!/usr/bin/env python3
"""Check all experiments' results against the reference values."""
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from expected_values import (
    B0, B1, B2_TRIGGER_WINDOW, B3_SCALING, B4,
    B6_KNOWN_CHANNEL, B6_BLIND, B7, B8, TOLERANCE,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXPERIMENTS = ROOT / "experiments"

results = []


def record(name, passed, detail):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}: {detail}")


# ---------- B0 ----------
def check_b0():
    print("B0 — byte classification")
    csv_path = EXPERIMENTS / "B0_decisive" / "results.csv"
    if not csv_path.exists():
        record("B0", False, "results.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))
    structural, content, inert = [], [], []
    for r in rows:
        off = int(r["byte_offset"])
        rc = int(r["decode_rc"])
        pcm_size = int(r.get("pcm_size", 0)) or None
        ident = r["identical_to_baseline"]

        if rc != 0 or (pcm_size and pcm_size != 963840):
            structural.append(off)
        elif ident == "yes":
            inert.append(off)
        else:
            content.append(off)

    ok_struct = sorted(structural) == sorted(B0["structural_bytes"])
    ok_content = sorted(content) == sorted(B0["content_bytes"])
    ok_inert = sorted(inert) == sorted(B0["inert_bytes"])

    record("B0.structural", ok_struct, f"{len(structural)} bytes (expected {len(B0['structural_bytes'])})")
    record("B0.content", ok_content, f"{len(content)} bytes (expected {len(B0['content_bytes'])})")
    record("B0.inert", ok_inert, f"{len(inert)} bytes (expected {len(B0['inert_bytes'])})")
    record("B0.tail_size", len([b for b in inert if b >= 48]) == B0["contiguous_tail_size"],
           f"contiguous tail = {len([b for b in inert if b >= 48])} (expected {B0['contiguous_tail_size']})")


# ---------- B2 ----------
def check_b2():
    print("B2 — trigger window")
    csv_path = EXPERIMENTS / "B2_oneshot_sweep" / "results.csv"
    if not csv_path.exists():
        record("B2", False, "results.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))
    for app in ["audio", "voip", "lowdelay"]:
        app_rows = [r for r in rows if r["application"] == app]
        triggered = [int(r["bitrate"]) for r in app_rows
                     if int(r["max_tail"]) >= 4]
        expected = B2_TRIGGER_WINDOW[app]
        ok = set(triggered) == set(expected)
        record(f"B2.{app}", ok, f"triggered at {triggered} (expected {expected})")


# ---------- B3 ----------
def check_b3():
    print("B3 — tail scaling")
    csv_path = EXPERIMENTS / "B3_tail_scaling" / "results.csv"
    if not csv_path.exists():
        record("B3", False, "results.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))
    for r in rows:
        br = int(r["bitrate"])
        if br not in B3_SCALING:
            continue
        exp_frame, exp_tail, exp_ratio = B3_SCALING[br]
        got_frame = int(r["frame_size"])
        got_tail = int(r["tail_bytes"])
        got_ratio = float(r["ratio"])

        ok_frame = abs(got_frame - exp_frame) <= TOLERANCE["frame_size"]
        ok_tail = abs(got_tail - exp_tail) <= TOLERANCE["tail_size"]
        ok_ratio = abs(got_ratio - exp_ratio) <= TOLERANCE["ratio"]

        record(f"B3.{br}.frame", ok_frame, f"{got_frame} (expected {exp_frame})")
        record(f"B3.{br}.tail", ok_tail, f"{got_tail} (expected {exp_tail})")
        record(f"B3.{br}.ratio", ok_ratio, f"{got_ratio:.3f} (expected {exp_ratio:.3f})")


# ---------- B4 ----------
def check_b4():
    print("B4 — payload demonstration")
    recovered = EXPERIMENTS / "B4_payload" / "recovered.txt"
    if not recovered.exists():
        record("B4", False, "recovered.txt missing")
        return

    content = recovered.read_text().strip()
    ok = content == B4["test_payload"]
    record("B4.recovery", ok, f"recovered='{content}' (expected='{B4['test_payload']}')")


# ---------- B6 ----------
def check_b6():
    print("B6 — steganalysis")

    csv_path = EXPERIMENTS / "B6_steganalysis" / "detection_accuracy.csv"
    if not csv_path.exists():
        record("B6.S2", False, "detection_accuracy.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))

    # Group by (detector, payload) → TPR, FPR
    stats = {}
    for r in rows:
        key = (r["detector"], int(r["payload_size"]))
        kind = r["stream_type"]
        label = r["label"]
        if key not in stats:
            stats[key] = {"clean": 0, "clean_ok": 0, "stego": 0, "stego_ok": 0}
        if kind == "clean":
            stats[key]["clean"] += 1
            if label == "clean":
                stats[key]["clean_ok"] += 1
        else:
            stats[key]["stego"] += 1
            if label == "stego":
                stats[key]["stego_ok"] += 1

    for detector, expected_vals in B6_KNOWN_CHANNEL.items():
        for payload, (exp_tpr, exp_fpr) in expected_vals.items():
            s = stats.get((detector, payload))
            if not s:
                record(f"B6.{detector}.{payload}", False, "missing")
                continue
            tpr = s["stego_ok"] / s["stego"] if s["stego"] else 0
            fpr = 1 - (s["clean_ok"] / s["clean"]) if s["clean"] else 0
            ok_tpr = abs(tpr - exp_tpr) <= TOLERANCE["tpr_fpr"]
            ok_fpr = abs(fpr - exp_fpr) <= TOLERANCE["tpr_fpr"]
            record(f"B6.{detector}.{payload}.TPR", ok_tpr,
                   f"{tpr:.2f} (expected {exp_tpr:.2f})")
            record(f"B6.{detector}.{payload}.FPR", ok_fpr,
                   f"{fpr:.2f} (expected {exp_fpr:.2f})")

    # Blind detection: z-scores should be identical clean vs stego
    blind_path = EXPERIMENTS / "B6_steganalysis" / "blind_detection.csv"
    if blind_path.exists():
        blind_rows = list(csv.DictReader(open(blind_path)))
        clean_z = sorted(set(float(r["z_score"]) for r in blind_rows
                             if r["stream_type"] == "clean"))
        stego_z = sorted(set(float(r["z_score"]) for r in blind_rows
                             if r["stream_type"] == "stego_N32"))
        ok = clean_z == stego_z
        record("B6.blind_identical_z", ok,
               f"clean={len(clean_z)} stego={len(stego_z)} (identical={ok})")


# ---------- B7 ----------
def check_b7():
    print("B7 — music content")
    csv_path = EXPERIMENTS / "B7_music" / "results.csv"
    if not csv_path.exists():
        record("B7", False, "results.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))
    n = len(rows)
    with_tail = sum(1 for r in rows if int(r["tail_frames"]) > 0)
    max_tail = max(int(r["max_tail"]) for r in rows) if rows else 0

    ok_n = n == B7["files"]
    ok_with_tail = with_tail == B7["files_with_tail"]
    ok_max = max_tail <= B7["max_tail_observed"] + TOLERANCE["tail_size"]

    record("B7.file_count", ok_n, f"{n} files (expected {B7['files']})")
    record("B7.trigger_count", ok_with_tail,
           f"{with_tail} files with tail (expected {B7['files_with_tail']})")
    record("B7.max_tail", ok_max,
           f"{max_tail} (expected <= {B7['max_tail_observed'] + TOLERANCE['tail_size']})")


# ---------- B8 ----------
def check_b8():
    print("B8 — LibriSpeech content")
    csv_path = EXPERIMENTS / "B8_librispeech" / "results.csv"
    if not csv_path.exists():
        record("B8", False, "results.csv missing")
        return

    rows = list(csv.DictReader(open(csv_path)))
    n = len(rows)
    with_tail = sum(1 for r in rows if int(r["tail_frames"]) > 0)
    max_tail = max(int(r["max_tail"]) for r in rows) if rows else 0

    ok_n = n == B8["files"]
    ok_with_tail = with_tail == B8["files_with_tail"]
    ok_max = max_tail <= B8["max_tail_observed"] + TOLERANCE["tail_size"]

    record("B8.file_count", ok_n, f"{n} files (expected {B8['files']})")
    record("B8.trigger_count", ok_with_tail,
           f"{with_tail} files with tail (expected {B8['files_with_tail']})")
    record("B8.max_tail", ok_max,
           f"{max_tail} (expected <= {B8['max_tail_observed'] + TOLERANCE['tail_size']})")


# ---------- Main ----------
def main():
    print("========== VERIFICATION ==========")
    print()

    for name, fn in [
        ("B0", check_b0),
        ("B2", check_b2),
        ("B3", check_b3),
        ("B4", check_b4),
        ("B6", check_b6),
        ("B7", check_b7),
        ("B8", check_b8),
    ]:
        try:
            fn()
        except Exception as e:
            record(name, False, f"exception: {e}")
        print()

    n_pass = sum(1 for _, status, _ in results if status == "PASS")
    n_fail = sum(1 for _, status, _ in results if status == "FAIL")

    print("========== SUMMARY ==========")
    print(f"PASS: {n_pass}")
    print(f"FAIL: {n_fail}")
    print(f"Total: {len(results)}")

    if n_fail > 0:
        print()
        print("Failures:")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"  {name}: {detail}")
        sys.exit(1)
    else:
        print()
        print("All checks passed. Results are consistent with the audit.")
        sys.exit(0)


if __name__ == "__main__":
    main()