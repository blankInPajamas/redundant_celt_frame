#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "== 1. Check opus tree state =="
cd "$ROOT/opus"
git diff --stat
grep -c 'frame_id' src/opus_encoder.c || echo "0 (patch 0002 not applied)"

echo
echo "== 2. Attempting to apply patch 0002 =="
if grep -q 'frame_id' src/opus_encoder.c; then
  echo "Patch 0002 already applied."
else
  if git apply --check "$ROOT/patches/0002-fix-frame-correlation.patch" 2>/dev/null; then
    git apply "$ROOT/patches/0002-fix-frame-correlation.patch"
    echo "Applied patch 0002 cleanly."
  else
    echo "Patch 0002 does NOT apply cleanly. Manual edit required (see instructions)."
    exit 1
  fi
fi
grep -n 'frame_id' src/opus_encoder.c

echo
echo "== 3. Rebuild opus =="
make -j"$(nproc)" >/dev/null

echo
echo "== 4. Rebuild encode_raw / decode_raw =="
cd "$ROOT"
bash scripts/02_build/fix_libopus_binding.sh

echo
echo "== 5. Verify new log format =="
"$ROOT/scripts/encode_raw" "$ROOT/data/pcm/silence.pcm" /tmp/_repair_check.bin audio 32000 \
  2> /tmp/_repair_check.log || true
grep -E 'frame_id|FINAL' /tmp/_repair_check.log | head -n 5
rm -f /tmp/_repair_check.bin /tmp/_repair_check.log

echo
echo "== Repair complete =="
echo "Next: rerun reproduce_32k_audio.sh, then verify_32k_audio.sh"