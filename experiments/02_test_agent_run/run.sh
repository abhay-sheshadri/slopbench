#!/bin/bash
# Smoke test: run the api-key proposal through the pi agent in a bwrap sandbox.
# All flags pass through to run.py, e.g.:
#   ./run.sh --force                 # wipe + run
# Watch live or review with ./view_agents.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate
source scripts/run_cleanup.sh
install_run_cleanup_trap
exec python experiments/02_test_agent_run/run.py "$@"
