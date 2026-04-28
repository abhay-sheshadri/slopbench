#!/bin/bash
# Launch basic (single-loop) agent runs.
set -e
cd "$(dirname "$0")/../.."

# ── Configuration ──────────────────────────────────────
PROJECTS=(
    understanding_probe_generalization
)
K=4
MODEL="anthropic/claude-opus-4-7"
OUTPUT_DIR="outputs/01_run_agents"
TOKEN_LIMIT=""                     # token budget per agent, empty = no limit
TIME_LIMIT=21600                   # seconds per agent (6 hours)
MAX_CONTINUATIONS=30
STALL_TIMEOUT=1800                 # kill after 30 min of no activity (0 = disable)
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

args=(basic --projects "${PROJECTS[@]}" --k "$K" --model "$MODEL" --output-dir "$OUTPUT_DIR" --max-continuations "$MAX_CONTINUATIONS" --display "$DISPLAY_MODE")
args+=(--max-sandboxes "$MAX_SANDBOXES")
[ -n "$TOKEN_LIMIT" ]   && args+=(--token-limit "$TOKEN_LIMIT")
[ -n "$TIME_LIMIT" ]    && args+=(--time-limit "$TIME_LIMIT")
[ -n "$STALL_TIMEOUT" ] && args+=(--stall-timeout "$STALL_TIMEOUT")

python experiments/01_run_agents/run.py "${args[@]}"
