#!/usr/bin/env python3
"""Launch pi INTERACTIVELY inside the same bubblewrap sandbox used for agent runs.

Mirrors src/sandbox.py's isolation (read-only host toolchain, a writable
/workspace as the cwd, HOME=/workspace/.home, .env secrets injected) but keeps
your terminal attached so you get pi's interactive TUI. Use it to see how pi
behaves inside the sandbox.

Usage:
    python scripts/run_pi_sandbox.py [--workspace DIR] [-- <pi args>]

    python scripts/run_pi_sandbox.py                      # fresh throwaway workspace
    python scripts/run_pi_sandbox.py --workspace /tmp/pi  # reuse (keeps sessions/files)
    python scripts/run_pi_sandbox.py -- --model claude-opus-4-8   # pass args to pi

Notes:
- Requires bwrap (bubblewrap) and a working pi (scripts/setup_machine.sh).
- Auth comes from <repo>/.env (ANTHROPIC_API_KEY etc.), injected into the sandbox
  env like real runs. HOME is remapped, so ~/.pi/agent/auth.json is NOT used.
- IS_SANDBOX=1 by default (pi runs autonomously, matching real runs). Run with
  `IS_SANDBOX=0 python scripts/run_pi_sandbox.py` if you want approval prompts.
- On startup pi extracts its bundled skills/subagents/files into
  /workspace/.home/.pi/agent/, so they're all available inside the sandbox.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import sandbox  # noqa: E402
from src.runner_utils import parse_env_text  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run pi interactively inside the bwrap sandbox."
    )
    ap.add_argument(
        "--workspace",
        help="Dir mounted as /workspace (the cwd). Default: a fresh temp dir.",
    )
    ap.add_argument(
        "pi_args",
        nargs=argparse.REMAINDER,
        help="Args passed to pi (put them after --).",
    )
    args = ap.parse_args()

    if not sandbox.available():
        sys.exit(
            "bwrap not found. Install bubblewrap first (e.g. scripts/setup_machine.sh)."
        )

    ws = (
        Path(args.workspace).resolve()
        if args.workspace
        else Path(tempfile.mkdtemp(prefix="pi-sandbox-"))
    )
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".home").mkdir(exist_ok=True)

    # Inject .env secrets into the sandbox env (auth), same as real agent runs.
    env_file = ROOT / ".env"
    overrides = parse_env_text(env_file.read_text()) if env_file.exists() else {}
    env = sandbox.default_env(overrides)
    if overrides:
        (ws / ".env").write_text(
            env_file.read_text()
        )  # research code often loads dotenv

    pi_args = list(args.pi_args)
    if pi_args and pi_args[0] == "--":
        pi_args = pi_args[1:]

    argv = sandbox.build_argv(ws, ["pi", *pi_args])

    print(f"[sandbox] /workspace -> {ws}", file=sys.stderr)
    print(
        f"[sandbox] HOME=/workspace/.home  IS_SANDBOX={env.get('IS_SANDBOX')}  pi args={pi_args}",
        file=sys.stderr,
    )
    # Inherit the terminal (no stdio redirection) so pi's interactive TUI works.
    return subprocess.run(argv, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
