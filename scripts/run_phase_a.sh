#!/usr/bin/env bash
set -uo pipefail        # NOTE: no -e; we handle errors explicitly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export ROOT

LOG="$ROOT/logs/phase_a/phase_a_run.log"
mkdir -p "$ROOT/logs/phase_a"

echo "########## PHASE A: CONSOLIDATION ##########" | tee "$LOG"
date -u | tee -a "$LOG"
echo | tee -a "$LOG"

FAILED=0
run() {
  echo ">>> $1" | tee -a "$LOG"
  if bash "$SCRIPT_DIR/$1" 2>&1 | tee -a "$LOG"; then
    echo "  [ok]" | tee -a "$LOG"
  else
    rc=$?
    echo "  [FAILED: exit $rc]" | tee -a "$LOG"
    FAILED=$((FAILED+1))
  fi
  echo | tee -a "$LOG"
}

run 00_env/check_env.sh
run 01_inventory/inventory_tree.sh
run 01_inventory/inventory_opus.sh
run 01_inventory/inventory_inputs.sh
run 01_inventory/inventory_logs.sh
run 02_build/check_build.sh
run 02_build/check_instrumentation.sh
run 02_build/fix_libopus_binding.sh
run 03_reproduce/reproduce_32k_audio.sh
run 03_reproduce/verify_32k_audio.sh
run 04_tools/check_python_tools.sh
run 04_tools/smoke_test_pipeline.sh
run 05_freeze/make_patch.sh
run 05_freeze/checksums.sh
run 05_freeze/snapshot_tree.sh

echo "########## PHASE A COMPLETE ##########" | tee -a "$LOG"
echo "Failures: $FAILED" | tee -a "$LOG"
echo "Full log: $LOG" | tee -a "$LOG"