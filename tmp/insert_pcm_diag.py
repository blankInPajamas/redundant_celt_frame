#!/usr/bin/env python3
"""Insert PCM measurement diagnostic immediately before the redundant CELT encode."""
import pathlib, shutil, sys

FILE = pathlib.Path("opus/src/opus_encoder.c")
BACKUP = pathlib.Path("/tmp/opus_encoder_before_pcm_diag.c")

if not FILE.exists():
    print("ERROR: run from project root")
    sys.exit(1)

src = FILE.read_text()

MARKER = 'err = celt_encode_with_ec(celt_enc, pcm_buf, st->Fs/200, data+nb_compr_bytes, redundancy_bytes, NULL);'

if 'RED_PCM:' in src:
    print("Already instrumented. Skipping.")
    sys.exit(0)

if MARKER not in src:
    print("ERROR: target line not found. The source may have drifted.")
    print("Find it manually with:")
    print("  grep -n 'celt_encode_with_ec(celt_enc, pcm_buf, st->Fs/200' opus/src/opus_encoder.c")
    sys.exit(1)

# Backup once
if not BACKUP.exists():
    shutil.copy2(FILE, BACKUP)
    print(f"Backup: {BACKUP}")

DIAG = '''        /* --- RED_PCM DIAGNOSTIC --- */
        {
            int _n = st->Fs/200;
            int _ch = st->channels;
            double _sum_sq = 0.0;
            int _peak = 0;
            int _k;
            for (_k = 0; _k < _n*_ch; _k++) {
                int _s = pcm_buf[_k];
                _sum_sq += (double)_s * (double)_s;
                int _a = _s < 0 ? -_s : _s;
                if (_a > _peak) _peak = _a;
            }
            double _rms = (_n*_ch > 0) ? sqrt(_sum_sq / (double)(_n*_ch)) : 0.0;
            fprintf(stderr, "  -> RED_PCM: samples=%d rms=%.2f peak=%d\\n",
                    _n*_ch, _rms, _peak);
        }
        /* --- END RED_PCM DIAGNOSTIC --- */
'''

# Insert the diagnostic immediately BEFORE the marker line
# but preserve the leading indentation of the marker line.
lines = src.splitlines(keepends=True)
out = []
inserted = False
for line in lines:
    if not inserted and MARKER in line:
        # Preserve the leading whitespace of the target line
        leading = line[:len(line) - len(line.lstrip())]
        # DIAG already has 8-space indentation, adjust if needed
        out.append(DIAG)
        inserted = True
    out.append(line)

FILE.write_text(''.join(out))
print("Instrumentation inserted.")

# Verify
check = FILE.read_text()
if 'RED_PCM:' in check:
    print("[OK] RED_PCM diagnostic present")
else:
    print("[MISSING] RED_PCM diagnostic not found")
    sys.exit(2)