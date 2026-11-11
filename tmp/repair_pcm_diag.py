#!/usr/bin/env python3
"""Repair the broken RED_PCM string literal."""
import pathlib, re, sys

FILE = pathlib.Path("opus/src/opus_encoder.c")
if not FILE.exists():
    print("ERROR: run from project root")
    sys.exit(1)

content = FILE.read_text()

# The broken pattern: a real newline followed by optional whitespace and '",'
# Fix: replace with the escape sequence \n and the closing quote
pattern = re.compile(r'(sample3=%\.6f)\n\s*",')
new_content, n = pattern.subn(r'\1\\n",', content)

if n == 0:
    print("Pattern not found. Current state may differ.")
    print("Show lines around 2458-2463 with:")
    print("  sed -n '2455,2465p' opus/src/opus_encoder.c")
    sys.exit(1)

FILE.write_text(new_content)
print(f"[OK] repaired {n} broken string(s)")

# Verify the fix
check = FILE.read_text()
if 'sample3=%.6f\\n",' in check:
    print("[OK] repaired line present")
else:
    print("[WARN] expected repaired pattern not found")
    sys.exit(2)