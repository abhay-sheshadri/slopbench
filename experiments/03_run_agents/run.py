"""Run pi research agents on proposals in bwrap sandboxes — both modes by default.

No Inspect, no Docker: drives lightweight bwrap sandboxes directly via
src.agent_runner. Each (proposal, mode) is one browsable run directory under
outputs/03_run_agents/<proposal>_<mode>/. Watch live or review finished
runs with ./view_agents.sh.
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
DEFAULT_OUTPUT_DIR = "outputs/03_run_agents"


def list_proposals() -> list[str]:
    return sorted(path.stem for path in PROPOSALS_DIR.glob("*.md"))


def load_proposal(name: str) -> str:
    path = PROPOSALS_DIR / f"{name}.md"
    if not path.exists():
        raise SystemExit(f"Proposal not found: {path}")
    return path.read_text()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List proposals and exit.")
    parser.add_argument(
        "--proposals", nargs="+", default=None, metavar="NAME", help="Default: all."
    )
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=21600,
        help="Per-pi-command wall-clock cap (s).",
    )
    parser.add_argument(
        "--run-loop-args",
        default="",
        help="Extra args for /run-loop (multi_phase only).",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=2, help="Max containers running at once."
    )
    parser.add_argument(
        "--force", action="store_true", help="Wipe each proposal's output dir first."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    available = list_proposals()
    if args.list:
        for proposal in available:
            print(proposal)
        return

    proposals = args.proposals or available
    unknown = sorted(set(proposals) - set(available))
    if unknown:
        raise SystemExit(f"Unknown proposal(s): {', '.join(unknown)}")

    base = (ROOT / args.output_dir).resolve()
    env_path = ROOT / ".env"
    env_contents = env_path.read_text() if env_path.exists() else None

    # One run per (proposal, mode); each is a uniquely-named directory directly
    # under the experiment output dir. run_many executes them all in parallel.
    specs: list[RunSpec] = []
    for proposal in proposals:
        text = load_proposal(proposal)
        for mode in args.modes:
            out_dir = base / f"{proposal}_{mode}"
            if args.force:
                clean_output_dir(out_dir)
            specs.append(
                RunSpec(
                    proposal=proposal,
                    proposal_text=text,
                    mode=mode,
                    model=args.model,
                    out_dir=out_dir,
                    thinking=args.thinking,
                    command_timeout=args.command_timeout,
                    run_loop_args=args.run_loop_args,
                    env_contents=env_contents,
                )
            )

    print(f"Proposals: {', '.join(proposals)}")
    print(
        f"Modes: {', '.join(args.modes)} | model: {args.model} | runs: {len(specs)} | max_concurrent: {args.max_concurrent}"
    )
    print(f"Output: {base}/<proposal>_<mode>   (live view: ./view_agents.sh)\n")

    results = asyncio.run(run_many(specs, max_concurrent=args.max_concurrent))

    print("\n=== results ===")
    for r in sorted(results, key=lambda x: (x.spec.proposal, x.spec.mode)):
        line = f"  {r.spec.proposal:42} {r.spec.mode:11} {r.status:9} sub-sessions={r.run_loop_sessions}"
        if r.error:
            line += f"  error={r.error}"
        print(line)


if __name__ == "__main__":
    main()
