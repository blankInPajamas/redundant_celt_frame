#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

OPUS_SRC="$ROOT/opus"
OUT="$ROOT/patches/opus_encoder_instrumentation_from_worktree.patch"

if [ -d "$OPUS_SRC/.git" ]; then
  (cd "$OPUS_SRC" && git diff) > "$OUT"
  echo "Wrote $OUT"
  wc -l "$OUT"
else
  echo "No git repo at $OPUS_SRC; cannot produce a patch."
fi