#!/usr/bin/env bash
# rebuild.sh — clean rebuild of libopus + custom tools
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

echo "=== Rebuilding libopus ==="
if [ -f autogen.sh ]; then
  ./autogen.sh
fi
./configure --enable-custom-modes 2>&1 | tee logs/phase_a/configure.log
make clean
make -j"$(nproc 2>/dev/null || echo 4)" 2>&1 | tee logs/phase_a/make.log

echo
echo "=== Rebuilding encode_raw / decode_raw ==="
# Adjust these flags to match your original build
CC=${CC:-gcc}
CFLAGS="-I. -Iinclude -O2 -g"
LIBS=".libs/libopus.a -lm"

$CC $CFLAGS -o encode_raw encode_raw.c $LIBS 2>&1 | tee logs/phase_a/build_encode_raw.log
$CC $CFLAGS -o decode_raw decode_raw.c $LIBS 2>&1 | tee logs/phase_a/build_decode_raw.log

echo "Rebuild complete."
ls -la encode_raw decode_raw 2>/dev/null || true
