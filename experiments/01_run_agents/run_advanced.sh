#!/bin/bash
# Launch advanced (full orchestrator) agent runs.
set -e
cd "$(dirname "$0")/../.."

# ── Configuration ──────────────────────────────────────
PROJECTS=(
    understanding_probe_generalization
)
K=4
PLANNER_MODEL="anthropic/claude-opus-4-7"
WORKER_MODEL="anthropic/claude-opus-4-7"
PHASE_PLANNER_MODEL=""              # defaults to PLANNER_MODEL
OUTPUT_DIR="outputs/01_run_agents"
TOKEN_LIMIT=""                     # token budget per agent, empty = no limit
TIME_LIMIT=21600                   # seconds per agent (6 hours)
MAX_PHASES=10
MAX_CONTINUATIONS=15
STALL_TIMEOUT=1800                 # kill step after 30 min of no activity (0 = disable)
PLANNING_ONLY=false
DISPLAY_MODE="full"                # full, conversation, rich, plain, none
# ───────────────────────────────────────────────────────

[ -f .venv/bin/activate ] && source .venv/bin/activate

cleanup() {
    echo "Cleaning up Docker containers..."
    docker ps --filter "name=inspect-" --format '{{.Names}}' | xargs -r docker rm -f 2>/dev/null
}
trap cleanup EXIT

# Each container is pinned to a 3g.40gb MIG slice; one slice per concurrent agent.
if [ ! -f .mig_uuids ]; then
    echo "ERROR: .mig_uuids not found. Run: bash scripts/enable_mig.sh" >&2
    exit 1
fi
NUM_MIG=$(wc -l < .mig_uuids)
MAX_SANDBOXES="$NUM_MIG"
echo "MIG slices available: $NUM_MIG (40 GB each, hardware-enforced)"
if [ "$K" -gt "$NUM_MIG" ]; then
    echo "ERROR: K=$K exceeds available MIG slices ($NUM_MIG)." >&2
    exit 1
fi

args=(advanced --projects "${PROJECTS[@]}" --k "$K" --planner-model "$PLANNER_MODEL" --worker-model "$WORKER_MODEL" --output-dir "$OUTPUT_DIR" --max-phases "$MAX_PHASES" --max-continuations "$MAX_CONTINUATIONS" --display "$DISPLAY_MODE")
args+=(--max-sandboxes "$MAX_SANDBOXES")
[ -n "$TOKEN_LIMIT" ]   && args+=(--token-limit "$TOKEN_LIMIT")
[ -n "$TIME_LIMIT" ]    && args+=(--time-limit "$TIME_LIMIT")
[ -n "$STALL_TIMEOUT" ]       && args+=(--stall-timeout "$STALL_TIMEOUT")
[ -n "$PHASE_PLANNER_MODEL" ] && args+=(--phase-planner-model "$PHASE_PLANNER_MODEL")
[ "$PLANNING_ONLY" = true ]   && args+=(--planning-only)

python experiments/01_run_agents/run.py "${args[@]}"
