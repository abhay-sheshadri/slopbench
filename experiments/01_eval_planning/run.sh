#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# Use the project venv (matches the other experiment runners).
[ -f .venv/bin/activate ] && source .venv/bin/activate
PY="$(command -v python || command -v python3)"
if [ -z "$PY" ]; then echo "error: no python found (create .venv first)" >&2; exit 1; fi

# By default this experiment plans only the empirical_* proposals. Override the
# default by passing your own project selection, e.g.:
#   ./run.sh --conceptual-only
#   ./run.sh --empirical-only          (same as the default)
#   ./run.sh --projects empirical_foo conceptual_bar
kind_override=0
for arg in "$@"; do
  case "$arg" in
    --conceptual-only|--empirical-only|--projects|--projects=*)
      kind_override=1
      break
      ;;
  esac
done

args=(--max-concurrent "${MAX_CONCURRENT:-50}")
if [[ "$kind_override" -eq 0 ]]; then
  args+=(--empirical-only)
fi
args+=("$@")

PYTHONUNBUFFERED=1 "$PY" experiments/01_eval_planning/run.py "${args[@]}"
