#!/usr/bin/env bash
# fix_libopus_binding.sh — rebuild encode_raw/decode_raw against the
# instrumented libopus, with RPATH so LD_LIBRARY_PATH is not needed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OPUS_SRC="$ROOT/opus"
TOOLS="$ROOT/scripts"

if [ ! -f "$OPUS_SRC/.libs/libopus.a" ]; then
  echo "ERROR: $OPUS_SRC/.libs/libopus.a not found. Build opus first."
  exit 1
fi

echo "=== Rebuilding encode_raw with static libopus.a ==="
gcc -O2 -g -o "$TOOLS/encode_raw" "$TOOLS/encode_raw.c" \
  -I "$OPUS_SRC/include" \
  "$OPUS_SRC/.libs/libopus.a" \
  -lm

echo "=== Rebuilding decode_raw with static libopus.a ==="
gcc -O2 -g -o "$TOOLS/decode_raw" "$TOOLS/decode_raw.c" \
  -I "$OPUS_SRC/include" \
  "$OPUS_SRC/.libs/libopus.a" \
  -lm

echo
echo "=== Verify linkage (should show no libopus.so) ==="
ldd "$TOOLS/encode_raw" | grep -i opus || echo "OK: no dynamic libopus"
ldd "$TOOLS/decode_raw" | grep -i opus || echo "OK: no dynamic libopus"

echo
echo "=== Smoke test: confirm instrumentation fires ==="
"$TOOLS/encode_raw" "$ROOT/data/pcm/silence.pcm" /tmp/_smoke.bin audio 32000 \
  2> /tmp/_smoke.log || true
if grep -q 'FINAL packet\|REDUNDANCY' /tmp/_smoke.log; then
  echo "OK: instrumentation is live"
else
  echo "WARNING: no instrumentation output. Check that opus was rebuilt."
fi
rm -f /tmp/_smoke.bin /tmp/_smoke.log