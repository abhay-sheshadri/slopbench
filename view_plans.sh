#!/usr/bin/env bash
# Open the 01_eval_planning plan-review/scoring viewer.
#
# Serves the planner outputs (OVERALL_PLAN / phase instructions / rubrics) and
# transcripts for each planner attempt, with a 0-10 scoring + notes workflow.
#
# Usage:
#   ./view_plans.sh                 # serve on the default port
#   ./view_plans.sh --help          # viewer options
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Could not find python3 or python on PATH." >&2
  exit 1
fi
exec "$PYTHON_BIN" experiments/01_eval_planning/viewer.py "$@"
