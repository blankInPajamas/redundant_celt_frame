import csv
import struct
import hashlib
import tempfile
import subprocess

from pathlib import Path
from collections import defaultdict

ROOT = Path.cwd()
B9 = ROOT / "experiments/B9_common_voice"
OUT = B9 / "results/b9_full_encoding"

SOURCE = OUT / "payload_mutation_100speaker/b9_100speaker_mutation.csv"
RESULT = OUT / "payload_roundtrip_100speaker"

MODIFIED = RESULT / "modified_bitstreams"
MODIFIED.mkdir(parents=True, exist_ok=True)

VERSIONS = ["1.5.2", "1.6.1"]
DECODERS = {
    v: ROOT / f"scripts/decode_raw_{v}"
    for v in VERSIONS
}

PAYLOAD_SIZE = 36
SEED = "B9_END_TO_END_ROUNDTRIP_V1"


def read_packets(path):
    data = path.read_bytes()
    packets = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length <= 0 or offset + length > len(data):
            raise ValueError("Invalid packet length")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


def write_packets(path, packets):
    with open(path, "wb") as f:
        for packet in packets:
            f.write(struct.pack("<I", len(packet)))
            f.write(packet)


def decode(decoder, bitstream, pcm):
    p = subprocess.run(
        [str(decoder), str(bitstream), str(pcm)],
        capture_output=True,
        text=True
    )
    return p.returncode, p.stderr


# Read and group previous experiment results
groups = defaultdict(list)

with open(SOURCE, newline="") as f:
    for row in csv.DictReader(f):
        key = (
            row["encoder"],
            row["recording"],
            int(row["frame"])
        )
        groups[key].append(row)


payload_manifest = []
roundtrip_results = []

