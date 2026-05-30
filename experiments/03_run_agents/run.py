#!/usr/bin/env python3
"""Launch pi research agents on the given projects, in the given modes.

This is a thin launcher: the project/mode selection (and model/thinking) is
configured in run.sh — edit the config block there. One agent per (project,
mode), all launched concurrently, with no timeout (runs execute to completion).
Each run is a browsable directory at outputs/03_run_agents/<project>_<mode>/;
watch them live with ./view_agents.sh.
"""

from __future__ import annotations

import argparse
import asyncio
import sys as _sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in _sys.path:
    _sys.path.insert(0, str(ROOT))

from src import DEFAULT_MODEL  # noqa: E402
from src.agent_runner import MODES, RunSpec, run_many  # noqa: E402
from src.runner_utils import clean_output_dir  # noqa: E402

PROPOSALS_DIR = ROOT / "proposals"


def load_proposal(name: str) -> str:
    path = PROPOSALS_DIR / f"{name}.md"
    if not path.exists():
        raise SystemExit(f"Proposal not found: {path}")
    return path.read_text()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projects",
        nargs="+",
        required=True,
        metavar="NAME",
        help="Proposal names to run (without .md).",
    )
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--output-dir", default="outputs/03_run_agents")
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help="Max runs in flight. Default: all of them (launch simultaneously).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Wipe each run's output dir first."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = (ROOT / args.output_dir).resolve()
    env_path = ROOT / ".env"
    env_contents = env_path.read_text() if env_path.exists() else None

    # One run per (project, mode); each a uniquely-named dir under the output dir.
    specs: list[RunSpec] = []
    for project in args.projects:
        text = load_proposal(project)
        for mode in args.modes:
            out_dir = base / f"{project}_{mode}"
            if args.force:
                clean_output_dir(out_dir)
            specs.append(
                RunSpec(
                    proposal=project,
                    proposal_text=text,
                    mode=mode,
                    model=args.model,
                    out_dir=out_dir,
                    thinking=args.thinking,
                    command_timeout=None,  # no timeout — run to completion
                    env_contents=env_contents,
                )
            )

    max_concurrent = args.max_concurrent or len(specs)
    print(
        f"Launching {len(specs)} runs ({len(args.projects)} projects x {len(args.modes)} modes), all at once:"
    )
    for project in args.projects:
        print(f"  - {project}")
    print(
        f"Modes: {', '.join(args.modes)} | model: {args.model} | thinking: {args.thinking} | max_concurrent: {max_concurrent}"
    )
    print(f"Output: {base}/<project>_<mode>   (watch: ./view_agents.sh)\n")

    results = asyncio.run(run_many(specs, max_concurrent=max_concurrent))

    print("\n=== results ===")
    for r in sorted(results, key=lambda x: (x.spec.proposal, x.spec.mode)):
        line = f"  {r.spec.proposal:46} {r.spec.mode:11} {r.status:9} sub-sessions={r.run_loop_sessions}"
        if r.error:
            line += f"  error={r.error}"
        print(line)


if __name__ == "__main__":
    main()
