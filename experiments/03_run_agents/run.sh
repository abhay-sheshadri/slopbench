#!/bin/bash
# Launch pi research agents. Edit the config block below, then run it:
#   ./run.sh            # launch every (project x mode) run, concurrently, no timeout
#   ./run.sh --force    # wipe each run's output dir first
# Watch live or review with ./view_agents.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate

# ------------------------------- config ------------------------------------ #
PROJECTS=(
    # empirical_cot_controllability_steering_vectors
    # empirical_introspection_science
    # empirical_subliminal_backdoors
    empirical_prompted_false_facts
    empirical_slop_probes
    empirical_impossible_tasks_bullshitting
    empirical_emergent_collusion
    empirical_reasoning_recontextualization
    empirical_functional_emotions_wellbeing
    empirical_nla_auditbench_quirks
)
MODES=(multi_phase)
THINKING=xhigh
MODEL="anthropic/claude-opus-4-8"   # Claude Opus 4.8
# --------------------------------------------------------------------------- #

source scripts/run_cleanup.sh
install_run_cleanup_trap

ARGS=(--projects "${PROJECTS[@]}" --modes "${MODES[@]}" --thinking "$THINKING")
[ -n "$MODEL" ] && ARGS+=(--model "$MODEL")

exec python experiments/03_run_agents/run.py "${ARGS[@]}" "$@"
