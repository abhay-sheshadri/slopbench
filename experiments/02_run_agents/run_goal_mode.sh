#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

PROPOSALS=(
    empirical_prompted_false_facts
)
K=1
MODEL="anthropic/claude-opus-4-7"
OUTPUT_DIR="outputs/02_run_agents"
TOKEN_LIMIT=""
TIME_LIMIT=21600
STALL_TIMEOUT=1800
DISPLAY_MODE="full"

[ -f .venv/bin/activate ] && source .venv/bin/activate

cleanup() {
    echo "Cleaning up Docker containers..."
    docker ps --filter "name=inspect-" --format '{{.Names}}' | xargs -r docker rm -f 2>/dev/null
}
trap cleanup EXIT

args=(goal-mode --proposals "${PROPOSALS[@]}" --k "$K" --model "$MODEL" --output-dir "$OUTPUT_DIR" --display "$DISPLAY_MODE" --force)
args+=(--max-sandboxes "$K")
[ -n "$TOKEN_LIMIT" ] && args+=(--token-limit "$TOKEN_LIMIT")
[ -n "$TIME_LIMIT" ] && args+=(--time-limit "$TIME_LIMIT")
[ -n "$STALL_TIMEOUT" ] && [ "$STALL_TIMEOUT" != "0" ] && args+=(--stall-timeout "$STALL_TIMEOUT")

python experiments/02_run_agents/run.py "${args[@]}"
