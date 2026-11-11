#!/usr/bin/env python3
"""Run the B11 Common Voice payload-reliability pilot."""
import csv, hashlib, json, os, re, struct, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B9 = ROOT / "experiments/B9_common_voice"
BASE = B9 / "results/b11_payload_reliability"
MANIFEST = B9 / "results/b9_full_encoding/payload_roundtrip_100speaker/b9_payload_manifest.csv"
BITROOT = B9 / "results/b9_full_encoding"

VERSIONS = ("1.5.2", "1.6.1")
DECODERS = {v: ROOT / f"scripts/decode_raw_{v}" for v in VERSIONS}

SIZES = (4, 8, 16, 24, 32, 36)
REPS = 3
CAPACITY = 36

# Exact events selected by the successful B11 preflight.
PILOT = {
 "1.5.2": [
  "common_voice_en_10143", "common_voice_en_17296746",
  "common_voice_en_17969876", "common_voice_en_18779251",
  "common_voice_en_19956563", "common_voice_en_21857421",
  "common_voice_en_24015131", "common_voice_en_32651929",
  "common_voice_en_565467", "common_voice_en_76718"
 ],
 "1.6.1": [
  "common_voice_en_117681", "common_voice_en_17278718",
  "common_voice_en_17893190", "common_voice_en_18835223",
  "common_voice_en_20371345", "common_voice_en_22730873",
  "common_voice_en_25318456", "common_voice_en_30678398",
  "common_voice_en_54511", "common_voice_en_9412178"
 ]
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_packets(path):
    data = Path(path).read_bytes()
    packets = []
    off = 0

    while off < len(data):
        if off + 4 > len(data):
            raise ValueError(f"Incomplete packet header: {path}")

        n = struct.unpack_from("<I", data, off)[0]
        off += 4

        if n <= 0 or off + n > len(data):
            raise ValueError(f"Invalid packet framing: {path}")

        packets.append(data[off:off+n])
        off += n

    return packets


def write_packets(path, packets):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "wb") as f:
        for p in packets:
            f.write(struct.pack("<I", len(p)) + p)


def zero_tail(packet):
    n = 0

    for b in reversed(packet):
        if b:
            break
        n += 1

    return n


def embed(packets, frame, payload):
    if len(payload) > CAPACITY:
        raise ValueError(
            f"Payload {len(payload)} exceeds {CAPACITY}-byte capacity"
        )

    if not 0 < len(payload) <= CAPACITY:
        raise ValueError("Invalid payload size")

    if not 0 <= frame < len(packets):
        raise ValueError("Invalid target frame")

    if zero_tail(packets[frame]) != CAPACITY:
        raise ValueError("Expected exactly 36 trailing zeros")

    out = list(packets)
    p = bytearray(out[frame])
    p[-len(payload):] = payload
    out[frame] = bytes(p)

    return out


def make_payload(enc, rec, frame, size, rep):
    seed = (
        f"B11-CV26-PILOT-v1|{enc}|{rec}|"
        f"{frame}|{size}|{rep}"
    ).encode()

    return hashlib.shake_256(seed).digest(size)


def csv_write(path, rows, fields=None):
    if fields is None:
        fields = list(rows[0]) if rows else []

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def decode(decoder, bitstream, pcm_path, nframes):
    p = subprocess.run(
        [str(decoder), str(bitstream), str(pcm_path)],
        capture_output=True,
        text=True,
        timeout=120
    )

    log = p.stderr or ""
    m = re.search(r"Decoded\s+(\d+)\s+frames", log)
    frames = int(m.group(1)) if m else -1

    pcm = (
        Path(pcm_path).read_bytes()
        if Path(pcm_path).is_file()
        else b""
    )

    ok = (
        p.returncode == 0
        and frames == nframes
        and bool(pcm)
    )

    return p.returncode, log, frames, pcm, ok


def extract_tail(log, payload):
    matches = []
    n = len(payload)

    for h in re.findall(r"tail36=([0-9a-fA-F]{72})", log):
        t = bytes.fromhex(h)

        if (
            t[:CAPACITY-n] == bytes(CAPACITY-n)
            and t[CAPACITY-n:] == payload
        ):
            matches.append(t)

    tail = matches[0] if len(matches) == 1 else None

    return (
        tail,
        len(matches),
        len(re.findall(r"tail36=([0-9a-fA-F]{72})", log))
    )


