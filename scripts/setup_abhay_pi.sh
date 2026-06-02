#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

run_with_sudo() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

# Run a command as the owner of $1 (a path). If we're already that user,
# run directly; otherwise sudo to them. Used so git operations against the
# already-cloned, user-owned $ABHAY_PI_DIR keep using the user's GitHub
# credentials instead of root's (which usually has none).
run_as_path_owner() {
    local path="$1"
    shift
    local owner
    owner="$(stat -c '%U' "$path" 2>/dev/null || stat -f '%Su' "$path" 2>/dev/null || echo root)"
    if [ "$owner" = "$(id -un)" ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$owner" "$@"
    else
        "$@"
    fi
}

install_node() {
    curl -fsSL https://deb.nodesource.com/setup_22.x | run_with_sudo bash -
    run_with_sudo apt install -y nodejs
}

install_source_repo() {
    ABHAY_PI_REPO="${ABHAY_PI_REPO:-https://github.com/abhay-sheshadri/abhay-pi.git}"
    ABHAY_PI_REF="${ABHAY_PI_REF:-main}"
    # Clone pi *into this project dir* (gitignored) rather than into /opt, so the
    # whole toolchain lives under the repo and `pi` is a symlink to the wrapper.
    ABHAY_PI_DIR="${ABHAY_PI_DIR:-$REPO_DIR/abhay-pi}"

    run_with_sudo apt install -y git ca-certificates
    if [ -d "$ABHAY_PI_DIR/.git" ]; then
        # Run git as the directory's owner so it uses their GitHub creds
        # (root usually has none). Also mark the dir as a safe.directory in
        # case ownership and the current user disagree at the git layer.
        git config --global --add safe.directory "$ABHAY_PI_DIR" 2>/dev/null || true
        run_as_path_owner "$ABHAY_PI_DIR" git -C "$ABHAY_PI_DIR" fetch origin "$ABHAY_PI_REF"
        run_as_path_owner "$ABHAY_PI_DIR" git -C "$ABHAY_PI_DIR" checkout "$ABHAY_PI_REF"
        run_as_path_owner "$ABHAY_PI_DIR" git -C "$ABHAY_PI_DIR" pull --ff-only origin "$ABHAY_PI_REF"
    else
        rm -rf "$ABHAY_PI_DIR"
        # Clone as the owner of the project dir so the tree stays user-owned.
        run_as_path_owner "$REPO_DIR" git clone --branch "$ABHAY_PI_REF" --depth 1 "$ABHAY_PI_REPO" "$ABHAY_PI_DIR"
    fi

    run_as_path_owner "$ABHAY_PI_DIR" npm --prefix "$ABHAY_PI_DIR" install --ignore-scripts
}

install_wrappers() {
    # Symlink the in-repo wrapper onto PATH so `pi` (and `abhay-pi`) call it
    # directly — no stale copies to drift out of sync with the repo.
    run_with_sudo ln -sfn "$SCRIPT_DIR/abhay-pi" /usr/local/bin/abhay-pi
    run_with_sudo ln -sfn "$SCRIPT_DIR/abhay-pi" /usr/local/bin/pi
}

install_node
install_source_repo
install_wrappers

echo "Node.js version: $(node --version)"
echo "abhay-pi source: ${ABHAY_PI_DIR:-$REPO_DIR/abhay-pi}"
echo "pi installed: $(which pi) -> $(readlink -f "$(which pi)")"
echo "abhay-pi installed: $(which abhay-pi) -> $(readlink -f "$(which abhay-pi)")"
