#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ " $* " != *" --list "* ]]; then
  rm -rf outputs/01_eval_planning
fi

PYTHONUNBUFFERED=1 python experiments/01_eval_planning/run.py \
  --max-concurrent "${MAX_CONCURRENT:-50}" \
  --force \
  "$@"
