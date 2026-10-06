#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

DATE=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$ROOT/snapshots/phase_a_snapshot_${DATE}.tar.gz"
mkdir -p "$ROOT/snapshots"

tar --exclude='.venv' \
    --exclude='.git' \
    --exclude='.vscode' \
    --exclude='snapshots' \
    --exclude='*.o' --exclude='*.lo' --exclude='*.la' \
    --exclude='.libs' --exclude='.deps' \
    --exclude='opus/autom4te.cache' \
    -czf "$OUT" \
    -C "$ROOT" \
    data logs scripts patches drafts papers opus/src opus/celt opus/silk opus/include \
    README.md DRAFT.md 2>/dev/null

echo "Wrote $OUT"
ls -lh "$OUT"