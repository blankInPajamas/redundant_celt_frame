#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export ROOT

echo "Project root: $ROOT"
echo

mkdir -p "$ROOT/logs/phase_a"

echo "########## PHASE A: CONSOLIDATION ##########"
date -u
echo

run() {
  echo ">>> $1"
  bash "$SCRIPT_DIR/$1"
  echo
}

run 00_env/check_env.sh
run 01_inventory/inventory_tree.sh
run 01_inventory/inventory_opus.sh
run 01_inventory/inventory_inputs.sh
run 01_inventory/inventory_logs.sh
run 02_build/check_build.sh
run 02_build/check_instrumentation.sh
run 02_build/fix_libopus_binding.sh       # NEW
run 03_reproduce/reproduce_32k_audio.sh
run 03_reproduce/verify_32k_audio.sh
run 04_tools/check_python_tools.sh
run 04_tools/smoke_test_pipeline.sh
run 05_freeze/make_patch.sh
run 05_freeze/checksums.sh
run 05_freeze/snapshot_tree.sh

echo "########## PHASE A COMPLETE ##########"