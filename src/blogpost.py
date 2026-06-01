"""Blogpost meta-agent: audit one completed run and write a clean write-up.

This is the standalone counterpart to the (removed) Run-Lens "writeup" button.
It runs a read-only oversight ``pi`` agent over a finished run directory and has
it produce a clear, faithful, LessWrong-style write-up plus figures.

Sandbox model (same bubblewrap runner as the rest of the project):
  - the **source run** is bind-mounted READ-ONLY at ``/source`` (the agent can read
    every file — code, transcripts, results — but physically cannot modify it),
  - a fresh **writable working dir** is the agent's CWD at ``/workspace``, where it
    writes ``final_writeup.md`` + ``final_plots/`` and its own session log,
  - matplotlib/pandas/numpy from the project venv are on PATH so it can replot.

``generate()`` runs the agent to completion and returns the produced artifacts +
the path to the agent's own session transcript (so the trajectory can be audited).
The prompt is adapted from redwoodresearch/research-projects
``experiments/blogposts/blogpost_instructions.md``.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from src import DEFAULT_GPT_MODEL, sandbox
from src.runner_utils import parse_env_text

ROOT = Path(__file__).resolve().parents[1]

# The write-up is a WRITING task, so it defaults to a GPT model (better prose);
# override with the BLOGPOST_MODEL env var or --model.
BLOGPOST_MODEL = os.environ.get("BLOGPOST_MODEL", DEFAULT_GPT_MODEL)
WRITEUP_THINKING_DEFAULT = "high"
DEFAULT_TIMEOUT = None  # no timeout by default: the agent runs to completion


def is_run_dir(path: Path) -> bool:
    """A slopbench run/project dir is recognised by its ``.pi_transcripts/``."""
    return (path / ".pi_transcripts").is_dir()


# --------------------------------------------------------------------------- #
# Prompt + reference docs staged into the agent's CWD
# --------------------------------------------------------------------------- #
def structure_doc() -> str:
    """RUN_DIR_STRUCTURE.md — the general layout, staged into the CWD."""
    return """# slopbench run directory structure

The source run is mounted READ-ONLY at /source. Read freely there, but write ONLY
inside your current working directory (/workspace). TRACE_INDEX.md (in your CWD)
has the concrete paths for this specific run.

## Layout (/source)
- proposal.md                         the project proposal/spec (may also be under planner/)
- .pi_transcripts/session.jsonl       the execution agent's full transcript
                                      (goal mode: the worker; multi_phase: the run-loop orchestrator)
- .pi_transcripts/planner.session.jsonl   the up-front planner transcript (/init-planner)
- .pi_transcripts/manifest.json       mode / model / status
- .pi_transcripts/run_loop_sessions/*.jsonl   (finished multi_phase) folded per-phase sub-agent
                                      transcripts: worker_<seg>_<phase>.jsonl, reviewer_*, phase_planner_*
- .home/.pi/agent/sessions/*/*.jsonl  (live multi_phase) the same per-phase sub-agent transcripts
- planner/OVERALL_PLAN.md             the segment/phase plan (multi_phase)
- planner/INSTRUCTIONS_*.md           per-phase worker instructions
- planner/RUN_LOOP_STATE.json         run-loop state: segments, phases, decisions, costUsd
- writeup/ or writeups/               the run agent's OWN write-ups: write_up.md (rolling summary),
                                      write_up_<phase>.md, progress_log*.md, continuation_context.md
- <the agent's own code, data, results, plots>   experiment artifacts (names vary by project)

## The two modes
- goal mode: a single execution agent (session.jsonl) pursuing a goal; no phases.
- multi_phase: a planner + a run-loop that decomposes the work into segments/phases. Each phase has
  worker / reviewer / phase_planner sub-agent sessions and per-phase write-ups
  (write_up_<phase>.md, progress_log_<phase>.md). RUN_LOOP_STATE.json lists completed phases and the
  reviewer's decisions. READ EVERY PHASE — results and dead-ends often live only in the phase where
  they were produced; the rolling write_up.md is the agent's own summary, not ground truth.

