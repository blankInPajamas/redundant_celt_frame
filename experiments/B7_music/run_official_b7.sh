#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/research/redundant_celt_frame_steganography"
SRC="$ROOT/data/raw/gtzan_official/genres_original"
BAD="$SRC/jazz/jazz.00054.wav"

OUT="$ROOT/logs/phase_b/B7_official_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$OUT/tmp"

for V in 1.5.2 1.6.1; do
    mkdir -p "$OUT/$V/bitstreams"
    mkdir -p "$OUT/$V/diagnostics"

    ENC="$ROOT/scripts/encode_raw_$V"

    if [[ ! -x "$ENC" ]]; then
        echo "ERROR: Missing executable: $ENC"
        exit 1
    fi

    if ! strings "$ENC" | grep 'RED_FINAL: frame=' >/dev/null; then
        echo "ERROR: Instrumentation missing in $ENC"
        exit 1
    fi
done

mapfile -d '' ALL_WAVS < <(
    find "$SRC" -type f -iname '*.wav' -print0 | sort -z
)

if [[ ${#ALL_WAVS[@]} -ne 1000 ]]; then
    echo "ERROR: Expected 1000 source WAVs; found ${#ALL_WAVS[@]}"
    exit 1
fi

WAVS=()

for WAV in "${ALL_WAVS[@]}"; do
    [[ "$WAV" == "$BAD" ]] && continue
    WAVS+=("$WAV")
done

if [[ ${#WAVS[@]} -ne 999 ]]; then
    echo "ERROR: Expected 999 valid WAVs."
    exit 1
fi

echo "Source recordings: ${#WAVS[@]}"
echo "Output: $OUT"

echo "id,genre,source_wav,pcm_sha256,pcm_bytes" \
    > "$OUT/input_manifest.csv"

echo "id,genre,version,frames,redundancy_events,celt_to_silk_events,successful_relocations,bitstream,diagnostics" \
    > "$OUT/summary.csv"

COUNT=0

for WAV in "${WAVS[@]}"; do

    REL="${WAV#"$SRC"/}"
    GENRE="${REL%%/*}"
    BASE="${REL##*/}"
    STEM="${BASE%.wav}"
    ID="${GENRE}__${STEM}"

    PCM="$OUT/tmp/$ID.pcm"

    ffmpeg -nostdin -y -v error \
        -i "$WAV" \
        -ac 1 -ar 48000 \
        -c:a pcm_s16le \
        -f s16le "$PCM"

    BYTES=$(stat -c%s "$PCM")

    if [[ "$BYTES" -eq 0 || $((BYTES % 2)) -ne 0 ]]; then
        echo "ERROR: Invalid PCM: $WAV"
        exit 1
    fi

    SHA=$(sha256sum "$PCM" | awk '{print $1}')

    printf '%s,%s,%s,%s,%s\n' \
        "$ID" "$GENRE" "$REL" "$SHA" "$BYTES" \
        >> "$OUT/input_manifest.csv"

    for V in 1.5.2 1.6.1; do

        ENC="$ROOT/scripts/encode_raw_$V"

        BIN="$OUT/$V/bitstreams/$ID.bin"
        DIAG="$OUT/$V/diagnostics/$ID.log"
        RAWLOG="$OUT/tmp/${ID}_${V}.stderr"

        echo "Encoding $ID | Opus $V"

        if "$ENC" "$PCM" "$BIN" audio 32000 2>"$RAWLOG"; then

            grep -E '^(REDUNDANCY:|RED_FINAL:)' \
                "$RAWLOG" > "$DIAG" || true

        else
            cp "$RAWLOG" "$OUT/$V/diagnostics/$ID.error.log"
            echo "ERROR: Encoding failed: $ID | $V"
            exit 1
        fi

        FRAMES=$(awk '/^RED_FINAL:/ {n++} END {print n+0}' "$DIAG")

        EVENTS=$(awk '/^REDUNDANCY:/ {n++} END {print n+0}' "$DIAG")

        C2S=$(awk '/^REDUNDANCY:/ && /celt_to_silk=1/ {n++} END {print n+0}' "$DIAG")

        MOVED=$(awk '/^RED_FINAL:/ && /moved=1/ {n++} END {print n+0}' "$DIAG")

        if [[ "$FRAMES" -eq 0 ]]; then
            echo "ERROR: No frame diagnostics: $ID | $V"
            exit 1
        fi

        printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
            "$ID" "$GENRE" "$V" "$FRAMES" \
            "$EVENTS" "$C2S" "$MOVED" \
            "$V/bitstreams/$ID.bin" \
            "$V/diagnostics/$ID.log" \
            >> "$OUT/summary.csv"

        rm -f "$RAWLOG"

    done

    rm -f "$PCM"

    COUNT=$((COUNT+1))

    if (( COUNT % 25 == 0 )); then
        echo "Progress: $COUNT / 999 recordings"
    fi

done

ROWS=$(($(wc -l < "$OUT/summary.csv") - 1))

echo
echo "========== B7 ENCODING COMPLETE =========="
echo "Recordings: $COUNT"
echo "Expected encoding runs: 1998"
echo "Completed encoding records: $ROWS"
echo "Results: $OUT"

if [[ "$ROWS" -ne 1998 ]]; then
    echo "ERROR: Incorrect number of encoding records."
    exit 1
fi

echo "B7 RUNNER VALIDATION PASSED"
