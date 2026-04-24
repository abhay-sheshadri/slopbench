#!/bin/bash
# Build Docker images for agent task environments.
#
# Usage:
#   bash docker/build.sh              # build both
#   bash docker/build.sh minimal      # just minimal
#   bash docker/build.sh research     # just research

set -e
cd "$(dirname "$0")"

build_minimal() {
    echo "Building agent-minimal..."
    docker build -t agent-minimal -f Dockerfile.minimal .
    echo "Done: agent-minimal"
}

build_research() {
    echo "Building agent-research..."
    cp ../src/tooling.py tooling.py
    docker build -t agent-research -f Dockerfile.research .
    rm tooling.py
    echo "Done: agent-research"
}

TARGET="${1:-all}"

case "$TARGET" in
    minimal)
        build_minimal
        ;;
    research)
        build_research
        ;;
    all)
        build_minimal
        build_research
        ;;
    *)
        echo "Usage: $0 [minimal|research|all]"
        exit 1
        ;;
esac
