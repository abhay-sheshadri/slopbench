#!/bin/bash
# Live agent viewer: stream pi agent state (messages, thinking, tool calls,
# subagents, run-loop phases, goal-mode state) from running and completed agent
# runs under outputs/ (read directly off disk; no Docker).
#
# Usage:
#   ./view_agents.sh                 # serve on http://127.0.0.1:<random-port>
#   ./view_agents.sh --port 9000 --open
#   ./view_agents.sh -c              # serve through a temporary trycloudflare URL
set -euo pipefail
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate

cloudflare=0
viewer_args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -c|--cloudflare)
      cloudflare=1
      shift
      ;;
    --)
      shift
      viewer_args+=("$@")
      break
      ;;
    *)
      viewer_args+=("$1")
      shift
      ;;
  esac
done

if [ "$cloudflare" -eq 0 ]; then
  exec python -m src.agent_viewer "${viewer_args[@]}"
fi

has_host=0
for arg in "${viewer_args[@]}"; do
  if [ "$arg" = "--host" ] || [[ "$arg" == --host=* ]]; then
    has_host=1
    break
  fi
done
if [ "$has_host" -eq 0 ]; then
  viewer_args=(--host 127.0.0.1 "${viewer_args[@]}")
fi

find_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    command -v cloudflared
    return
  fi
  if [ -x /tmp/bin/cloudflared ]; then
    printf '%s\n' /tmp/bin/cloudflared
    return
  fi

  local arch url
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    aarch64|arm64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    *) echo "Unsupported architecture for automatic cloudflared download: $arch" >&2; return 1 ;;
  esac

  mkdir -p /tmp/bin
  echo "Downloading cloudflared..." >&2
  curl -fsSL "$url" -o /tmp/bin/cloudflared
  chmod +x /tmp/bin/cloudflared
  printf '%s\n' /tmp/bin/cloudflared
}

cloudflared_bin="$(find_cloudflared)"
viewer_log="$(mktemp -t view-agents.XXXXXX.log)"
tunnel_log="$(mktemp -t view-agents-cloudflare.XXXXXX.log)"
viewer_pid=""
tunnel_pid=""

cleanup() {
  [ -n "$tunnel_pid" ] && kill "$tunnel_pid" >/dev/null 2>&1 || true
  [ -n "$viewer_pid" ] && kill "$viewer_pid" >/dev/null 2>&1 || true
  rm -f "$viewer_log" "$tunnel_log"
}
trap cleanup EXIT INT TERM

python -m src.agent_viewer "${viewer_args[@]}" >"$viewer_log" 2>&1 &
viewer_pid=$!

viewer_url=""
for _ in $(seq 1 60); do
  if ! kill -0 "$viewer_pid" >/dev/null 2>&1; then
    cat "$viewer_log" >&2
    exit 1
  fi
  viewer_url="$(sed -nE 's/^Agent viewer on (http:\/\/[^ ]+).*/\1/p' "$viewer_log" | head -n 1)"
  [ -n "$viewer_url" ] && break
  sleep 0.25
done

if [ -z "$viewer_url" ]; then
  echo "Timed out waiting for agent viewer to start. Log:" >&2
  cat "$viewer_log" >&2
  exit 1
fi

port="$(printf '%s\n' "$viewer_url" | sed -nE 's#^http://(\[[^]]+\]|[^:]+):([0-9]+).*$#\2#p')"
if [ -z "$port" ]; then
  echo "Could not parse viewer port from: $viewer_url" >&2
  exit 1
fi

local_url="http://127.0.0.1:$port"

echo "Waiting for Cloudflare tunnel..."
"$cloudflared_bin" tunnel --no-autoupdate --url "$local_url" >"$tunnel_log" 2>&1 &
tunnel_pid=$!

public_url=""
for _ in $(seq 1 120); do
  if ! kill -0 "$tunnel_pid" >/dev/null 2>&1; then
    cat "$tunnel_log" >&2
    exit 1
  fi
  public_url="$(sed -nE 's/.*(https:\/\/[-a-zA-Z0-9.]+\.trycloudflare\.com).*/\1/p' "$tunnel_log" | tail -n 1)"
  [ -n "$public_url" ] && break
  sleep 0.5
done

if [ -z "$public_url" ]; then
  echo "Timed out waiting for Cloudflare tunnel URL. Log:" >&2
  cat "$tunnel_log" >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  verified=0
  for _ in $(seq 1 60); do
    if curl -fsSL --max-time 10 "$public_url/" 2>/dev/null | grep -q "<title>Agent Viewer</title>"; then
      verified=1
      break
    fi
    sleep 1
  done
  if [ "$verified" -eq 0 ]; then
    echo "Cloudflare URL was assigned but did not become reachable in time: $public_url" >&2
    echo "Tunnel log:" >&2
    cat "$tunnel_log" >&2
    exit 1
  fi
fi

echo "Agent viewer public: $public_url"
echo "Press Ctrl-C to stop the viewer and tunnel."
wait -n "$viewer_pid" "$tunnel_pid"
