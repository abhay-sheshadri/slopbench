#!/usr/bin/env python3
"""Launch pi research agents on the given projects.

This is a thin launcher: the project selection (and model/thinking) is
configured in run.sh — edit the config block there. One agent per project, all
launched concurrently, with no timeout (runs execute to completion). Each run is
a browsable directory at outputs/03_run_agents/<project>_multi_phase/; watch them
live with ./view_agents.sh.
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
from src.agent_runner import RUN_DIR_SUFFIX, RunSpec, run_many  # noqa: E402
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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume each run from its existing output dir (continue where it stopped).",
    )
    parser.add_argument(
        "--continue-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Relaunch each *completed* run as a continuation: the file's contents "
        "become the new instructions (the main planner rejects its prior 'all "
        "complete' decision and plans the additional work).",
    )
    parser.add_argument(
        "--run-loop-args",
        default="",
        metavar="ARGS",
        help="Extra arguments appended to the /run-loop command, e.g. "
        '--run-loop-args "--single-dir" to run all phases in one work/ directory.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.force and args.resume:
        raise SystemExit("--force and --resume are mutually exclusive.")
    if args.continue_file and (args.force or args.resume):
        raise SystemExit("--continue-file is mutually exclusive with --force/--resume.")
    continue_instructions = None
    if args.continue_file:
        if not args.continue_file.exists():
            raise SystemExit(f"Continue file not found: {args.continue_file}")
        continue_instructions = args.continue_file.read_text()
        if not continue_instructions.strip():
            raise SystemExit(f"Continue file is empty: {args.continue_file}")
    base = (ROOT / args.output_dir).resolve()
    env_path = ROOT / ".env"
    env_contents = env_path.read_text() if env_path.exists() else None

    # One run per project; each a uniquely-named dir under the output dir.
    specs: list[RunSpec] = []
    for project in args.projects:
        text = load_proposal(project)
        out_dir = base / f"{project}_{RUN_DIR_SUFFIX}"
        if args.force:
            clean_output_dir(out_dir)
        specs.append(
            RunSpec(
                proposal=project,
                proposal_text=text,
                model=args.model,
                out_dir=out_dir,
                thinking=args.thinking,
                command_timeout=None,  # no timeout — run to completion
                env_contents=env_contents,
                resume=args.resume,
                continue_instructions=continue_instructions,
                run_loop_args=args.run_loop_args,
            )
        )

    max_concurrent = args.max_concurrent or len(specs)
    print(f"Launching {len(specs)} runs, all at once:")
    for project in args.projects:
        print(f"  - {project}")
    print(
        f"model: {args.model} | thinking: {args.thinking} | max_concurrent: {max_concurrent}"
    )
    print(f"Output: {base}/<project>_{RUN_DIR_SUFFIX}   (watch: ./view_agents.sh)\n")

    results = asyncio.run(run_many(specs, max_concurrent=max_concurrent))

    print("\n=== results ===")
    for r in sorted(results, key=lambda x: x.spec.proposal):
        line = f"  {r.spec.proposal:46} {r.status:9} sub-sessions={r.run_loop_sessions}"
        if r.error:
            line += f"  error={r.error}"
        print(line)


if __name__ == "__main__":
    main()
