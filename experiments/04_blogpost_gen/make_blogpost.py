#!/usr/bin/env python3
"""Generate a clean blogpost-style write-up for one completed run.

A read-only oversight agent audits the run (its code, transcripts, results) and
writes a clear, faithful blogpost + figures. The source run is mounted READ-ONLY;
the agent works in a throwaway dir, and only the final artifacts are copied into
``outputs/04_blogpost_gen/<run-name>/``:
    final_writeup.md
    final_plots/*.png|*.pdf
    blogpost_agent_session.jsonl   (the agent's own trajectory, for auditing)

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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import audit_agent  # noqa: E402

# Writing task -> GPT model by default; override with BLOGPOST_MODEL or --model.
BLOGPOST_MODEL = os.environ.get("BLOGPOST_MODEL", audit_agent.DEFAULT_MODEL)

PROMPT = """# Audit a run and turn it into a clean write-up

Audit and clean up the results of another agent that worked on a research project
autonomously, and convert what it produced into a clear write-up in the style of a
post on Anthropic's Alignment Science blog. Aim for a short, front-loaded post with
standard section headings: a brief Introduction (motivation, prior work, a preview of
the key results), a short Methods section, then Results ordered by importance
(replication first if there is one), then takeaways — with the technical detail left
to appendices that can run longer than the post.

Your current working directory (/workspace) is a fresh, WRITABLE output dir. The
source run is mounted READ-ONLY at /source — read from there freely, but never write
outside your CWD.

Two reference files are in your CWD — READ BOTH before doing anything else:
- RUN_DIR_STRUCTURE.md — the run-dir layout, the two modes (goal / multi_phase),
  how to read transcripts (jq), and how to run python for plots.
- TRACE_INDEX.md — the concrete paths for THIS run.

Required artifacts in your CWD when you finish:
1. ./final_writeup.md — the write-up
2. ./final_plots/ — every figure you cite, saved as BOTH .png and .pdf

## Read the whole run before writing anything
Sweep the ENTIRE run in detail — every phase, not just the latest. Read the per-phase
write-ups and progress logs and the rolling write_up.md (the agent's OWN summary — a
map, NOT ground truth). Audit the actual experiment code. Verify headline numbers
against the raw .csv / .jsonl / .json files the run produced — do NOT repeat a number
you haven't traced to a file. You MUST also sample the per-phase session transcripts
with jq (see RUN_DIR_STRUCTURE.md / TRACE_INDEX.md): at minimum cross-check the single
most important claim AND one failed/abandoned approach against what the agent ACTUALLY
did, since write-ups routinely misdescribe or omit what happened. Do not rely on the
write-ups alone — the plots, numbers, and prose must all trace to first-hand artifacts
you opened yourself.

## Writing Instructions
Aim for roughly this structure, using the standard section headings Introduction,
Methods, and Results, keeping the main body short and leaving the technical detail to
the appendices:

1. Introduction (a few short paragraphs): brief motivation, a brief note on the prior
   work this builds on, and a short preview of the key results, ordered by importance.
   Whenever you reference prior work, cite it (name the paper/authors and include a
   link), drawing on the references in the proposal's related-work section rather
   than inventing citations.
2. Methods (short): the setup and approach in enough detail that the results are
   interpretable — the model(s), data, and what was actually measured — with the full
   detail left to the appendices.
3. Results, organised around the findings rather than what the agent did: the
   replication of prior results first (if any) — citing the work being replicated
   and saying how closely it matches — then the findings from biggest to
   smallest, each as a short claim followed by a short paragraph on the analysis and
   evidence. This LessWrong post is a useful reference for the style:
   <https://www.lesswrong.com/posts/LqDjxSceFz8tjMe2j/auditbench-evaluating-alignment-auditing-techniques-on>.
   If useful, we should also have example representative model outputs/transcripts or examples from the training data
   so that the reader can quickly verify that the setup makes sense.
   Wherever possible, contextualize each finding against known results from other
   papers — say whether it agrees with, extends, quantitatively compares to, or
   contradicts what prior work found (citing it) — so the reader sees how the result
   fits into the broader literature rather than in isolation.
