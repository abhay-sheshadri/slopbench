#!/usr/bin/env bash
# reclaim_disk.sh — drop redundant heavy artifacts from OLD phase dirs.
#
# Each new phase is a clone-forward of the previous one, so the latest phase is a
# content superset of the older ones (verified: no real artifact file is unique to
# an old phase; only regenerable dirs like .venv/__pycache__ differ). So a heavy
# data/cache dir in an old phase, when the latest phase already has it at >= size,
# is a redundant duplicate and is safe to delete.
#
# For each run (live runs skipped), for each phase OLDER than the latest, delete
# any dir named in ARTIFACT_DIRS when the latest phase has a same-named dir of
# >= size. Only these curated data/cache names are ever touched, so code dirs
# (scripts_*/, src/), *.py, writeups/, planner/ etc. are never candidates.
#
# Dry run by default; pass --apply to delete.
#   scripts/reclaim_disk.sh            # show what would go
#   scripts/reclaim_disk.sh --apply    # delete it

set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# Regenerable scratch: deleted from every old phase unconditionally (not deliverables).
REGEN_DIRS=".venv __pycache__ file_cache_dir activation_cache"
# Real data: deleted from an old phase only when the latest phase has it at >= size.
DATA_DIRS="results data lora_adapters adapters checkpoints"
LIVE_HEARTBEAT_MIN=10

RUNS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../outputs/03_run_agents" && pwd)"
now=$(date +%s)
kb() { du -sk "$1" 2>/dev/null | cut -f1; }
total=0; targets=()

echo "Scanning $RUNS_DIR ($([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN))"

for run in "$RUNS_DIR"/*/; do
  run="${run%/}"
  # Skip live runs (RUNNING marker or fresh heartbeat).
  hb="$run/.pi_transcripts/heartbeat.json"
  if [ -f "$run/.pi_transcripts/RUNNING" ] ||
     { [ -f "$hb" ] && [ $(( (now - $(stat -c %Y "$hb")) / 60 )) -lt "$LIVE_HEARTBEAT_MIN" ]; }; then
    echo "$(basename "$run"): LIVE — skipping"; continue
  fi

  mapfile -t phases < <(ls -d "$run"/phase_segment_*_phase_* 2>/dev/null | sort -V)
  [ "${#phases[@]}" -ge 2 ] || continue
  latest="${phases[-1]}"

  drop() {  # queue dir $1 for deletion
    local d="$1" o; o=$(kb "$d")
    total=$(( total + o )); targets+=("$d")
    printf "  %-7s %s\n" "$(numfmt --to=iec --from-unit=1024 "$o")" "${d#"$RUNS_DIR"/}"
  }

  for p in "${phases[@]:0:${#phases[@]}-1}"; do   # every phase except the latest
    for name in $REGEN_DIRS; do                   # regenerable -> always safe to drop
      [ -d "$p/$name" ] && drop "$p/$name"
    done
    for name in $DATA_DIRS; do                    # real data -> only if latest is a superset
      old="$p/$name"; new="$latest/$name"
      [ -d "$old" ] && [ -d "$new" ] || continue
      [ "$(kb "$new")" -ge "$(kb "$old")" ] && drop "$old"
    done
  done
done

echo "Reclaimable: $(numfmt --to=iec --from-unit=1024 "$total") across ${#targets[@]} dirs"
if [ "$APPLY" = 1 ]; then
  for t in "${targets[@]}"; do rm -rf "$t"; done
  echo "Deleted. Disk now:"; df -h "$RUNS_DIR" | tail -1
else
  echo "(dry run — re-run with --apply to delete)"
fi