## Reading order
1. /source/proposal.md (and planner/OVERALL_PLAN.md if present)
2. The rolling /source/writeup(s)/write_up.md — a map, NOT ground truth
3. Per-phase write-ups (write_up_<phase>.md, progress_log_<phase>.md) across ALL phases
4. The actual code + the raw result/data files (verify every headline number yourself)
5. Sample the per-phase sub-agent session transcripts wherever prose is ambiguous

## Reading the transcripts (pi session JSONL, one object per line — use jq, don't cat whole)
```bash
# assistant text blocks in a session
jq -r 'select(.type=="message" and .message.role=="assistant") | .message.content[]? \\
  | select(.type=="text") | .text' SESSION.jsonl
# tool calls (name + truncated args)
jq -rc 'select(.type=="message" and .message.role=="assistant") | .message.content[]? \\
  | select(.type=="toolCall") | [.name, (.arguments|tostring)[0:200]] | @tsv' SESSION.jsonl
```

## Running Python (for plots)
matplotlib / pandas / numpy are on PATH (`python3`). Read data via absolute /source/... paths and write
figures into ./final_plots/ in your CWD. Never write under /source.
"""


def trace_index(run_dir: Path) -> str:
    """TRACE_INDEX.md — concrete /source paths that exist for THIS run."""
    tdir = run_dir / ".pi_transcripts"
    lines = [
        f"# Trace index for {run_dir.name}",
        "",
        "Source run is read-only at /source; write only in your CWD (/workspace).",
        "",
        "## Source run files that exist (read-only at /source)",
    ]
    for label, relp in (
        ("proposal", "proposal.md"),
        ("overall plan", "planner/OVERALL_PLAN.md"),
        ("execution transcript", ".pi_transcripts/session.jsonl"),
        ("planner transcript", ".pi_transcripts/planner.session.jsonl"),
        ("manifest", ".pi_transcripts/manifest.json"),
        ("run-loop state", "planner/RUN_LOOP_STATE.json"),
    ):
        if (run_dir / relp).exists():
            lines.append(f"- {label}: /source/{relp}")
    if (tdir / "run_loop_sessions").is_dir():
        lines.append(
            "- per-phase sub-agent transcripts: /source/.pi_transcripts/run_loop_sessions/*.jsonl"
        )
    elif (run_dir / ".home" / ".pi").is_dir():
        lines.append(
            "- per-phase sub-agent transcripts: /source/.home/.pi/agent/sessions/*/*.jsonl"
        )
    if (run_dir / "planner").is_dir():
        lines.append("- per-phase instructions: /source/planner/INSTRUCTIONS_*.md")
    for d in ("writeup", "writeups"):
        if (run_dir / d).is_dir():
            lines.append(f"- the run agent's own write-ups: /source/{d}/")
    lines += [
        "",
        "## Output — write ONLY into your CWD (/workspace)",
        "- ./final_writeup.md",
        "- ./final_plots/  (every cited figure as BOTH .png and .pdf)",
    ]
    return "\n".join(lines) + "\n"


def prompt() -> str:
    """The audit->write-up instructions (adapted from the blogposts workflow)."""
    return """# Audit a run and turn it into a clean write-up

Audit and clean up the results of another agent that worked on a research project
autonomously, and convert what it produced into a clear write-up in the style of a
post on Anthropic's Alignment Science blog: open with motivation; then, if the
run reproduces a result from prior work that it builds on, that reproduction first;
then the main new result; then the supporting results presented as a build-up where
each result leads into the next.

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

## Writing Instructions
Structure:
- Have a short intro that discusses the context and value of this research
- Before diving into new results, highlight the reproduction of previous results from the literature
- Structure the blogpost around the key results, not around what the agent did.
- Model the structure on this LessWrong post: <https://www.lesswrong.com/posts/LqDjxSceFz8tjMe2j/auditbench-evaluating-alignment-auditing-techniques-on>. Enumerate findings ordered by importance, state each finding cleanly, and follow it with a short paragraph elaborating the key analysis.
- Push technical details, ablations, and minor results into appendices, and reference each appendix from the main body.