4. Takeaways: a short section on the conclusions, open questions, and implications.

Appendices (which can be longer than the post itself): setup, methods, ablations,
controls, secondary results, cost, and reproducibility notes. Reference each appendix
from the main body.

Figures:
- Spend real time on how to present figures cleanly.
- AI-generated figures usually have too much text on them. Keep labels and legends clean and elegant, and push detail into the caption below.
- Define each label fully in the legend: spell out what every series/line/bar is, with no undefined abbreviations or cryptic shorthand, so the reader can tell the labels apart from the legend alone (keep the wording short, but complete).
- Really avoid cryptic shorthand anywhere a reader looks — legends, axis labels, titles, and tick labels. Internal names from the run (e.g. `cfg3`, `exp_v2`, `kto_sft`, `m1`/`m2`, `acc`, `pp1`) are meaningless to an outside reader: replace every one with the plain-English thing it stands for ("KTO adversarial training", "accuracy", etc.). If an abbreviation is truly unavoidable, define it in the caption. A reader who has never seen the run should understand the figure without guessing.
- Default to small figsizes with big, short text.
- Save each cited figure to ./final_plots/ as BOTH .png and .pdf and reference it with a relative path, e.g. `![Fig 1: headline](final_plots/fig1_headline.png)`.

Read the draft from the outside:
- Go over the draft sentence by sentence and, for each one, ask: "is this a sentence
  I could actually read in a post on LessWrong?" Cut or rewrite anything that reads
  like AI filler — throat-clearing, vague hype, hollow contrast ("not just X, but
  Y"), restating the obvious, or padding. Keep only sentences that carry real content
  in a voice a thoughtful human would actually write.
- When you mention prior work, cite it (author/title + link); only use citations
  that appear in the proposal or that you verified against an artifact in the run —
  never fabricate a reference. A short "References" list at the end is fine.
- Try to communicate clearly and use common words or ML terminology.
- Please don't reference the AI agent doing research, the goal here is to have a finished product that can be submitted to a conference, not a summary of the agent's work
- Keep the document understandable to humans. Assume the readers are very intelligent but are not familiar with the jargon of this subfield — define or avoid jargon.
- Re-read your draft as if you had only read the proposal and nothing else from the run. Would you follow it on first read? If not, fix it.
- Don't miss important things the agent did that the reader should know about. Sweep the run with that lens before calling the writeup done.

When done, ./final_writeup.md and ./final_plots/ (at least the headline figure as
.png + .pdf) must exist. Write the report to the file; you don't need to print it.
"""


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
        "--timeout",
        type=int,
        default=audit_agent.DEFAULT_TIMEOUT,
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
        f"Model: {args.model} | thinking: {args.thinking} | timeout: {timeout}\n"
        "--- agent auditing the run (this can take many minutes) ---",
        flush=True,
    )

    res = audit_agent.generate(
        run_dir,
        work,
        PROMPT,
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
    writeup = work / "final_writeup.md"
    if not writeup.exists():
        print(
            f"FAILED: no final_writeup.md produced (rc={res['returncode']} "
            f"timed_out={res['timed_out']}).\n"
            f"Agent stdout log: {work}/agent_stdout.log\n"
            f"Agent session:    {res['session']}"
        )
        raise SystemExit(1)

    plots = audit_agent.list_plots(work)
    (out / "final_plots").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(writeup, out / "final_writeup.md")
    for name in plots:
        shutil.copyfile(work / "final_plots" / name, out / "final_plots" / name)
    if Path(res["session"]).exists():
        shutil.copyfile(res["session"], out / "blogpost_agent_session.jsonl")

    print(f"Write-up: {out / 'final_writeup.md'} ({writeup.stat().st_size} bytes)")
    print(
        f"Plots:    {out / 'final_plots'} ({len(plots)} files: {', '.join(plots) or 'none'})"
    )
    print(f"Agent trajectory (for audit): {out / 'blogpost_agent_session.jsonl'}")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
