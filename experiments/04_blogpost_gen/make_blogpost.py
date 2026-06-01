#!/usr/bin/env python3
"""Generate a clean blogpost-style write-up for one completed run.

A read-only oversight agent audits the run (its code, transcripts, results) and
writes a clear, faithful, LessWrong-style report + figures. The source run is
mounted READ-ONLY; the agent works in a throwaway dir, and only the final
artifacts are copied into ``<run-dir>/clean_writeups/``.

Usage:
    python experiments/04_blogpost_gen/make_blogpost.py <path-to-run-dir>
    ./experiments/04_blogpost_gen/make_blogpost.py \\
        outputs/03_run_agents/empirical_introspection_science_multi_phase

The argument must be an actual run/project dir (one that contains
``.pi_transcripts/``). Output goes under ``outputs/04_blogpost_gen/<run-name>/``:
    final_writeup.md
    final_plots/*.png|*.pdf
    blogpost_agent_session.jsonl   (the agent's own trajectory, kept so you can
        audit what it actually read)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import blogpost  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "run_dir", help="Path to a run/project dir (must contain .pi_transcripts/)."
    )
    ap.add_argument("--model", default=blogpost.BLOGPOST_MODEL)
    ap.add_argument("--thinking", default=blogpost.WRITEUP_THINKING_DEFAULT)
    ap.add_argument(
        "--timeout",
        type=int,
        default=blogpost.DEFAULT_TIMEOUT,
        help="Max seconds for the agent (default: no timeout — run to completion).",
    )
    ap.add_argument(
        "--keep-work",
        action="store_true",
        help="Don't delete the agent's throwaway work dir.",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Where to write the blogpost (default: outputs/04_blogpost_gen/<run-name>/).",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"Not a directory: {run_dir}")
    if not blogpost.is_run_dir(run_dir):
        raise SystemExit(
            f"{run_dir} is not a run/project dir (no .pi_transcripts/ found).\n"
            "Pass a run dir, e.g. outputs/03_run_agents/<proposal>_<mode>."
        )

    work = Path(tempfile.mkdtemp(prefix="blogpost_"))
    print(
        f"Run dir:  {run_dir}\n"
        f"Work dir: {work}\n"
        f"Model: {args.model} | thinking: {args.thinking} | timeout: {str(args.timeout) + 's' if args.timeout else 'none'}\n"
        "--- agent auditing the run (this can take many minutes) ---",
        flush=True,
    )

    res = blogpost.generate(
        run_dir,
        work,
        model=args.model,
        thinking=args.thinking,
        timeout=args.timeout,
        on_log=lambda m: print(m, flush=True),
    )

    print("--- done ---")
    out = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else ROOT / "outputs" / "04_blogpost_gen" / run_dir.name
    )
    if not res["writeup"]:
        print(
            f"FAILED: no final_writeup.md produced (rc={res['returncode']} "
            f"timed_out={res['timed_out']}).\n"
            f"Agent stdout log: {work}/agent_stdout.log\n"
            f"Agent session:    {res['session']}"
        )
        raise SystemExit(1)

    (out / "final_plots").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(res["writeup_path"], out / "final_writeup.md")
    for name in res["plots"]:
        shutil.copyfile(Path(work) / "final_plots" / name, out / "final_plots" / name)
    if Path(res["session"]).exists():
        shutil.copyfile(res["session"], out / "blogpost_agent_session.jsonl")

    print(f"Write-up: {out / 'final_writeup.md'} ({len(res['writeup'])} chars)")
    print(
        f"Plots:    {out / 'final_plots'} "
        f"({len(res['plots'])} files: {', '.join(res['plots']) or 'none'})"
    )
    print(f"Agent trajectory (for audit): {out / 'blogpost_agent_session.jsonl'}")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
