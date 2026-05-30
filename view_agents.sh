#!/bin/bash
# Live agent viewer: stream pi agent state (messages, thinking, tool calls,
# subagents, run-loop phases, goal-mode state) from running and completed agent
# runs under outputs/ (read directly off disk; no Docker).
#
# Usage:
#   ./view_agents.sh                 # serve on http://127.0.0.1:8765
#   ./view_agents.sh --port 9000 --open
set -euo pipefail
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate
exec python -m src.agent_viewer "$@"
