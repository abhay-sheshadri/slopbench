#!/bin/bash
# Generate a clean blogpost for every COMPLETED (not live) run under
# outputs/03_run_agents/. Deletes the existing outputs/04_blogpost_gen/<run>/
# before regenerating. Run it in tmux; extra args pass through to make_blogpost.py.
#
#   ./experiments/04_blogpost_gen/run_all.sh                       # all at once (<=50)
#   CONCURRENCY=1 ./experiments/04_blogpost_gen/run_all.sh         # one at a time
#   ./experiments/04_blogpost_gen/run_all.sh --timeout 3000
set -uo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate

OUT_DIR="outputs/04_blogpost_gen"
CONCURRENCY="${CONCURRENCY:-50}"   # max blogpost agents running at once

for run in outputs/03_run_agents/*/; do
  name="$(basename "$run")"
  [ -f "$run/.pi_transcripts/RUNNING" ] && continue                              # skip live runs
  grep -q '"status": "completed"' "$run/.pi_transcripts/manifest.json" 2>/dev/null || continue
  (
    t0=$(date +%s)
    echo "[$(date '+%H:%M:%S')] START $name"
    rm -rf "${OUT_DIR:?}/$name"
    python experiments/04_blogpost_gen/make_blogpost.py "$run" "$@" >/dev/null 2>&1
    rc=$?; dt=$(( $(date +%s) - t0 ))
    echo "[$(date '+%H:%M:%S')] DONE  $name in $((dt/60))m$((dt%60))s (rc=$rc) -> $OUT_DIR/$name"
  ) &
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do sleep 5; done
done

wait
echo "All blogposts done -> $OUT_DIR/"
