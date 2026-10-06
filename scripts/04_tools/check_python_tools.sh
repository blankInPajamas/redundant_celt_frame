#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
LOG_DIR="$ROOT/logs/phase_a"
mkdir -p "$LOG_DIR"

OUT="$LOG_DIR/python_tools_check.txt"
TOOLS="$ROOT/scripts"

{
  echo "=== Python tools check ==="
  echo "ROOT=$ROOT"
  echo "TOOLS=$TOOLS"
  echo

  for t in parse_packets.py automate.py modify_packet.py parse_bitstream.py; do
    f="$TOOLS/$t"
    if [ -f "$f" ]; then
      echo "FOUND: $f"
      echo "--- head ---"
      head -n 25 "$f"
      echo "--- syntax check ---"
      python3 -m py_compile "$f" && echo "OK" || echo "SYNTAX ERROR"
      echo "--- imports check ---"
      python3 - "$f" <<'PY' || true
import ast, sys
src = open(sys.argv[1]).read()
tree = ast.parse(src)
mods = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for n in node.names:
            mods.add(n.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            mods.add(node.module.split('.')[0])
print("imports:", sorted(mods))
PY
      echo
    else
      echo "MISSING: $f"
      echo
    fi
  done
} | tee "$OUT"

echo "Wrote $OUT"