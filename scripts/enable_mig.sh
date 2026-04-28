#!/bin/bash
# Enable MIG on all H100 GPUs and create 2x 3g.40gb slices per GPU.
#
# Result: 16 MIG instances (8 GPUs * 2) with hardware-enforced 40GB VRAM each.
# UUIDs are written to .mig_uuids (one per line) in the repo root.
#
# Requires sudo. Will FAIL if any process is using a GPU.
# Re-runnable: if MIG is already enabled, only re-creates instances.

set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE_NAME="3g.40gb"
PROFILE_ID=9                       # H100 80GB profile ID for 3g.40gb (stable)

# Bail if any GPU has running compute clients
if nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q .; then
    echo "ERROR: GPU(s) in use. Stop running CUDA processes before enabling MIG." >&2
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv >&2
    exit 1
fi

NUM_GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
echo "Found $NUM_GPUS GPU(s)"

# Enable MIG mode on each GPU (idempotent — no-op if already enabled)
for i in $(seq 0 $((NUM_GPUS - 1))); do
    mode=$(nvidia-smi -i "$i" --query-gpu=mig.mode.current --format=csv,noheader)
    if [ "$mode" != "Enabled" ]; then
        echo "Enabling MIG on GPU $i..."
        sudo nvidia-smi -i "$i" -mig 1
    else
        echo "GPU $i: MIG already enabled"
    fi
done

# Destroy existing MIG instances then create 2x 3g.40gb on each GPU
for i in $(seq 0 $((NUM_GPUS - 1))); do
    echo "Resetting MIG instances on GPU $i..."
    sudo nvidia-smi mig -i "$i" -dci 2>/dev/null || true
    sudo nvidia-smi mig -i "$i" -dgi 2>/dev/null || true
    echo "Creating 2x $PROFILE_NAME on GPU $i..."
    sudo nvidia-smi mig -i "$i" -cgi "$PROFILE_ID,$PROFILE_ID" -C
done

# Dump MIG UUIDs to .mig_uuids
nvidia-smi -L | awk -F 'UUID: |\\)' '/MIG/ {print $2}' > .mig_uuids
COUNT=$(wc -l < .mig_uuids)
echo "Wrote $COUNT MIG UUIDs to .mig_uuids"
cat .mig_uuids
