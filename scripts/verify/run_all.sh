#!/usr/bin/env bash
# run_all.sh — run every experiment in order, log to verify/
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/verify"
mkdir -p "$LOG_DIR"
MASTER_LOG="$LOG_DIR/run_all.log"

{
  echo "########## END-TO-END VERIFICATION ##########"
  echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
} | tee "$MASTER_LOG"

# --- Preconditions ---
echo ">>> Preconditions" | tee -a "$MASTER_LOG"

if [ ! -f opus/.libs/libopus.a ]; then
  echo "  FAIL: opus/.libs/libopus.a not found. Build opus first." | tee -a "$MASTER_LOG"
  exit 1
fi
echo "  [ok] libopus built" | tee -a "$MASTER_LOG"

if [ ! -x scripts/encode_raw ] || [ ! -x scripts/decode_raw ]; then
  echo "  FAIL: encode_raw or decode_raw missing." | tee -a "$MASTER_LOG"
  exit 1
fi
echo "  [ok] encode_raw / decode_raw built" | tee -a "$MASTER_LOG"

mkdir -p data/pcm
if ! ls data/pcm/spontaneous-speech-en-*.pcm >/dev/null 2>&1; then
  echo "  FAIL: speech PCMs not found. Run prepare script." | tee -a "$MASTER_LOG"
  exit 1
fi
N_SPEECH=$(ls data/pcm/spontaneous-speech-en-*.pcm | wc -l)
echo "  [ok] speech corpus: $N_SPEECH files" | tee -a "$MASTER_LOG"

MUSIC_AVAILABLE=0
if ls data/pcm/music/*.pcm >/dev/null 2>&1; then
  N_MUSIC=$(ls data/pcm/music/*.pcm | wc -l)
  echo "  [ok] music corpus: $N_MUSIC files" | tee -a "$MASTER_LOG"
  MUSIC_AVAILABLE=1
else
  echo "  [skip] music corpus not present (B7 will be skipped)" | tee -a "$MASTER_LOG"
fi

LIBRI_AVAILABLE=0
if ls data/pcm/librispeech/*.pcm >/dev/null 2>&1; then
  N_LIBRI=$(ls data/pcm/librispeech/*.pcm | wc -l)
  echo "  [ok] librispeech corpus: $N_LIBRI files" | tee -a "$MASTER_LOG"
  LIBRI_AVAILABLE=1
else
  echo "  [skip] librispeech corpus not present (B8 will be skipped)" | tee -a "$MASTER_LOG"
fi

FAILED=0

run() {
  local name="$1"
  local script="$2"
  echo | tee -a "$MASTER_LOG"
  echo ">>> $name" | tee -a "$MASTER_LOG"

  if [ ! -f "$script" ]; then
    echo "  [skip] $script not found" | tee -a "$MASTER_LOG"
    return
  fi

  if bash "$script" 2>&1 | tee -a "$MASTER_LOG"; then
    echo "  [ok]" | tee -a "$MASTER_LOG"
  else
    echo "  [FAILED: exit $?]" | tee -a "$MASTER_LOG"
    FAILED=$((FAILED + 1))
  fi
}

analyze() {
  local name="$1"
  local script="$2"
  echo | tee -a "$MASTER_LOG"
  echo ">>> $name (analysis)" | tee -a "$MASTER_LOG"

  if [ ! -f "$script" ]; then
    echo "  [skip] $script not found" | tee -a "$MASTER_LOG"
    return
  fi

  if python3 "$script" 2>&1 | tee -a "$MASTER_LOG"; then
    echo "  [ok]" | tee -a "$MASTER_LOG"
  else
    echo "  [FAILED: exit $?]" | tee -a "$MASTER_LOG"
    FAILED=$((FAILED + 1))
  fi
}

# --- B0: mechanism ---
run "B0 — Decisive experiment" experiments/B0_decisive/reproduce.sh
analyze "B0" experiments/B0_decisive/analyze.py

# --- B1: one-shot ---
run "B1 — Multi-transition test" experiments/B1_multitransition/reproduce.sh

# --- B2: trigger window ---
run "B2 — One-shot sweep" experiments/B2_oneshot_sweep/reproduce.sh

# --- B3: tail scaling ---
run "B3 — Tail scaling" experiments/B3_tail_scaling/reproduce.sh

# --- B4: payload demo ---
run "B4 — Payload demonstration" experiments/B4_payload/reproduce.sh

# --- B5: version comparison (informational — uses current opus tree) ---
echo | tee -a "$MASTER_LOG"
echo ">>> B5 — Version comparison (informational)" | tee -a "$MASTER_LOG"
echo "  note: uses the currently built opus tree" | tee -a "$MASTER_LOG"
echo "  note: see experiments/B5_versions/README.md for prior 1.5.2 vs 1.6.1 comparison" | tee -a "$MASTER_LOG"

# --- B6: steganalysis ---
run "B6 — Steganalysis S2" experiments/B6_steganalysis/reproduce_s2.sh
analyze "B6 S2" experiments/B6_steganalysis/analyze_s2.py
run "B6 — Steganalysis S3" experiments/B6_steganalysis/reproduce_s3.sh
analyze "B6 S3" experiments/B6_steganalysis/analyze_s3.py
analyze "B6 S4" experiments/B6_steganalysis/analyze_s4.py

# --- B7: music (skip if not present) ---
if [ "$MUSIC_AVAILABLE" -eq 1 ]; then
  run "B7 — Music content" experiments/B7_music/reproduce.sh
else
  echo | tee -a "$MASTER_LOG"
  echo ">>> B7 — Music (skipped)" | tee -a "$MASTER_LOG"
fi

# --- B8: librispeech (skip if not present) ---
if [ "$LIBRI_AVAILABLE" -eq 1 ]; then
  run "B8 — LibriSpeech content" experiments/B8_librispeech/reproduce.sh
else
  echo | tee -a "$MASTER_LOG"
  echo ">>> B8 — LibriSpeech (skipped)" | tee -a "$MASTER_LOG"
fi

echo | tee -a "$MASTER_LOG"
echo "########## COMPLETE ##########" | tee -a "$MASTER_LOG"
echo "Failures: $FAILED" | tee -a "$MASTER_LOG"
echo "Log: $MASTER_LOG" | tee -a "$MASTER_LOG"

if [ "$FAILED" -gt 0 ]; then
  exit 1
fi