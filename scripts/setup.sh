#!/usr/bin/env bash
# setup.sh — bootstrap the redundant_celt_frame_steganography environment
#
# Usage:
#   ./setup.sh              # full setup: clone, patch, build, compile, verify
#   ./setup.sh --skip-clone # reuse an existing opus/ checkout (re-patch + rebuild only)
#
# Requires: git, autoconf, automake, libtool, pkg-config, gcc, ffmpeg, python3

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPUS_DIR="$PROJECT_ROOT/opus"
PATCH_FILE="$PROJECT_ROOT/patches/0001-redundancy-instrumentation.patch"
# Pin the exact commit this project was built and validated against.
# Update this if you intentionally move to a newer libopus revision —
# but note the paper's results are tied to this exact commit.
OPUS_COMMIT="503d81b1"

SKIP_CLONE=0
if [[ "${1:-}" == "--skip-clone" ]]; then
    SKIP_CLONE=1
fi

echo "== 1. Checking required tools =="
for tool in git autoconf automake libtool pkg-config gcc ffmpeg python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: required tool '$tool' not found on PATH." >&2
        exit 1
    fi
done
echo "  all required tools present."

echo "== 2. Cloning libopus =="
if [[ "$SKIP_CLONE" -eq 0 ]]; then
    if [[ -d "$OPUS_DIR" ]]; then
        echo "  opus/ already exists — removing for a clean clone."
        rm -rf "$OPUS_DIR"
    fi
    git clone https://gitlab.xiph.org/xiph/opus.git "$OPUS_DIR"
    (cd "$OPUS_DIR" && git checkout "$OPUS_COMMIT")
else
    echo "  --skip-clone passed, reusing existing opus/ checkout."
fi

CURRENT_COMMIT="$(cd "$OPUS_DIR" && git rev-parse --short HEAD)"
if [[ "$CURRENT_COMMIT" != "$OPUS_COMMIT"* ]]; then
    echo "  WARNING: opus/ is at $CURRENT_COMMIT, expected $OPUS_COMMIT." >&2
    echo "  Results may not match the paper's reported figures." >&2
fi

echo "== 3. Applying instrumentation patch =="
cd "$OPUS_DIR"
if git apply --check "$PATCH_FILE" 2>/dev/null; then
    git apply "$PATCH_FILE"
    echo "  patch applied cleanly."
else
    echo "  ERROR: patch did not apply cleanly against this libopus commit." >&2
    echo "  This usually means upstream opus_encoder.c has diverged from" >&2
    echo "  the line numbers the patch expects. Re-generate the patch against" >&2
    echo "  commit $OPUS_COMMIT, or manually re-apply the instrumentation" >&2
    echo "  described in README.md Section 5." >&2
    exit 1
fi

echo "== 4. Building libopus =="
./autogen.sh
./configure
make -j"$(nproc)"
cd "$PROJECT_ROOT"

echo "== 5. Compiling encode_raw / decode_raw =="
export LD_LIBRARY_PATH="$OPUS_DIR/.libs:${LD_LIBRARY_PATH:-}"
gcc -O2 -o scripts/encode_raw scripts/encode_raw.c \
    -I "$OPUS_DIR/include" -L "$OPUS_DIR/.libs" -lopus -lm
gcc -O2 -o scripts/decode_raw scripts/decode_raw.c \
    -I "$OPUS_DIR/include" -L "$OPUS_DIR/.libs" -lopus -lm
echo "  encode_raw / decode_raw built."

echo "== 6. Verifying instrumentation is live =="
mkdir -p data/pcm data/bitstreams/encoded data/bitstreams/modified data/output logs
ffmpeg -y -f lavfi -i "sine=frequency=1000:duration=1" -f s16le -acodec pcm_s16le -ar 48000 -ac 1 \
    data/pcm/_setup_check.pcm -loglevel error
./scripts/encode_raw data/pcm/_setup_check.pcm data/bitstreams/encoded/_setup_check.bin audio 32000 \
    2> logs/_setup_check.log || true
if grep -q "FINAL packet" logs/_setup_check.log; then
    echo "  instrumentation confirmed live (FINAL packet log line found)."
else
    echo "  WARNING: expected 'FINAL packet' log line not found." >&2
    echo "  Check that the patch applied and libopus rebuilt correctly." >&2
fi
rm -f data/pcm/_setup_check.pcm data/bitstreams/encoded/_setup_check.bin logs/_setup_check.log

echo ""
echo "== Setup complete =="
echo "Remember to export before running any pipeline script in a new shell:"
echo "  export LD_LIBRARY_PATH=\$PWD/opus/.libs:\$LD_LIBRARY_PATH"
echo ""
echo "Dataset note: data/raw/ (Mozilla Spontaneous Speech 5.0 MP3s) is NOT"
echo "fetched by this script — see data/README.md for the download source"
echo "and the ffmpeg conversion commands in README.md Section 4.2."
