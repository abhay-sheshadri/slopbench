#!/bin/bash
# Blue-team every COMPLETED (not live) run under outputs/03_run_agents/ for research
# sabotage. Deletes the existing outputs/08_automated_blue_teaming/<run>/ before
# regenerating. Run it in tmux; extra args pass through to make_blue_team.py.
#
#   ./experiments/08_automated_blue_teaming/run_all.sh                 # all at once (<=50)
#   CONCURRENCY=1 ./experiments/08_automated_blue_teaming/run_all.sh   # one at a time
#   ./experiments/08_automated_blue_teaming/run_all.sh --samples 3     # 3 auditors each
set -uo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate

OUT_DIR="outputs/08_automated_blue_teaming"
CONCURRENCY="${CONCURRENCY:-50}"   # max blue-team agents running at once

for run in outputs/03_run_agents/*/; do
  name="$(basename "$run")"
  [ -f "$run/.pi_transcripts/RUNNING" ] && continue                              # skip live runs
  grep -q '"status": "completed"' "$run/.pi_transcripts/manifest.json" 2>/dev/null || continue
  (
    t0=$(date +%s)
    echo "[$(date '+%H:%M:%S')] START $name"
    rm -rf "${OUT_DIR:?}/$name"
    python experiments/08_automated_blue_teaming/make_blue_team.py "$run" "$@" >/dev/null 2>&1
    rc=$?; dt=$(( $(date +%s) - t0 ))
    echo "[$(date '+%H:%M:%S')] DONE  $name in $((dt/60))m$((dt%60))s (rc=$rc) -> $OUT_DIR/$name"
  ) &
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do sleep 5; done
done

wait
echo "All blue-team audits done -> $OUT_DIR/"
