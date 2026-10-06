# check_env.sh — capture environment and toolchain versions
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OPUS_SRC="$ROOT/opus"
TOOLS="$ROOT/scripts"        # encode_raw, decode_raw, *.py live here
DATA="$ROOT/data"

OUT="scripts/00_env/env_report.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Phase A Environment Report ==="
  echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Host: $(uname -a)"
  echo
  echo "--- Working directory ---"
  pwd
  echo
  echo "--- Toolchain ---"
  for t in gcc clang make autoconf automake libtool pkg-config python3 pip3 git; do
    if command -v "$t" >/dev/null 2>&1; then
      printf "%-12s %s\n" "$t" "$($t --version 2>&1 | head -n1)"
    else
      printf "%-12s NOT FOUND\n" "$t"
    fi
  done
  echo
  echo "--- Python packages ---"
  python3 - <<'PY'
import importlib
for m in ("numpy", "scipy", "soundfile", "matplotlib"):
    try:
        mod = importlib.import_module(m)
        print(f"{m:12s} {getattr(mod, '__version__', 'unknown')}")
    except Exception as e:
        print(f"{m:12s} NOT INSTALLED ({e})")
PY
  echo
  echo "--- Disk usage ---"
  df -h .
  echo
  echo "--- CPU ---"
  (lscpu 2>/dev/null || sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "unknown")
} | tee "$OUT"

echo "Wrote $OUT"
