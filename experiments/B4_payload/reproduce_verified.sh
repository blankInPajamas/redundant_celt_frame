#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$ROOT/experiments/B4_payload"

PCM="$ROOT/data/pcm/spontaneous-speech-en-1.pcm"

ENCODER="$ROOT/scripts/encode_raw_1.6.1"
DECODER="$ROOT/scripts/decode_raw_1.6.1"

MESSAGE="HybridModeOfOpus:CELT+SILK"
TARGET_FRAME=3
FRAME_SIZE=960

RUN_ID="$(date +%Y%m%d_%H%M%S)"

OUT="$ROOT/logs/phase_b/B4_verified_1.6.1_$RUN_ID"

mkdir -p "$OUT"

echo "========== B4 VERIFIED REPRODUCTION =========="

for f in "$PCM" "$ENCODER" "$DECODER"; do
    if [ ! -f "$f" ]; then
        echo "Missing file: $f"
        exit 1
    fi
done

if [ ! -x "$ENCODER" ] || [ ! -x "$DECODER" ]; then
    echo "Encoder or decoder is not executable."
    exit 1
fi

export LD_LIBRARY_PATH="$ROOT/opus/.libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

echo "Encoder: $ENCODER"
echo "Decoder: $DECODER"
echo "Target frame: $TARGET_FRAME"
echo "Message: $MESSAGE"

ldd "$ENCODER" > "$OUT/encoder_dependencies.txt" 2>&1 || true
ldd "$DECODER" > "$OUT/decoder_dependencies.txt" 2>&1 || true

echo
echo "========== 1. ENCODING =========="

"$ENCODER" \
    "$PCM" \
    "$OUT/original.bin" \
    audio 32000 10 0 0 \
    2> "$OUT/encode.log"

echo "Encoding completed."

echo
echo "========== 2. BASELINE DECODING =========="

"$DECODER" \
    "$OUT/original.bin" \
    "$OUT/baseline.pcm" \
    2> "$OUT/decode_baseline.log"

echo "Baseline decoding completed."

echo
echo "========== 3. EMBEDDING =========="

python3 "$SCRIPT_DIR/embed.py" \
    "$OUT/original.bin" \
    "$OUT/modified.bin" \
    "$MESSAGE" \
    "$TARGET_FRAME" \
    2>&1 | tee "$OUT/embed.log"

echo
echo "========== 4. PAYLOAD EXTRACTION =========="

python3 "$SCRIPT_DIR/extract_verified.py" \
    "$OUT/modified.bin" \
    > "$OUT/recovered.txt" \
    2> "$OUT/extract.log"

printf '%s' "$MESSAGE" > "$OUT/expected.txt"

cat "$OUT/extract.log"

echo
echo "========== 5. MODIFIED STREAM DECODING =========="

"$DECODER" \
    "$OUT/modified.bin" \
    "$OUT/modified.pcm" \
    2> "$OUT/decode_modified.log"

echo "Modified decoding completed."

echo
echo "========== 6. INTEGRITY VALIDATION =========="

OUT="$OUT" \
TARGET_FRAME="$TARGET_FRAME" \
MESSAGE="$MESSAGE" \
FRAME_SIZE="$FRAME_SIZE" \
PCM="$PCM" \
python3 - <<'PY'

import os
import struct
import sys
from pathlib import Path

out = Path(os.environ["OUT"])
target = int(os.environ["TARGET_FRAME"])
message = os.environ["MESSAGE"].encode("ascii")
frame_size = int(os.environ["FRAME_SIZE"])

def load_packets(path):

    data = Path(path).read_bytes()

    packets = []
    offset = 0

    while offset < len(data):

        if offset + 4 > len(data):
            raise ValueError("Incomplete packet header")

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length == 0 or offset + length > len(data):
            raise ValueError("Invalid packet framing")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


original = load_packets(out / "original.bin")
modified = load_packets(out / "modified.bin")

baseline_pcm = (out / "baseline.pcm").read_bytes()
modified_pcm = (out / "modified.pcm").read_bytes()

expected = (out / "expected.txt").read_bytes()
recovered = (out / "recovered.txt").read_bytes()

source_bytes = Path(os.environ["PCM"]).stat().st_size

if source_bytes % 2:
    raise ValueError("Input PCM has an odd byte count")

source_samples = source_bytes // 2
decoded_samples = len(baseline_pcm) // 2

changed = [
    i for i, (a, b) in enumerate(zip(original, modified))
    if a != b
]

packet_count_equal = len(original) == len(modified)

packet_lengths_equal = (
    packet_count_equal
    and all(
        len(a) == len(b)
        for a, b in zip(original, modified)
    )
)

single_target_changed = changed == [target]

recovery_exact = recovered == expected == message

pcm_identical = baseline_pcm == modified_pcm

decoded_length_valid = (
    len(baseline_pcm) % 2 == 0
    and decoded_samples == len(original) * frame_size
)

frame_count_valid = (
    len(original) == source_samples // frame_size
)

checks = {
    "Packet count equal": packet_count_equal,
    "Packet lengths equal": packet_lengths_equal,
    "Only target packet changed": single_target_changed,
    "Payload recovered exactly": recovery_exact,
    "Decoded PCM bit-identical": pcm_identical,
    "Decoded sample count valid": decoded_length_valid,
    "Complete frame count valid": frame_count_valid,
}

print("Original packets:", len(original))
print("Modified packets:", len(modified))
print("Changed packet indices:", changed)
print("Input samples:", source_samples)
print("Decoded samples:", decoded_samples)
print("Unencoded input remainder:", source_samples % frame_size)

print("\nValidation results:")

for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")

report = [
    "B4 VERIFIED REPRODUCTION",
    f"Packets: {len(original)}",
    f"Changed packets: {changed}",
    f"Input samples: {source_samples}",
    f"Decoded samples: {decoded_samples}",
    f"Unencoded remainder: {source_samples % frame_size}",
    f"Recovered message: {recovered.decode('ascii', errors='replace')}",
    "",
]

report.extend(
    f"{'PASS' if passed else 'FAIL'}: {name}"
    for name, passed in checks.items()
)

(out / "verification_summary.txt").write_text(
    "\n".join(report) + "\n"
)

if not all(checks.values()):
    print("\nB4 VALIDATION FAILED.")
    sys.exit(1)

print("\nB4 VALIDATION SUCCESSFUL.")

PY

echo
echo "========== B4 REPRODUCTION FINISHED =========="

echo "Results saved in:"
echo "$OUT"

