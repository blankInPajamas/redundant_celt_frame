#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

DATE=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$ROOT/snapshots/phase_a_snapshot_${DATE}.tar.gz"
mkdir -p "$ROOT/snapshots"

tar \
  --exclude='.git' \
  --exclude='*/opus/.git' \
  --exclude='*.o' \
  --exclude='*.lo' \
  --exclude='*.la' \
  --exclude='.libs' \
  --exclude='snapshots' \
  -czf "$OUT" \
  -C "$ROOT" \
  data logs scripts patches opus/src opus/celt opus/silk \
  README.md DRAFT.md drafts 2>/dev/null || \
tar -czf "$OUT" \
  --exclude='.git' --exclude='snapshots' \
  -C "$ROOT" .

echo "Wrote $OUT"
ls -lh "$OUT"