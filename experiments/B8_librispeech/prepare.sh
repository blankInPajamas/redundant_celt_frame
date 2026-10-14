#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LIBRI_ROOT="$ROOT/data/raw/librispeech"
OUT_DIR="$ROOT/data/pcm/librispeech"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$OUT_DIR"

N_FILES=20

echo "Scanning for FLAC files under $LIBRI_ROOT..."
mapfile -t all_flacs < <(find "$LIBRI_ROOT" -name '*.flac' | sort)
echo "Found ${#all_flacs[@]} FLAC files"

if [ ${#all_flacs[@]} -eq 0 ]; then
  echo "ERROR: no FLAC files found under $LIBRI_ROOT" >&2
  exit 1
fi

# Group FLACs by chapter (from filename prefix)
declare -A chapter_flacs
for f in "${all_flacs[@]}"; do
  base=$(basename "$f" .flac)
  chapter="${base%-*}"
  chapter_flacs["$chapter"]+="$f "
done

echo "Found ${#chapter_flacs[@]} chapters"

mapfile -t chapters < <(printf '%s\n' "${!chapter_flacs[@]}" | sort)

count=0
for chapter in "${chapters[@]}"; do
  [ "$count" -ge "$N_FILES" ] && break

  read -ra flacs <<< "${chapter_flacs[$chapter]}"
  [ ${#flacs[@]} -ge 3 ] || continue

  take=("${flacs[@]:0:5}")

  tmp_pcms=()
  for u in "${take[@]}"; do
    base=$(basename "$u" .flac)
    pcm="$TMPDIR/${base}.pcm"
    ffmpeg -y -loglevel error -i "$u" -ac 1 -ar 48000 -f s16le "$pcm" || continue
    tmp_pcms+=("$pcm")
  done
  [ ${#tmp_pcms[@]} -ge 3 ] || continue

  out="$OUT_DIR/ls_${chapter}.pcm"
  > "$out"
  for pcm in "${tmp_pcms[@]}"; do
    cat "$pcm" >> "$out"
  done

  target=$((30 * 48000 * 2))
  size=$(stat -c%s "$out")
  if [ "$size" -gt "$target" ]; then
    head -c "$target" "$out" > "$out.tmp" && mv "$out.tmp" "$out"
  fi

  count=$((count + 1))
  echo "  [$count/$N_FILES] $chapter → $(basename "$out") ($(stat -c%s "$out") bytes)"
done

echo
echo "Generated $count files in $OUT_DIR"