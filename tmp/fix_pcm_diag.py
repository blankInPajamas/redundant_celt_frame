#!/usr/bin/env python3
"""Replace the broken RED_PCM diagnostic with a type-aware version."""
import pathlib, re, sys

FILE = pathlib.Path("opus/src/opus_encoder.c")
if not FILE.exists():
    print("ERROR: run from project root")
    sys.exit(1)

src = FILE.read_text()

# Match the existing RED_PCM block (between the comment markers)
pattern = re.compile(
    r'/\* --- RED_PCM DIAGNOSTIC --- \*/.*?/\* --- END RED_PCM DIAGNOSTIC --- \*/',
    re.DOTALL
)

if pattern.search(src) is None:
    print("ERROR: existing RED_PCM diagnostic not found.")
    print("Check with: grep -n 'RED_PCM' opus/src/opus_encoder.c")
    sys.exit(1)

NEW_DIAG = '''/* --- RED_PCM DIAGNOSTIC --- */
        {
            int _n = st->Fs/200;
            int _ch = st->channels;
            int _total = _n * _ch;
            double _sum_sq = 0.0;
            double _peak_d = 0.0;
            int _k;
            for (_k = 0; _k < _total; _k++) {
                /* opus_val16 is either opus_int16 or float depending on
                   FIXED_POINT; read as double to be correct for both. */
                double _d = (double)pcm_buf[_k];
                _sum_sq += _d * _d;
                double _a = _d < 0.0 ? -_d : _d;
                if (_a > _peak_d) _peak_d = _a;
            }
            double _rms = (_total > 0) ? sqrt(_sum_sq / (double)_total) : 0.0;
            /* Also dump first 4 samples so we can see the scale */
            fprintf(stderr,
                "  -> RED_PCM: samples=%d rms=%.6f peak=%.6f "
                "sample0=%.6f sample1=%.6f sample2=%.6f sample3=%.6f\\n",
                _total, _rms, _peak_d,
                (double)pcm_buf[0], (double)pcm_buf[1],
                (double)pcm_buf[2], (double)pcm_buf[3]);
        }
        /* --- END RED_PCM DIAGNOSTIC --- */'''

src = pattern.sub(NEW_DIAG, src)
FILE.write_text(src)
print("[OK] diagnostic replaced with type-aware version")

check = FILE.read_text()
if 'rms=%.6f' in check:
    print("[OK] new format present")
else:
    print("[MISSING] new format")
    sys.exit(2)