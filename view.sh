#!/bin/bash
# Open the Inspect log viewer.
#
# Recursive listing is on by default; do NOT pass --recursive — Inspect's CLI
# defines it as a flag with default=True, so passing the flag inverts it
# (a click is_flag/default=True quirk) and you'd lose recursion.
#
# Usage:
#   ./view.sh                              # browse all runs (basic + advanced, all models)
#   ./view.sh basic                        # only basic-mode runs
#   ./view.sh advanced/claude-sonnet-4-6   # one specific model under advanced
set -e
cd "$(dirname "$0")/outputs/01_run_agents"

SUBPATH="${1:-.}"
inspect view --log-dir "$SUBPATH"
