#!/usr/bin/env bash
set -euo pipefail

TASK2_ROOT="${TASK2_ROOT:-/root/CMF/Task_2}"
DATA_ROOT="${DATA_ROOT:-/root/CMF/Task_1}"

cd "$TASK2_ROOT"

python src/task2_evaluate.py \
  --data-root "$DATA_ROOT" \
  --output-dir outputs \
  --start 2025-11-01 \
  --end 2026-04-29

