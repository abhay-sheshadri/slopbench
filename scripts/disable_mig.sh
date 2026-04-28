#!/bin/bash
# Disable MIG on all GPUs. Restores them to normal full-GPU mode.
# Requires sudo. Fails if any process is using a GPU.

set -euo pipefail
cd "$(dirname "$0")/.."

if nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q .; then
    echo "ERROR: GPU(s) in use. Stop running CUDA processes before disabling MIG." >&2
    exit 1
fi

NUM_GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)

for i in $(seq 0 $((NUM_GPUS - 1))); do
    echo "Tearing down MIG instances on GPU $i..."
    sudo nvidia-smi mig -i "$i" -dci 2>/dev/null || true
    sudo nvidia-smi mig -i "$i" -dgi 2>/dev/null || true
    echo "Disabling MIG on GPU $i..."
    sudo nvidia-smi -i "$i" -mig 0 || true
done

rm -f .mig_uuids
echo "MIG disabled."