for version in VERSIONS:

    events = []

    for (enc, recording, frame), rows in groups.items():

        if enc != version:
            continue

        assert len(rows) == 2
        assert len({r["speaker"] for r in rows}) == 1

        events.append({
            "recording": recording,
            "speaker": rows[0]["speaker"],
            "frame": frame
        })

    assert len(events) == 100
    assert len({e["recording"] for e in events}) == 100
    assert len({e["speaker"] for e in events}) == 100

    print(f"\n========== ENCODER {version} ==========")
    print("Selected events:", len(events))

    for index, event in enumerate(
        sorted(events, key=lambda x: x["recording"]), 1
    ):

        recording = event["recording"]
        speaker = event["speaker"]
        frame = event["frame"]

        source_bin = (
            OUT / version / "bitstreams" /
            f"{recording}.bin"
        )

        original_packets = read_packets(source_bin)

        if frame >= len(original_packets):
            raise ValueError("Target frame missing")

        original_packet = original_packets[frame]

        if original_packet[-PAYLOAD_SIZE:] != bytes(PAYLOAD_SIZE):
            raise ValueError(
                f"Target suffix is not zero: {recording}"
            )

        # Generate a reproducible 36-byte payload
        seed = f"{SEED}|{version}|{recording}|{frame}".encode()

        payload = hashlib.shake_256(seed).digest(
            PAYLOAD_SIZE
        )

        # Embed payload
        modified_packets = list(original_packets)

        packet = bytearray(original_packet)
        packet[-PAYLOAD_SIZE:] = payload

        modified_packets[frame] = bytes(packet)

        output_dir = MODIFIED / version
        output_dir.mkdir(parents=True, exist_ok=True)

        modified_bin = output_dir / f"{recording}.bin"

        write_packets(modified_bin, modified_packets)

        # Independently reopen and extract
        extracted_packets = read_packets(modified_bin)

        recovered = extracted_packets[frame][-PAYLOAD_SIZE:]

        extraction_ok = recovered == payload

        packet_lengths_ok = (
            len(original_packets) == len(extracted_packets)
            and [
                len(p) for p in original_packets
            ] == [
                len(p) for p in extracted_packets
            ]
        )

        if not extraction_ok or not packet_lengths_ok:
            raise RuntimeError(
                f"Extraction/framing failure: {recording}"
            )

        payload_hash = hashlib.sha256(payload).hexdigest()

        payload_manifest.append({
            "encoder": version,
            "recording": recording,
            "speaker": speaker,
            "frame": frame,
            "payload_hex": payload.hex(),
            "payload_sha256": payload_hash,
            "extracted_sha256": hashlib.sha256(
                recovered
            ).hexdigest(),
            "extraction_exact": extraction_ok,
            "packet_lengths_preserved": packet_lengths_ok
        })

        # Test both decoders
        with tempfile.TemporaryDirectory(dir=RESULT) as td:

            td = Path(td)

            for decoder_version in VERSIONS:

                decoder = DECODERS[decoder_version]

                baseline_pcm = td / "baseline.pcm"
                modified_pcm = td / "modified.pcm"

                rc1, err1 = decode(
                    decoder, source_bin, baseline_pcm
                )

                rc2, err2 = decode(
                    decoder, modified_bin, modified_pcm
                )

                identical = False
                baseline_hash = ""
                modified_hash = ""
                baseline_size = 0
                modified_size = 0

                if rc1 == 0 and rc2 == 0:

                    a = baseline_pcm.read_bytes()
                    b = modified_pcm.read_bytes()

                    baseline_size = len(a)
                    modified_size = len(b)

                    baseline_hash = hashlib.sha256(a).hexdigest()
                    modified_hash = hashlib.sha256(b).hexdigest()

                    identical = a == b

                roundtrip_results.append({
                    "encoder": version,
                    "decoder": decoder_version,
                    "recording": recording,
                    "speaker": speaker,
                    "frame": frame,
                    "payload_bytes": PAYLOAD_SIZE,
                    "baseline_rc": rc1,
                    "modified_rc": rc2,
                    "baseline_pcm_bytes": baseline_size,
                    "modified_pcm_bytes": modified_size,
                    "baseline_pcm_sha256": baseline_hash,
                    "modified_pcm_sha256": modified_hash,
                    "pcm_identical": identical,
                    "extraction_exact": extraction_ok,
                    "packet_lengths_preserved": packet_lengths_ok
                })

        if index % 10 == 0:
            print(f"Processed {index}/100")


def save_csv(path, rows):
    if not rows:
        raise ValueError("No results to save")

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=rows[0].keys()
        )
        writer.writeheader()
        writer.writerows(rows)


save_csv(
    RESULT / "b9_payload_manifest.csv",
    payload_manifest
)

save_csv(
    RESULT / "b9_payload_roundtrip_results.csv",
    roundtrip_results
)

extraction_pass = all(
    r["extraction_exact"] and r["packet_lengths_preserved"]
    for r in payload_manifest
)

pcm_pass = all(
    r["pcm_identical"]
    and r["baseline_rc"] == 0
    and r["modified_rc"] == 0
    and r["baseline_pcm_bytes"] == r["modified_pcm_bytes"]
    for r in roundtrip_results
)

print("\n========== B9 PAYLOAD ROUNDTRIP AUDIT ==========")
print("Payload events:", len(payload_manifest))
print("Extraction successes:", sum(
    r["extraction_exact"] for r in payload_manifest
))
print("Packet framing successes:", sum(
    r["packet_lengths_preserved"] for r in payload_manifest
))
print("Decoder comparisons:", len(roundtrip_results))
print("Exact PCM matches:", sum(
    r["pcm_identical"] for r in roundtrip_results
))

print("Extraction:", "PASS" if extraction_pass else "FAIL")
print("PCM preservation:", "PASS" if pcm_pass else "FAIL")

print("\nResults:", RESULT)

if extraction_pass and pcm_pass:
    print("B9 END-TO-END PAYLOAD ROUNDTRIP: PASS")
else:
    raise SystemExit("B9 END-TO-END PAYLOAD ROUNDTRIP: FAIL")
