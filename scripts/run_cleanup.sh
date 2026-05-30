#!/bin/bash
# Safety-net cleanup for experiment run scripts.
#
# The bwrap sandbox runner tears its own process tree down automatically
# (--die-with-parent + a private PID namespace), so a clean exit leaves nothing
# behind. This trap only catches the SIGKILL / hard-crash case: it kills any
# leftover bwrap processes whose workspace is under outputs/, and clears stale
# .pi_transcripts/RUNNING markers so interrupted runs don't show as "live"
# forever in the viewer.
#
# Usage (after cd to repo root):
#   source scripts/run_cleanup.sh
#   install_run_cleanup_trap

_pi_run_cleanup() {
    # Kill leftover sandboxes that bind an outputs/ workspace.
    local pids
    pids="$(pgrep -f 'bwrap.*--bind .*/outputs/' 2>/dev/null || true)"
    if [ -n "$pids" ]; then
        echo "Cleaning up leftover agent sandboxes from this run..."
        # shellcheck disable=SC2086
        kill -TERM $pids 2>/dev/null
        sleep 2
        # shellcheck disable=SC2086
        kill -KILL $pids 2>/dev/null
    fi
    # Clear stale RUNNING markers (a clean run removes its own).
    find outputs -path '*/.pi_transcripts/RUNNING' -delete 2>/dev/null || true
    return 0
}

install_run_cleanup_trap() {
    trap _pi_run_cleanup EXIT
}
