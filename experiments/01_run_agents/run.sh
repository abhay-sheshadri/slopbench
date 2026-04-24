#!/bin/bash
# Launch agent runs. Edit the variables below to configure.
set -e
cd "$(dirname "$0")/../.."

# ── Configuration ──────────────────────────────────────
PROJECTS=(
    understanding_probe_generalization
)
K=5
PLANNER_MODEL="anthropic/claude-sonnet-4-6"
WORKER_MODEL="anthropic/claude-sonnet-4-6"
PHASE_PLANNER_MODEL=""              # defaults to PLANNER_MODEL
GPU_MEMORY=20                      # VRAM per container in GB
GPUS="all"                         # which GPUs to use: "all" or "0,1,2" etc.
LOG_DIR="outputs/01_run_agents"
TOKEN_LIMIT=""                     # token budget per agent, empty = no limit
TIME_LIMIT=7200                    # seconds per agent (2 hours)
MAX_PHASES=10
MAX_CONTINUATIONS=15
STALL_TIMEOUT=1800                 # kill step after 30 min of no activity (0 = disable)
PLANNING_ONLY=false
DISPLAY_MODE="full"          # full, conversation, rich, plain, none
# ───────────────────────────────────────────────────────

[ -f .venv/bin/activate ] && source .venv/bin/activate

# Kill any leftover inspect containers on exit (normal, error, or interrupt)
cleanup() {
    echo "Cleaning up Docker containers..."
    docker ps --filter "name=inspect-" --format '{{.Names}}' | xargs -r docker rm -f 2>/dev/null
}
trap cleanup EXIT

# Clean up previous log files
if [ -d "$LOG_DIR" ]; then
    rm -rf "$LOG_DIR"
    echo "Cleaned previous logs from $LOG_DIR"
fi

# Calculate max concurrent containers from GPU memory
if [ -n "$GPU_MEMORY" ]; then
    export GPU_MEMORY_GB="$GPU_MEMORY"

    if [ "$GPUS" = "all" ]; then
        TOTAL_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk '{s+=$1} END {printf "%.0f", s/1024}')
        NUM_GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
    else
        IFS=',' read -ra GPU_IDS <<< "$GPUS"
        NUM_GPUS=${#GPU_IDS[@]}
        TOTAL_VRAM=0
        for gid in "${GPU_IDS[@]}"; do
            MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i "$gid" | awk '{printf "%.0f", $1/1024}')
            TOTAL_VRAM=$((TOTAL_VRAM + MEM))
        done
        export NVIDIA_VISIBLE_DEVICES="$GPUS"
    fi

    MAX_SANDBOXES=$((TOTAL_VRAM / GPU_MEMORY))
    echo "GPUs: $NUM_GPUS ($TOTAL_VRAM GB total), ${GPU_MEMORY} GB/container → max $MAX_SANDBOXES concurrent"
fi

args=(--projects "${PROJECTS[@]}" --k "$K" --planner-model "$PLANNER_MODEL" --worker-model "$WORKER_MODEL" --log-dir "$LOG_DIR" --max-phases "$MAX_PHASES" --max-continuations "$MAX_CONTINUATIONS" --display "$DISPLAY_MODE")
[ -n "$GPU_MEMORY" ]    && args+=(--gpu-memory "$GPU_MEMORY")
[ -n "$MAX_SANDBOXES" ] && args+=(--max-sandboxes "$MAX_SANDBOXES")
[ -n "$TOKEN_LIMIT" ]   && args+=(--token-limit "$TOKEN_LIMIT")
[ -n "$TIME_LIMIT" ]    && args+=(--time-limit "$TIME_LIMIT")
[ -n "$STALL_TIMEOUT" ]       && args+=(--stall-timeout "$STALL_TIMEOUT")
[ -n "$PHASE_PLANNER_MODEL" ] && args+=(--phase-planner-model "$PHASE_PLANNER_MODEL")
[ "$PLANNING_ONLY" = true ] && args+=(--planning-only)

python experiments/01_run_agents/run.py "${args[@]}"
