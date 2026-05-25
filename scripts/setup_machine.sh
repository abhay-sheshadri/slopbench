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

install_docker() {
    if command -v docker >/dev/null 2>&1; then
        return
    fi

    run_with_sudo apt update
    run_with_sudo apt install -y ca-certificates curl gnupg
    run_with_sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | run_with_sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    run_with_sudo chmod a+r /etc/apt/keyrings/docker.gpg

    . /etc/os-release
    codename="${VERSION_CODENAME:-}"
    if [ -z "$codename" ]; then
        codename="$(. /etc/lsb-release && echo "$DISTRIB_CODENAME")"
    fi

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $codename stable" \
        | run_with_sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

    run_with_sudo apt update
    run_with_sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

start_docker() {
    if docker info >/dev/null 2>&1; then
        return
    fi

    run_with_sudo systemctl enable --now docker
}

cd "$(dirname "$0")/.."

bash scripts/setup_abhay_pi.sh
install_python_env
install_dev_tools
install_docker
start_docker
bash docker/build.sh
