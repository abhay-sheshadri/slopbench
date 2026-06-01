"""Smoke test: run the api-key proposal through the pi agent in both modes.

Directly drives bwrap sandboxes via src.agent_runner (no Inspect, no Docker).
Each (mode) produces a single browsable run directory under
outputs/02_test_agent_run/<proposal>/<mode>/. Watch runs live (or review finished
ones) with ./view_agents.sh.
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

EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_PROPOSAL = EXPERIMENT_DIR / "api_key_smoke_test.md"
DEFAULT_OUTPUT_DIR = "outputs/02_test_agent_run"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--proposal-name", default="api_key_smoke_test")
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=None,
        help="Per-phase wall-clock cap (s). Default: no timeout (run to completion).",
    )
    parser.add_argument("--run-loop-args", default="")
    parser.add_argument("--max-concurrent", type=int, default=len(MODES))
    parser.add_argument(
        "--force", action="store_true", help="Wipe the proposal's output dir first."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume each run from its existing output dir (continue where it stopped).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.proposal.exists():
        raise SystemExit(f"Proposal not found: {args.proposal}")
    if args.force and args.resume:
        raise SystemExit("--force and --resume are mutually exclusive.")

    base = (ROOT / args.output_dir).resolve()
    env_path = ROOT / ".env"
    env_contents = env_path.read_text() if env_path.exists() else None
    text = args.proposal.read_text()

    # One run per mode, each a uniquely-named directory <proposal>_<mode> directly
    # under the experiment output dir. run_many runs them all in parallel.
    specs = []
    for mode in args.modes:
        out_dir = base / f"{args.proposal_name}_{mode}"
        if args.force:
            clean_output_dir(out_dir)
        specs.append(
            RunSpec(
                proposal=args.proposal_name,
                proposal_text=text,
                mode=mode,
                model=args.model,
                out_dir=out_dir,
                thinking=args.thinking,
                command_timeout=args.command_timeout,
                run_loop_args=args.run_loop_args,
                env_contents=env_contents,
                resume=args.resume,
            )
        )

    print(f"Proposal: {args.proposal_name} | modes: {args.modes} | model: {args.model}")
    print(
        f"Output:   {base}/{args.proposal_name}_<mode>   (live view: ./view_agents.sh)\n"
    )

    results = asyncio.run(run_many(specs, max_concurrent=args.max_concurrent))

    print("\n=== results ===")
    for r in results:
        line = f"  {r.spec.mode:11} {r.status:9} sub-sessions={r.run_loop_sessions}"
        if r.error:
            line += f"  error={r.error}"
        print(line + (f"  -> {r.agent_dir}" if r.agent_dir else ""))


if __name__ == "__main__":
    main()
