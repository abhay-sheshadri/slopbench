"""Shared infrastructure for read-only oversight agents over a finished run.

Several tools point a read-only ``pi`` agent at a completed slopbench run and have
it read the code/results/transcripts:

  - the blogpost author (``experiments/04``), the figures agent (``experiments/05``)
    and the automated blue-teamer (``experiments/08``), all via ``src/audit_agent``;
  - the interactive Run Lens in ``src/agent_viewer``.

They used to each hard-code two things that drifted apart: the description of a run's
directory layout, and the ``pi`` launch invocation. Both now live here so there is a
single source of truth.

Mount conventions still differ by tool and stay with the caller:
  - audit_agent mounts the run READ-ONLY at ``/source`` with a writable CWD at
    ``/workspace`` (it produces durable artifacts);
  - Run Lens mounts the run READ-ONLY *as* ``/workspace`` with a writable ``/lensjob``
    scratch (it streams an answer in place).
What's shared is the run-layout knowledge (:func:`key_locations`, :func:`run_layout_doc`,
:func:`trace_index`) and the launch primitives (:func:`pi_inner_argv`,
:func:`oversight_env`).
"""

from __future__ import annotations

from pathlib import Path

from src import sandbox
from src.runner_utils import parse_env_text

ROOT = Path(__file__).resolve().parents[1]


def is_run_dir(path: Path) -> bool:
    """A slopbench run/project dir is recognised by its ``.pi_transcripts/``."""
    return (path / ".pi_transcripts").is_dir()


# --------------------------------------------------------------------------- #
# Run-layout knowledge — the single source of truth for WHERE things live.
# --------------------------------------------------------------------------- #
def key_locations() -> list[tuple[str, str]]:
    """``(label, path-relative-to-run-root)`` for a run's important files.

    Globs are allowed. This is the canonical list every oversight tool orients
    from; keep :func:`run_layout_doc` consistent with it. Paths are relative to
    the run root, so each caller prefixes the mount it uses (``/source`` for
    audit_agent, ``/workspace`` for Run Lens).
    """
    return [
        ("proposal / spec", "proposal.md"),
        ("overall plan (multi_phase)", "planner/OVERALL_PLAN.md"),
        ("per-phase instructions", "planner/INSTRUCTIONS_*.md"),
        ("per-phase rubrics", "planner/RUBRIC_*.md"),
        ("run-loop state", "planner/RUN_LOOP_STATE.json"),
        ("manifest (mode/model/status)", ".pi_transcripts/manifest.json"),
        ("planner transcript", ".pi_transcripts/planner.session.jsonl"),
        ("execution transcript (goal mode only)", ".pi_transcripts/session.jsonl"),
        (
            "per-phase transcripts (multi_phase)",
            ".pi_transcripts/run_loop_sessions/*.jsonl",
        ),
        (
            "per-phase transcripts (still-live run)",
            ".home/.pi/agent/sessions/*/*.jsonl",
        ),
        ("the agent's write-ups", "writeups/"),
        ("the agent's per-phase write-ups", "phase_segment_*/writeups/"),
    ]


def _present(run_dir: Path, rel: str) -> bool:
    rel = rel.rstrip("/")
    if any(ch in rel for ch in "*?"):
        return bool(list(run_dir.glob(rel)))
    return (run_dir / rel).exists()


