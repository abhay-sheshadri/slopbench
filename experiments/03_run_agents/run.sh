#!/bin/bash
# Launch pi research agents. Edit the config block below, then run it:
#   ./run.sh            # launch every (project x mode) run in detached tmux sessions
#   ./run.sh --force    # wipe each run's output dir first
#   ./run.sh --direct   # run in this shell instead of tmux (debugging)
# Watch live or review with ./view_agents.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .venv/bin/activate ] && source .venv/bin/activate

# ------------------------------- config ------------------------------------ #
PROJECTS=(
    # empirical_cot_controllability_steering_vectors
    # empirical_introspection_science
    # empirical_subliminal_backdoors
    # empirical_reasoning_recontextualization
    # empirical_slop_probes
    empirical_prompted_false_facts
    empirical_impossible_tasks_bullshitting
    empirical_emergent_collusion
    empirical_functional_emotions_wellbeing
    empirical_nla_auditbench_quirks
    empirical_filler_token_scaling
)
MODES=(multi_phase)
THINKING=xhigh
MODEL="anthropic/claude-opus-4-8"   # Claude Opus 4.8
# --------------------------------------------------------------------------- #

DIRECT=0
EXTRA_ARGS=()
for arg in "$@"; do
    case "$arg" in
        -h|--help)
            cat <<'EOF'
Usage: experiments/03_run_agents/run.sh [--direct] [run.py args...]

Default: launch each configured project/mode in its own detached tmux session.
Use --direct to run the old in-shell launcher for debugging.
Extra args are passed through to experiments/03_run_agents/run.py.
EOF
            exit 0
            ;;
        --direct)
            DIRECT=1
            ;;
        *)
            EXTRA_ARGS+=("$arg")
            ;;
    esac
done

ARGS=(--projects "${PROJECTS[@]}" --modes "${MODES[@]}" --thinking "$THINKING")
[ -n "$MODEL" ] && ARGS+=(--model "$MODEL")

if [ "$DIRECT" -eq 1 ]; then
    source scripts/run_cleanup.sh
    install_run_cleanup_trap
    exec python experiments/03_run_agents/run.py "${ARGS[@]}" "${EXTRA_ARGS[@]}"
fi

if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required for detached launches. Install it or pass --direct." >&2
    exit 1
fi

tmux_session_name() {
    local raw="agent_$1_$2"
    raw="${raw//[^A-Za-z0-9_-]/_}"
    printf '%s' "${raw:0:180}"
}

fail=0
launched=0
for project in "${PROJECTS[@]}"; do
    for mode in "${MODES[@]}"; do
        session="$(tmux_session_name "$project" "$mode")"
        if tmux has-session -t "$session" 2>/dev/null; then
            echo "Already running: tmux session $session"
            fail=1
            continue
        fi

        child_args=(--projects "$project" --modes "$mode" --thinking "$THINKING")
        [ -n "$MODEL" ] && child_args+=(--model "$MODEL")
        child_args+=("${EXTRA_ARGS[@]}")

        printf -v quoted_args '%q ' "${child_args[@]}"
        printf -v repo_q '%q' "$PWD"
        cmd="cd $repo_q; [ -f .venv/bin/activate ] && source .venv/bin/activate; exec python experiments/03_run_agents/run.py $quoted_args"
        tmux new-session -d -s "$session" "$cmd"
        echo "Launched $project ($mode) in tmux session: $session"
        launched=$((launched + 1))
    done
done

if [ "$launched" -gt 0 ]; then
    echo
    echo "Runs are detached. Watch with: tmux ls"
    echo "Attach with: tmux attach -t <session>"
    echo "Viewer: ./view_agents.sh -c"
fi

exit "$fail"
