#!/usr/bin/env python3
"""Produce a small set of clear, comprehensive figures of a completed run's
main results.

A read-only oversight agent audits the run (its code, transcripts, results) and
makes a SMALL set of well-designed figures that highlight the most important
results, optimized for understandability. The source run is mounted READ-ONLY;
the agent works in a throwaway dir, and only the final artifacts are copied into
``outputs/05_figures_gen/<run-name>/``:
    final_plots/*.png|*.pdf
    FIGURES.md                  (each figure embedded inline + its caption)
    figures_agent_session.jsonl (the agent's own trajectory, for auditing)

Usage:
    python experiments/05_figures_gen/make_figures.py <path-to-run-dir>
    ./experiments/05_figures_gen/make_figures.py \\
        outputs/03_run_agents/empirical_introspection_science_multi_phase
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

# Figure design/plotting uses the shared pipeline model by default.
# Override with FIGURES_MODEL only when deliberately testing a variant.
FIGURES_MODEL = os.environ.get("FIGURES_MODEL", audit_agent.DEFAULT_MODEL)

PROMPT = """# Audit a run and make a small set of clear figures of its main results

Audit the results of another agent that worked on a research project autonomously,
and produce a set of figures that clearly communicate the project's results.

Your current working directory (/workspace) is a fresh, WRITABLE output dir. The
source run is mounted READ-ONLY at /source — read from there freely, but never write
outside your CWD.

Two reference files are in your CWD — READ BOTH before doing anything else:
- RUN_DIR_STRUCTURE.md — the run-dir layout, how to read transcripts (jq), and how to run
  python for plots.
- TRACE_INDEX.md — the concrete paths for THIS run.

## Read the run first — don't plot until you understand it
Read the proposal, the per-phase write-ups, the actual experiment code, and the raw
result/data files (results/ and data/). Figure out what the project's MAIN findings
actually are. Verify every number you put on a figure against the raw .csv / .jsonl /
.json file it comes from — do NOT plot a number you haven't traced to a file. Sample
the per-phase session transcripts with jq (see RUN_DIR_STRUCTURE.md / TRACE_INDEX.md)
whenever a prose summary is ambiguous about what actually happened. Don't trust the
run's own write-ups; the figures must trace to first-hand artifacts you opened.

## What to produce
- Generate a figure for each important result that you think can make its way into a
  paper on this topic.
    - If the agent reproduced any existing results, please make that its own plot and try
    to visualize it in a way similar to how it was plotted previously in other papers.
    - Try to focus on capturing the main results instead of secondary results.
- ./FIGURES.md — a single self-contained markdown document that a reader can just
  open and look at. Present the figures in order; for each one, EMBED the figure
  inline as a markdown image (e.g. `![](final_plots/fig1_name.png)` — reference the
  .png so it renders) immediately followed by a 2-4 sentence caption in plain
  language saying what the figure shows, the key numbers, and why it matters. The
  whole file should read as a clean figure-by-figure summary of the run's main
  results, each figure understandable on its own to a smart reader who knows the
  proposal but nothing else about the run.

## Make the figures clear and readable — this is the whole point
- Each figure should make one point cleanly. Pick the chart type that conveys that,
- Spend real effort on design: short, legible labels and legends; readable font sizes;
  uncluttered panels. AI-made figures usually have too much text on them — push detail
  into the caption, not onto the plot. Default to small figsizes with big, short text.
- Use clear titles and axis labels in plain words; define or avoid jargon.
- Show uncertainty where it matters (error bars / confidence intervals / n).
- Use color purposefully and consistently, and make sure it stays readable.

When done, ./final_plots/ (each figure as .png + .pdf) and ./FIGURES.md must exist.
You don't need to print anything.
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "run_dir", help="Path to a run/project dir (must contain .pi_transcripts/)."
    )
    ap.add_argument("--model", default=FIGURES_MODEL)
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
        help="Where to write the figures (default: outputs/05_figures_gen/<run-name>/).",
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

    work = Path(tempfile.mkdtemp(prefix="figures_"))
    timeout = f"{args.timeout}s" if args.timeout else "none"
    print(
        f"Run dir:  {run_dir}\n"
        f"Work dir: {work}\n"
        f"Model: {args.model} | thinking: {args.thinking} | timeout: {timeout}\n"
        "--- agent auditing the run and making figures (this can take many minutes) ---",
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
        else ROOT / "outputs" / "05_figures_gen" / run_dir.name
    )
    plots = audit_agent.list_plots(work)
    if not plots:
        print(
            f"FAILED: no figures produced in final_plots/ (rc={res['returncode']} "
            f"timed_out={res['timed_out']}).\n"
            f"Agent stdout log: {work}/agent_stdout.log\n"
            f"Agent session:    {res['session']}"
        )
        raise SystemExit(1)

    (out / "final_plots").mkdir(parents=True, exist_ok=True)
    for name in plots:
        shutil.copyfile(work / "final_plots" / name, out / "final_plots" / name)
    captions = work / "FIGURES.md"
    if captions.exists():
        shutil.copyfile(captions, out / "FIGURES.md")
    if Path(res["session"]).exists():
        shutil.copyfile(res["session"], out / "figures_agent_session.jsonl")

    print(f"Figures:  {out / 'final_plots'} ({len(plots)} files: {', '.join(plots)})")
    print(
        f"Captions: {out / 'FIGURES.md'}"
        + ("" if captions.exists() else "  (NOT produced)")
    )
    print(f"Agent trajectory (for audit): {out / 'figures_agent_session.jsonl'}")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
