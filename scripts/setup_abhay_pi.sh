#!/bin/bash
set -e
set -u
set -o pipefail

# Helper function to run commands with sudo if available
run_with_sudo() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

# Install Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | run_with_sudo bash -
run_with_sudo apt install -y nodejs

# Install Pi. Override ABHAY_PI_PACKAGE for a fork/tarball/git URL if needed.
ABHAY_PI_PACKAGE="${ABHAY_PI_PACKAGE:-@earendil-works/pi-coding-agent}"
run_with_sudo npm install -g "$ABHAY_PI_PACKAGE"

# Install abhay-pi wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run_with_sudo cp "$SCRIPT_DIR/abhay-pi" /usr/local/bin/abhay-pi
run_with_sudo chmod +x /usr/local/bin/abhay-pi

# Verify
echo "Node.js version: $(node --version)"
echo "Pi installed: $(which pi)"
echo "abhay-pi installed: $(which abhay-pi)"
