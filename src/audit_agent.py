"""Audit-agent runner: run a read-only ``pi`` agent over a finished run and have
it produce artifacts (a write-up, figures, …) in a fresh writable working dir.

Shared infrastructure for the experiments that audit a completed run
(``experiments/04_blogpost_gen``, ``experiments/05_figures_gen``, …):

  - the source run is bind-mounted READ-ONLY at ``/source`` (the agent can read
    every file — code, transcripts, results — but physically cannot modify it),
  - a fresh writable working dir is the agent's CWD at ``/workspace``,
  - matplotlib / pandas / numpy from the project venv are on PATH so it can plot.

Each experiment supplies its own task PROMPT and decides which artifacts to keep.
``generate()`` is generic: it stages the two reference docs into the CWD, runs the
agent to completion, and returns the work dir + the path to the agent's own session
transcript (so the trajectory can be audited).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from src import DEFAULT_GPT_MODEL, sandbox
from src.runner_utils import parse_env_text

ROOT = Path(__file__).resolve().parents[1]

# Write-ups and figures are writing/design tasks, so default to a GPT model.
DEFAULT_MODEL = DEFAULT_GPT_MODEL
THINKING_DEFAULT = "high"
DEFAULT_TIMEOUT = None  # no timeout by default: the agent runs to completion


def is_run_dir(path: Path) -> bool:
    """A slopbench run/project dir is recognised by its ``.pi_transcripts/``."""
    return (path / ".pi_transcripts").is_dir()


# --------------------------------------------------------------------------- #
# Reference docs staged into the agent's CWD
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
        "Write your outputs ONLY into your CWD (/workspace) — see the task prompt for"
        " exactly what to produce.",
    ]
    return "\n".join(lines) + "\n"


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


def list_plots(work_dir: str | Path) -> list[str]:
    """The .png/.pdf figures the agent produced under ``work_dir/final_plots``."""
    p = Path(work_dir) / "final_plots"
    if not p.is_dir():
        return []
    return sorted(f.name for f in p.glob("*") if f.suffix.lower() in (".png", ".pdf"))


def generate(
    run_dir: str | Path,
    work_dir: str | Path,
    prompt: str,
    *,
    model: str | None = None,
    thinking: str = THINKING_DEFAULT,
    timeout: int | None = DEFAULT_TIMEOUT,
    env_text: str | None = None,
    on_log=None,
) -> dict:
    """Run an audit agent (run mounted read-only at /source, CWD = ``work_dir``)
    with the given ``prompt``. Returns ``{returncode, timed_out, session,
    work_dir}``; the caller reads whatever artifacts it wants out of ``work_dir``.
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
        model or DEFAULT_MODEL,
        "--thinking",
        thinking,
        "--mode",
        "json",
        prompt,
    ]
    argv = sandbox.build_argv(
        work, inner, extra_ro_dest_binds=((str(run_dir), "/source"),)
    )
    timed_out = False
    with (work / "agent_stdout.log").open("wb") as log:
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
    return {
        "returncode": proc.poll(),
        "timed_out": timed_out,
        "session": str(work / "session.jsonl"),
        "work_dir": str(work),
    }


def _progress(work: Path) -> str:
    sess = work / "session.jsonl"
    size = sess.stat().st_size if sess.exists() else 0
    return f"  …agent working: session={size}B plots={len(list_plots(work))}"
