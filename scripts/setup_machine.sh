#!/bin/bash
set -euo pipefail

run_with_sudo() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

install_python_env() {
    run_with_sudo rm -rf .venv
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env"
    uv python install 3.11
    uv venv --clear
    source .venv/bin/activate
    uv pip install -e .
    uv pip install pre-commit
    pre-commit install
}

install_dev_tools() {
    run_with_sudo apt update
    run_with_sudo apt install -y tmux gh
    cp .tmux.conf ~/.tmux.conf
}

install_sandbox() {
    # Agent runs are isolated with bubblewrap (bwrap), not Docker. On Ubuntu
    # 24.04 unprivileged user namespaces are confined by AppArmor, so bwrap also
    # needs a small profile granting it `userns`; without it bwrap fails with
    # "setting up uid map: Permission denied".
    run_with_sudo apt update
    run_with_sudo apt install -y bubblewrap

    if [ -d /etc/apparmor.d ] && command -v apparmor_parser >/dev/null 2>&1; then
        run_with_sudo tee /etc/apparmor.d/bwrap >/dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
PROFILE
        run_with_sudo apparmor_parser -r /etc/apparmor.d/bwrap || true
    fi

    # Sanity check: a user namespace must work for the agent sandbox to run.
    if ! bwrap --unshare-user --ro-bind /usr /usr --ro-bind /bin /bin true 2>/dev/null; then
        echo "WARNING: bwrap cannot create a user namespace. If this is Ubuntu 24.04+,"
        echo "         ensure the AppArmor profile above loaded, or as a fallback set"
        echo "         'sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0'."
    fi
}

cd "$(dirname "$0")/.."

bash scripts/setup_abhay_pi.sh
install_python_env
install_dev_tools
install_sandbox