Figures:
- Spend real time on how to present figures cleanly.
- AI-generated figures usually have too much text on them. Keep labels and legends clean and elegant, and push detail into the caption below.
- Default to small figsizes with big, short text.

Read the draft from the outside:
- Keep the document understandable to humans. Assume the humans reading are very intelligent, but aren't familiar with your non-standard jargon.
- Re-read your draft as if you had only read the proposal and nothing else from the run. Would you follow it on first read? If not, fix it.
- Don't miss important things the agent did that the reader should know about. Sweep the run with that lens before calling the writeup done.

When done, ./final_writeup.md and ./final_plots/ (at least the headline figure as
.png + .pdf) must exist. Write the report to the file; you don't need to print it.
"""


# --------------------------------------------------------------------------- #
# Run the agent
# --------------------------------------------------------------------------- #
def _env(env_text: str | None) -> dict[str, str]:
    overrides = parse_env_text(env_text) if env_text else {}
    if not env_text:
        env_path = ROOT / ".env"
        if env_path.exists():
            overrides = parse_env_text(env_path.read_text())
    return sandbox.default_env(overrides)  # HOME=/workspace/.home (writable CWD)


def generate(
    run_dir: str | Path,
    work_dir: str | Path,
    *,
    model: str | None = None,
    thinking: str = WRITEUP_THINKING_DEFAULT,
    timeout: int | None = DEFAULT_TIMEOUT,
    env_text: str | None = None,
    on_log=None,
) -> dict:
    """Run the blogpost agent over ``run_dir`` with CWD ``work_dir``.

    Returns ``{returncode, writeup, plots, session, work_dir, timed_out}``. The
    write-up and plots are read from ``work_dir`` (the agent's CWD); copying them
    to a project's ``clean_writeups/`` is the caller's job.
    """
    run_dir = Path(run_dir).resolve()
    work = Path(work_dir).resolve()
    if sandbox.available() is None:
        raise RuntimeError("bubblewrap (bwrap) is not installed")
    if not is_run_dir(run_dir):
        raise ValueError(
            f"{run_dir} is not a run/project dir (no .pi_transcripts/ found)"
        )
    work.mkdir(parents=True, exist_ok=True)
    (work / "final_plots").mkdir(parents=True, exist_ok=True)
    (work / "RUN_DIR_STRUCTURE.md").write_text(structure_doc())
    (work / "TRACE_INDEX.md").write_text(trace_index(run_dir))

    inner = [
        "pi",
        "-p",
        "--session",
        f"{sandbox.WORKSPACE}/session.jsonl",
        "--model",
        model or BLOGPOST_MODEL,
        "--thinking",
        thinking,
        "--mode",
        "json",
        prompt(),
    ]
    argv = sandbox.build_argv(
        work, inner, extra_ro_dest_binds=((str(run_dir), "/source"),)
    )
    log_path = work / "agent_stdout.log"
    timed_out = False
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            argv,
            env=_env(env_text),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = (time.time() + timeout) if timeout and timeout > 0 else None
        while proc.poll() is None:
            if deadline is not None and time.time() > deadline:
                proc.kill()
                timed_out = True
                break
            if on_log:
                on_log(_progress(work))
            time.sleep(5)
    rc = proc.poll()
    wp = work / "final_writeup.md"
    plots = sorted(
        p.name
        for p in (work / "final_plots").glob("*")
        if p.suffix.lower() in (".png", ".pdf")
    )
    return {
        "returncode": rc,
        "timed_out": timed_out,
        "writeup": wp.read_text(errors="replace") if wp.exists() else None,
        "writeup_path": str(wp) if wp.exists() else None,
        "plots": plots,
        "session": str(work / "session.jsonl"),
        "work_dir": str(work),
    }


def _progress(work: Path) -> str:
    sess = work / "session.jsonl"
    wp = work / "final_writeup.md"
    nplots = (
        len(list((work / "final_plots").glob("*")))
        if (work / "final_plots").is_dir()
        else 0
    )
    size = sess.stat().st_size if sess.exists() else 0
    return f"  …agent working: session={size}B writeup={'yes' if wp.exists() else 'no'} plots={nplots}"