def run_layout_doc() -> str:
    """RUN_DIR_STRUCTURE.md — the general layout, staged into the audit agent's CWD.

    Written for the audit_agent mount convention (run READ-ONLY at ``/source``,
    writable CWD at ``/workspace``). Keep the path facts consistent with
    :func:`key_locations`.
    """
    return """# slopbench run directory structure

The source run is mounted READ-ONLY at /source. Read freely there, but write ONLY
inside your current working directory (/workspace). Exact paths vary by run —
TRACE_INDEX.md (in your CWD) lists what actually exists for this one.

## Layout (/source)
- proposal.md                         the project proposal/spec (may also be under planner/)
- planner/OVERALL_PLAN.md             the segment/phase plan (multi_phase)
- planner/INSTRUCTIONS_*.md, RUBRIC_*.md   per-phase worker instructions + grading rubrics
- planner/RUN_LOOP_STATE.json         run-loop state: segments, phases, decisions, costUsd
- .pi_transcripts/manifest.json       mode / model / status
- .pi_transcripts/planner.session.jsonl   the up-front planner transcript (/init-planner -> OVERALL_PLAN.md)
- .pi_transcripts/session.jsonl       goal mode ONLY: the single execution agent's full transcript
- .pi_transcripts/run_loop_sessions/*.jsonl   (multi_phase) the per-phase sub-agent transcripts:
                                      worker_<seg>_<phase>.jsonl (wrote + ran that phase's code),
                                      phase_planner_<seg>_<phase>.jsonl, and main_planner.jsonl (run-loop driver)
- .home/.pi/agent/sessions/*/*.jsonl  (still-live multi_phase) the same per-phase transcripts
- the agent's code, data/, results/, plots, and a writeups/ dir — at the run root (goal mode)
  and/or inside each phase working dir phase_segment_<seg>_phase_<n>/ (multi_phase)
- writeups/                           the agent's OWN write-ups: write_up.md (rolling summary),
                                      write_up_<label>.md, progress_log_<label>.md

## The two modes
- goal mode: a single execution agent (.pi_transcripts/session.jsonl) pursuing a goal; its
  code, data/, results/, and writeups/ live at the run root.
- multi_phase: an up-front planner (planner.session.jsonl) produces OVERALL_PLAN.md, then a
  run-loop decomposes the work into segments/phases. Each phase runs a worker (and a
  phase_planner) whose transcripts are in run_loop_sessions/, working in its own dir
  phase_segment_<seg>_phase_<n>/ with its own code, data/, results/, and writeups/.
  RUN_LOOP_STATE.json lists completed phases and decisions. READ EVERY PHASE — results and
  dead-ends often live only in the phase where they were produced; the rolling write_up.md is
  the agent's own summary, not ground truth.

## Reading order
1. /source/proposal.md (and planner/OVERALL_PLAN.md if present)
2. The rolling write_up.md (under writeups/) — a map, NOT ground truth
3. Per-phase write-ups (write_up_<label>.md, progress_log_<label>.md) across ALL phases
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


def trace_index(run_dir: str | Path) -> str:
    """TRACE_INDEX.md — the concrete ``/source`` paths that exist for THIS run.

    Built from :func:`key_locations`, filtered to what's actually present (globs
    resolved), so it never lists a path that isn't there.
    """
    run_dir = Path(run_dir)
    lines = [
        f"# Trace index for {run_dir.name}",
        "",
        "Source run is read-only at /source; write only in your CWD (/workspace).",
        "",
        "## Source run files that exist (read-only at /source)",
    ]
    present = [(label, rel) for label, rel in key_locations() if _present(run_dir, rel)]
    # A finished multi_phase run keeps both the folded run_loop_sessions/ transcripts
    # and leftover live .home sessions; the folded copies are canonical, so when both
    # exist list only the folded ones.
    folded = ".pi_transcripts/run_loop_sessions/*.jsonl"
    live = ".home/.pi/agent/sessions/*/*.jsonl"
    if any(rel == folded for _, rel in present):
        present = [(label, rel) for label, rel in present if rel != live]
    for label, rel in present:
        lines.append(f"- {label}: /source/{rel}")
    lines += [
        "",
        "Write your outputs ONLY into your CWD (/workspace) — see the task prompt for"
        " exactly what to produce.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Launch primitives — the shared `pi` invocation + sandbox environment.
# --------------------------------------------------------------------------- #
def pi_inner_argv(
    session: str,
    model: str,
    thinking: str,
    prompt: str,
    *,
    mode: str = "json",
) -> list[str]:
    """The ``pi -p --session ... --model ... --thinking ... --mode ... <prompt>``
    inner command run inside the sandbox (pass to ``sandbox.build_argv``)."""
    return [
        "pi",
        "-p",
        "--session",
        session,
        "--model",
        model,
        "--thinking",
        thinking,
        "--mode",
        mode,
        prompt,
    ]


def oversight_env(home: str, env_text: str | None = None) -> dict[str, str]:
    """Sandbox environment for an oversight agent: :func:`sandbox.default_env`
    seeded with the project ``.env`` secrets, with ``HOME`` pointed at ``home``
    (a writable scratch path inside the sandbox).

    ``env_text`` overrides the on-disk ``.env`` when provided.
    """
    overrides = parse_env_text(env_text) if env_text else {}
    if not env_text:
        env_path = ROOT / ".env"
        if env_path.exists():
            overrides = parse_env_text(env_path.read_text())
    env = sandbox.default_env(overrides)
    env["HOME"] = home
    return env


__all__ = [
    "is_run_dir",
    "key_locations",
    "run_layout_doc",
    "trace_index",
    "pi_inner_argv",
    "oversight_env",
]
