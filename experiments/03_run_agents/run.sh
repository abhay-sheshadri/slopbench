#!/bin/bash
# Run pi research agents on proposals in bwrap sandboxes — both modes (goal +
# multi_phase) by default. All flags pass through to run.py, e.g.:
#   ./run.sh --list
#   ./run.sh --proposals empirical_slop_probes --force
#   ./run.sh --proposals empirical_slop_probes --modes goal --max-concurrent 1
# Watch live or review with ./view_agents.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate
source scripts/run_cleanup.sh
install_run_cleanup_trap
exec python experiments/03_run_agents/run.py "$@"
