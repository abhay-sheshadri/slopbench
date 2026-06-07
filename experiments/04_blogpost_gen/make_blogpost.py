#!/usr/bin/env python3
"""Generate a clean blogpost-style write-up for one completed run.

A read-only oversight agent audits the run (its code, transcripts, results) and
writes a clear, faithful blogpost + figures. The source run is mounted READ-ONLY;
the agent works in a throwaway dir, and only the final artifacts are copied into
``outputs/04_blogpost_gen/<run-name>/``:
    final_writeup.md
    final_plots/*.png|*.pdf
    blogpost_agent_session.jsonl   (the agent's own trajectory, for auditing)
    REVIEW_round*.md               (each review round's findings, for auditing)

To make the write-up more robust to the writing instructions, the author does not
work alone. After the author finishes a draft (while the source code is still
mounted), an adversarial reviewer agent reads the draft and figures and writes a
concrete list of problems judged against the same instructions; the author session
is then resumed with those findings and asked to fix them. This repeats for
``--review-rounds`` rounds (default 1).

The agent prompts live as Jinja2 templates in ``prompts/`` next to this file:
    prompts/_writing_instructions.md.j2   shared rubric (author + reviewer)
    prompts/author.md.j2                  audit + write the first draft
    prompts/reviewer.md.j2                 surface concrete problems -> REVIEW file
    prompts/fix.md.j2                      resume the author to fix the problems

Usage:
    python experiments/04_blogpost_gen/make_blogpost.py <path-to-run-dir>
    ./experiments/04_blogpost_gen/make_blogpost.py \\
        outputs/03_run_agents/empirical_introspection_science_multi_phase

The argument must be an actual run/project dir (one that contains
``.pi_transcripts/``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import DEFAULT_MODEL, audit_agent  # noqa: E402

# The write-up is a writing/judgement task -> default to Claude Opus 4.8.
# Override with BLOGPOST_MODEL or --model.
BLOGPOST_MODEL = os.environ.get("BLOGPOST_MODEL", DEFAULT_MODEL)

_JINJA = Environment(
    loader=FileSystemLoader(HERE / "prompts"),
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def render(template: str, **ctx: object) -> str:
    """Render a prompt template from ``prompts/``."""
    return _JINJA.get_template(template).render(**ctx)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "run_dir", help="Path to a run/project dir (must contain .pi_transcripts/)."
    )
    ap.add_argument("--model", default=BLOGPOST_MODEL)
    ap.add_argument("--thinking", default=audit_agent.THINKING_DEFAULT)
    ap.add_argument(
        "--review-rounds",
        type=int,
        default=1,
        help="Reviewer->fix rounds after the first draft (default: 1; 0 disables review).",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=audit_agent.DEFAULT_TIMEOUT,
        help="Max seconds for each agent turn (default: no timeout — run to completion).",
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
    if not audit_agent.is_run_dir(run_dir):
        raise SystemExit(
            f"{run_dir} is not a run/project dir (no .pi_transcripts/ found).\n"
            "Pass a run dir, e.g. outputs/03_run_agents/<proposal>_<mode>."
        )

    work = Path(tempfile.mkdtemp(prefix="blogpost_"))
    timeout = f"{args.timeout}s" if args.timeout else "none"
    print(
        f"Run dir:  {run_dir}\n"
        f"Work dir: {work}\n"
        f"Model: {args.model} | thinking: {args.thinking} | timeout: {timeout} | "
        f"review rounds: {args.review_rounds}",
        flush=True,
    )

    common = dict(
        model=args.model,
        thinking=args.thinking,
        timeout=args.timeout,
        on_log=lambda m: print(m, flush=True),
    )
    writeup = work / "final_writeup.md"

    # 1. Author the first draft (stages the reference docs into the work dir).
    print("--- author: auditing the run and drafting (this can take many minutes) ---")
    audit_agent.stage_reference_docs(work, run_dir)
    res = audit_agent.run_pi(
        run_dir,
        work,
        render("author.md.j2"),
        session="session.jsonl",
        log_name="agent_stdout_author.log",
        **common,
    )
    if not writeup.exists():
        _fail(work, res, "author produced no final_writeup.md")

    # 2. Reviewer -> fix loop, resuming the same author session each round.
    reviews: list[Path] = []
    for rnd in range(1, max(0, args.review_rounds) + 1):
        review_file = f"REVIEW_round{rnd}.md"
        print(f"--- review round {rnd}: reviewer surfacing problems ---")
        audit_agent.run_pi(
            run_dir,
            work,
            render("reviewer.md.j2", review_file=review_file),
            session=f"reviewer_round{rnd}.jsonl",
            **common,
        )
        if not (work / review_file).exists():
            print(
                f"  reviewer wrote no {review_file}; stopping review loop.", flush=True
            )
            break
        reviews.append(work / review_file)
        print(f"--- review round {rnd}: author fixing the flagged problems ---")
        res = audit_agent.run_pi(
            run_dir,
            work,
            render("fix.md.j2", review_file=review_file),
            session="session.jsonl",  # resume the author conversation
            log_name=f"agent_stdout_fix_round{rnd}.log",
            **common,
        )
        if not writeup.exists():
            _fail(work, res, f"author removed final_writeup.md during fix round {rnd}")

    # 3. Copy out the final artifacts.
    print("--- done ---")
    out = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else ROOT / "outputs" / "04_blogpost_gen" / run_dir.name
    )
    plots = audit_agent.list_plots(work)
    (out / "final_plots").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(writeup, out / "final_writeup.md")
    for name in plots:
        shutil.copyfile(work / "final_plots" / name, out / "final_plots" / name)
    for review in reviews:
        shutil.copyfile(review, out / review.name)
    if (work / "REVIEW_RESPONSE.md").exists():
        shutil.copyfile(work / "REVIEW_RESPONSE.md", out / "REVIEW_RESPONSE.md")
    if Path(res["session"]).exists():
        shutil.copyfile(res["session"], out / "blogpost_agent_session.jsonl")

    print(f"Write-up: {out / 'final_writeup.md'} ({writeup.stat().st_size} bytes)")
    print(
        f"Plots:    {out / 'final_plots'} ({len(plots)} files: {', '.join(plots) or 'none'})"
    )
    print(
        f"Reviews:  {len(reviews)} round(s) " + (f"-> {out}" if reviews else "(none)")
    )
    print(f"Agent trajectory (for audit): {out / 'blogpost_agent_session.jsonl'}")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)


def _fail(work: Path, res: dict, why: str) -> None:
    print(
        f"FAILED: {why} (rc={res['returncode']} timed_out={res['timed_out']}).\n"
        f"Agent stdout logs: {work}/agent_stdout_*.log\n"
        f"Agent session:     {res['session']}"
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