def main():

    if not MANIFEST.is_file():
        raise FileNotFoundError(MANIFEST)

    for p in (
        BASE / "b11_preflight_report.txt",
        BASE / "b11_source_bitstreams.sha256"
    ):
        if not p.is_file():
            raise FileNotFoundError(f"Missing B11 preflight artifact: {p}")

    for v, d in DECODERS.items():
        if not d.is_file() or not os.access(d, os.X_OK):
            raise FileNotFoundError(
                f"Missing/non-executable decoder {v}: {d}"
            )

    out = BASE / (
        "pilot_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=False)

    for d in (
        "bitstreams",
        "corrupted_bitstreams",
        "baseline_pcm",
        "decode_tmp"
    ):
        (out/d).mkdir(parents=True, exist_ok=True)

    with open(MANIFEST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    lookup = {}

    for r in rows:
        k = (r["encoder"], r["recording"])

        if k in lookup:
            raise ValueError(f"Duplicate manifest event: {k}")

        lookup[k] = r

    # Validate and freeze the 20 preflight-selected events.
    events = []

    for enc in VERSIONS:

        if len(PILOT[enc]) != 10 or len(set(PILOT[enc])) != 10:
            raise ValueError("Pilot list must have 10 unique recordings")

        part = []

        for rec in PILOT[enc]:

            r = lookup.get((enc, rec))

            if r is None:
                raise ValueError(
                    f"Preflight event missing from manifest: {enc}/{rec}"
                )

            old = bytes.fromhex(r["payload_hex"])

            if len(old) != CAPACITY or sha(old) != r["payload_sha256"]:
                raise ValueError(
                    f"B9 manifest payload/hash mismatch: {enc}/{rec}"
                )

            if (
                r["extraction_exact"].lower() != "true"
                or r["packet_lengths_preserved"].lower() != "true"
            ):
                raise ValueError(
                    f"B9 event not previously validated: {enc}/{rec}"
                )

            src = BITROOT / enc / "bitstreams" / f"{rec}.bin"

            if not src.is_file():
                raise FileNotFoundError(src)

            packets = read_packets(src)
            frame = int(r["frame"])

            if (
                frame >= len(packets)
                or zero_tail(packets[frame]) != CAPACITY
            ):
                raise ValueError(
                    f"Target packet capacity mismatch: {enc}/{rec}"
                )

            part.append({
                "enc": enc,
                "rec": rec,
                "speaker": r["speaker"],
                "frame": frame,
                "src": src,
                "packets": packets,
                "src_hash": file_sha(src)
            })

        if len({e["speaker"] for e in part}) != 10:
            raise ValueError(f"Speakers are not unique within {enc}")

        events += part

    before = {
        str(e["src"]): e["src_hash"]
        for e in events
    }

    with open(out/"b11_source_bitstreams_before.sha256", "w") as f:
        for p, h in sorted(before.items()):
            f.write(f"{h}  {Path(p).relative_to(ROOT)}\n")

    selection = [{
        "encoder": e["enc"],
        "recording": e["rec"],
        "speaker_sha256": e["speaker"],
        "frame": e["frame"],
        "source_sha256": e["src_hash"]
    } for e in events]

    csv_write(out/"b11_pilot_selection.csv", selection)

    config = {
        "experiment": "B11 Common Voice payload reliability pilot",
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": file_sha(MANIFEST),
        "encoders": VERSIONS,
        "payload_sizes_bytes": SIZES,
        "repetitions": REPS,
        "usable_capacity_bytes": CAPACITY,
        "pilot_events_per_encoder": 10,
        "corruption": "one bit flipped in repetition 1 for each event-size pair",
        "integrity": "out-of-band SHA256 comparison with original payload",
        "pcm_comparison": "modified versus baseline within the same decoder"
    }

    (out/"b11_run_config.json").write_text(
        json.dumps(config, indent=2) + "\n"
    )

    # Baseline decoding: 20 recordings x 2 decoders.
    baseline = {}
    baseline_rows = []

    print("========== B11 BASELINE DECODING ==========")

    with open(out/"b11_baseline_decoder_logs.txt", "w") as logs:

        for e in events:

            for dv in VERSIONS:

                pcmfile = (
                    out/"baseline_pcm"/e["enc"]/
                    f"{e['rec']}_dec{dv}.pcm"
                )
                pcmfile.parent.mkdir(parents=True, exist_ok=True)

                rc, log, n, pcm, ok = decode(
                    DECODERS[dv],
                    e["src"],
                    pcmfile,
                    len(e["packets"])
                )

                logs.write(
                    f"\n===== {e['enc']} {e['rec']} decoder {dv} =====\n"
                    f"{log}"
                )

                baseline[(e["enc"], e["rec"], dv)] = (
                    pcm if ok else None
                )

                baseline_rows.append({
                    "encoder": e["enc"],
                    "decoder": dv,
                    "recording": e["rec"],
                    "return_code": rc,
                    "frames": n,
                    "expected_frames": len(e["packets"]),
                    "pcm_bytes": len(pcm),
                    "pcm_sha256": sha(pcm) if pcm else "",
                    "baseline_pass": ok
                })

    csv_write(out/"b11_baseline_results.csv", baseline_rows)

    print(
        f"Baseline decodes: "
        f"{sum(x['baseline_pass'] for x in baseline_rows)}/{len(baseline_rows)}"
    )

    manifest = []
    results = []
    capacity = []

    with open(out/"b11_decoder_logs.txt", "w") as logs:

        print("\n========== B11 PAYLOAD TESTS ==========")

        for ei, e in enumerate(events, 1):

            enc, rec = e["enc"], e["rec"]
            frame, packets = e["frame"], e["packets"]

            # Test the 37-byte capacity boundary.
            try:
                embed(packets, frame, bytes(37))
                rejected = False
            except ValueError:
                rejected = True

            capacity.append({
                "encoder": enc,
                "recording": rec,
                "frame": frame,
                "attempted_bytes": 37,
                "capacity_bytes": CAPACITY,
                "rejected": rejected,
                "source_unchanged": file_sha(e["src"]) == e["src_hash"]
            })

            for size in SIZES:

                seen = set()

                for rep in range(1, REPS+1):

                    payload = make_payload(enc, rec, frame, size, rep)

                    if payload in seen:
                        raise RuntimeError(
                            f"Payload repetition collision: {enc}/{rec}/{size}"
                        )

                    seen.add(payload)

                    mod = embed(packets, frame, payload)

                    bit = (
                        out/"bitstreams"/enc/rec/
                        f"payload_{size:02d}B_rep{rep}.bin"
                    )

                    write_packets(bit, mod)
                    check = read_packets(bit)

                    frame_ok = (
                        len(check) == len(packets)
                        and [len(x) for x in check] == [len(x) for x in packets]
                        and check[frame][-size:] == payload
                        and check[frame][:-CAPACITY] == packets[frame][:-CAPACITY]
                    )

                    if not frame_ok:
                        raise RuntimeError(
                            f"Packet framing check failed: {bit}"
                        )

                    manifest.append({
                        "encoder": enc,
                        "recording": rec,
                        "speaker_sha256": e["speaker"],
                        "frame": frame,
                        "payload_size_bytes": size,
                        "repetition": rep,
                        "payload_hex": payload.hex(),
                        "payload_sha256": sha(payload),
                        "source_bitstream_sha256": e["src_hash"],
                        "modified_bitstream_sha256": file_sha(bit),
                        "packet_lengths_preserved": frame_ok,
                        "modified_bitstream": str(bit.relative_to(out))
                    })

                    tests = [
                        ("payload", payload, payload, bit, 0, "")
                    ]

                    # One-bit corruption control for repetition 1.
                    if rep == 1:

                        corrupt = bytearray(payload)
                        corrupt[len(corrupt)//2] ^= 1
                        corrupt = bytes(corrupt)

                        flips = sum(
                            (a ^ b).bit_count()
                            for a, b in zip(payload, corrupt)
                        )

                        if flips != 1:
                            raise RuntimeError(
                                "Corruption control did not flip exactly one bit"
                            )

                        cmod = embed(packets, frame, corrupt)

                        cbit = (
                            out/"corrupted_bitstreams"/enc/rec/
                            f"corrupt_{size:02d}B_rep1.bin"
                        )

                        write_packets(cbit, cmod)
                        ccheck = read_packets(cbit)

                        cframe_ok = (
                            len(ccheck) == len(packets)
                            and [len(x) for x in ccheck] == [len(x) for x in packets]
                            and ccheck[frame][-size:] == corrupt
                            and ccheck[frame][:-CAPACITY] == packets[frame][:-CAPACITY]
                        )

                        if not cframe_ok:
                            raise RuntimeError(
                                f"Corruption framing failed: {cbit}"
                            )

                        tests.append((
                            "one_bit_corruption",
                            corrupt,
                            payload,
                            cbit,
                            flips,
                            len(corrupt)//2
                        ))

                    # Decode with both Opus versions.
                    for test in tests:

                        if len(test) == 5:
                            control, wire, original, testbit, flipcount = test
                            flipindex = ""
                        else:
                            control, wire, original, testbit, flipcount, flipindex = test

                        for dv in VERSIONS:

                            basepcm = baseline.get((enc, rec, dv))

                            with tempfile.TemporaryDirectory(
                                dir=out/"decode_tmp"
                            ) as td:

                                pcmpath = Path(td)/"decoded.pcm"

                                try:
                                    rc, log, n, pcm, ok = decode(
                                        DECODERS[dv],
                                        testbit,
                                        pcmpath,
                                        len(packets)
                                    )
                                except subprocess.TimeoutExpired as ex:
                                    rc, log, n, pcm, ok = (
                                        124, str(ex), -1, b"", False
                                    )

                            logs.write(
                                f"\n===== {control} {enc} {rec} "
                                f"{size}B rep{rep} decoder {dv} =====\n{log}"
                            )

                            tail, matches, total = extract_tail(log, wire)

                            recovered = (
                                tail[-size:] if tail is not None else b""
                            )

                            original_hash = sha(original)
                            wire_hash = sha(wire)
                            got_hash = sha(recovered) if recovered else ""

                            exact = tail is not None and recovered == wire
                            mismatch = bool(
                                got_hash and got_hash != original_hash
                            )

                            if control == "payload":
                                integrity = (
                                    exact
                                    and got_hash == original_hash
                                    and not mismatch
                                )
                            else:
                                integrity = (
                                    exact
                                    and got_hash == wire_hash
                                    and mismatch
                                )

                            results.append({
                                "control": control,
                                "encoder": enc,
                                "decoder": dv,
                                "recording": rec,
                                "speaker_sha256": e["speaker"],
                                "frame": frame,
                                "payload_size_bytes": size,
                                "repetition": rep,
                                "original_payload_sha256": original_hash,
                                "wire_payload_sha256": wire_hash,
                                "bit_flip_count": flipcount,
                                "bit_flip_byte_index": flipindex,
                                "extracted_payload_sha256": got_hash,
                                "extraction_exact": exact,
                                "integrity_mismatch_detected": mismatch,
                                "integrity_control_pass": integrity,
                                "matching_tail_count": matches,
                                "total_tail_records": total,
                                "decoder_return_code": rc,
                                "decoded_frames": n,
                                "expected_frames": len(packets),
                                "decoder_pass": ok,
                                "baseline_pcm_bytes": len(basepcm) if basepcm is not None else 0,
                                "modified_pcm_bytes": len(pcm),
                                "baseline_pcm_sha256": sha(basepcm) if basepcm is not None else "",
                                "modified_pcm_sha256": sha(pcm) if pcm else "",
                                "pcm_identical": basepcm is not None and pcm == basepcm,
                                "packet_lengths_preserved": frame_ok if control == "payload" else cframe_ok,
                                "bitstream": str(testbit.relative_to(out))
                            })

            print(f"Processed event {ei}/20: {enc} {rec}")

    # Verify original source files were not modified.
    after = {
        str(e["src"]): file_sha(e["src"])
        for e in events
    }

    with open(out/"b11_source_bitstreams_after.sha256", "w") as f:
        for p, h in sorted(after.items()):
            f.write(f"{h}  {Path(p).relative_to(ROOT)}\n")

    source_unchanged = before == after

    csv_write(out/"b11_payload_manifest.csv", manifest)
    csv_write(out/"b11_decoder_results.csv", results)
    csv_write(out/"b11_capacity_rejection.csv", capacity)

    normal = [r for r in results if r["control"] == "payload"]
    corrupt = [r for r in results if r["control"] == "one_bit_corruption"]

    baseline_ok = sum(bool(r["baseline_pass"]) for r in baseline_rows)
    normal_ok = sum(bool(r["extraction_exact"]) for r in normal)
    corrupt_ok = sum(bool(r["extraction_exact"]) for r in corrupt)
    integrity_ok = sum(bool(r["integrity_control_pass"]) for r in corrupt)
    decode_ok = sum(bool(r["decoder_pass"]) for r in results)
    pcm_ok = sum(bool(r["pcm_identical"]) for r in results)
    framing_ok = sum(bool(r["packet_lengths_preserved"]) for r in results)

    capacity_ok = sum(
        bool(r["rejected"]) and bool(r["source_unchanged"])
        for r in capacity
    )

    passed = (
        len(events) == 20
        and len(manifest) == 360
        and len(normal) == 720
        and len(corrupt) == 240
        and baseline_ok == 40
        and normal_ok == 720
        and corrupt_ok == 240
        and integrity_ok == 240
        and decode_ok == 960
        and pcm_ok == 960
        and framing_ok == 960
        and capacity_ok == 20
        and source_unchanged
    )

    report = [
        "========== B11 PAYLOAD RELIABILITY PILOT REPORT ==========",
        f"Run directory: {out}",
        f"Source manifest SHA256: {file_sha(MANIFEST)}",
        "",
        "Design: 20 events (10 per encoder); 6 payload sizes; 3 deterministic SHAKE-256 repetitions.",
        "Payload sizes: 4, 8, 16, 24, 32, 36 bytes.",
        f"Uncorrupted payload instances: {len(manifest)}",
        f"One-bit corruption controls: {len(corrupt)//2} payload instances, each tested with both decoders.",
        "Integrity uses an out-of-band sender SHA256; this is not native Opus authentication.",
        "",
        "========== RESULTS ==========",
        f"Baseline decodes: {baseline_ok}/{len(baseline_rows)}",
        f"Uncorrupted extraction: {normal_ok}/{len(normal)}",
        f"Corrupted extraction: {corrupt_ok}/{len(corrupt)}",
        f"SHA256 integrity controls: {integrity_ok}/{len(corrupt)}",
        f"Modified decoder runs successful: {decode_ok}/{len(results)}",
        f"PCM identical vs same-decoder baseline: {pcm_ok}/{len(results)}",
        f"Packet framing preserved: {framing_ok}/{len(results)}",
        f"37-byte rejection with source unchanged: {capacity_ok}/{len(capacity)}",
        f"Source bitstreams unchanged: {source_unchanged}",
        f"Usable payload tail: {CAPACITY} bytes ({CAPACITY*8} bits)",
        "",
        f"OVERALL B11 PILOT: {'PASS' if passed else 'FAIL / INVESTIGATION REQUIRED'}"
    ]

    (out/"b11_report.txt").write_text("\n".join(report) + "\n")

    config["script_sha256"] = file_sha(Path(__file__))

    (out/"b11_run_config.json").write_text(
        json.dumps(config, indent=2) + "\n"
    )

    checksum = out/"b11_checksums.sha256"

    with open(checksum, "w") as f:
        for p in sorted(
            x for x in out.rglob("*")
            if x.is_file() and x != checksum
        ):
            f.write(f"{file_sha(p)}  {p.relative_to(out)}\n")

    print("\n========== B11 FINAL RESULTS ==========")
    print(f"Payload instances: {len(manifest)}")
    print(f"Uncorrupted extraction: {normal_ok}/{len(normal)}")
    print(f"Corruption extraction: {corrupt_ok}/{len(corrupt)}")
    print(f"Integrity controls: {integrity_ok}/{len(corrupt)}")
    print(f"Decoder runs: {decode_ok}/{len(results)}")
    print(f"PCM identical: {pcm_ok}/{len(results)}")
    print(f"Packet framing: {framing_ok}/{len(results)}")
    print(f"37-byte rejection: {capacity_ok}/{len(capacity)}")
    print(f"Source unchanged: {source_unchanged}")
    print(f"Report: {out/'b11_report.txt'}")
    print(f"Checksums: {checksum}")
    print(f"Results directory: {out}")

    print(
        "B11 PILOT: PASS"
        if passed
        else "B11 PILOT: FAIL / INVESTIGATION REQUIRED"
    )

    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"B11 PILOT ABORTED: {type(exc).__name__}: {exc}",
            file=sys.stderr
        )
        raise
